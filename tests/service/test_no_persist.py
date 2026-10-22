"""Prove frames are never persisted. OWNER: cloud tab.

Privacy is a competition judging criterion (ARCHITECTURE "개인정보"): the service must
hold frame bytes only in memory during a request. This test uploads a JPEG carrying a
unique marker, then asserts the marker — raw, hex and base64 — appears in NO new file
under temp/cwd and in NO captured log output after processing.

We also assert the persisted session summary and the trace contain no image fields.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import pathlib
import tempfile

import cv2
import numpy as np


def _marked_jpeg() -> tuple[bytes, bytes]:
    """A valid JPEG whose pixels encode a recognisable marker, plus the marker bytes.

    The marker is a fixed byte string we search for afterwards. We embed it by also
    appending it as a trailing comment segment so it survives as literal bytes in the
    JPEG payload (decoders ignore trailing bytes), guaranteeing a concrete needle.
    """
    img = np.full((240, 320, 3), 77, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    marker = b"NUNCHI_FRAME_MARKER_0xDEADBEEF_SECRET"
    jpeg = buf.tobytes() + marker  # literal needle inside the uploaded bytes
    return jpeg, marker


def _snapshot_files(roots: list[pathlib.Path]) -> set[pathlib.Path]:
    seen: set[pathlib.Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file():
                seen.add(p)
    return seen


def _needles(marker: bytes) -> list[bytes]:
    return [
        marker,
        marker.hex().encode(),
        base64.b64encode(marker),
        base64.b64encode(marker).rstrip(b"="),  # unpadded b64 variant
    ]


def test_frame_bytes_never_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)

    # Redirect temp + cwd into an isolated sandbox so we can diff file trees.
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    tempfile.tempdir = str(tmpdir)
    old_cwd = os.getcwd()
    os.chdir(sandbox)

    # Capture ALL logging at DEBUG into a buffer.
    import io

    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    prev_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    try:
        from nunchi.service import deps

        deps.reset_services()
        from fastapi.testclient import TestClient

        from nunchi.service.app import create_app

        roots = [sandbox, tmpdir]
        before = _snapshot_files(roots)

        with TestClient(create_app()) as c:
            sid = c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"}).json()[
                "session_id"
            ]
            jpeg, marker = _marked_jpeg()
            for t, phase in [(1.0, "calibrate"), (2.0, "calibrate"), (3.0, "calibrate"), (11.0, "run")]:
                r = c.post(
                    "/v1/frames",
                    data={"session_id": sid, "t": str(t), "phase": phase},
                    files={"frame": ("f.jpg", jpeg, "image/jpeg")},
                )
                assert r.status_code == 200, r.text
            end = c.post(f"/v1/sessions/{sid}/end").json()
            trace = c.get(f"/v1/trace/{sid}").text

        after = _snapshot_files(roots)
        new_files = after - before
        needles = _needles(marker)

        # (a) No new file under temp/cwd contains the marker in any encoding.
        for f in new_files:
            data = f.read_bytes()
            for n in needles:
                assert n not in data, f"marker leaked into new file {f}"

        # (b) No captured log line contains the marker in any encoding.
        logged = log_buf.getvalue().encode()
        for n in needles:
            assert n not in logged, "marker leaked into logs"

        # (c) Persisted summary + trace carry no image/marker bytes.
        blob = (json.dumps(end) + trace).encode()
        for n in needles:
            assert n not in blob, "marker leaked into summary/trace response"
        for banned in (b"image", b"jpeg", b"base64", b"data:image"):
            assert banned not in trace.encode().lower(), f"trace exposes {banned!r}"
    finally:
        os.chdir(old_cwd)
        root_logger.removeHandler(handler)
        root_logger.setLevel(prev_level)
        tempfile.tempdir = None
        from nunchi.service import deps

        deps.reset_services()


def test_vision_error_does_not_leak_bytes(monkeypatch, tmp_path):
    """An undecodable frame must yield a generic error with no byte content echoed."""
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.delenv("NUNCHI_FORCE_STUB", raising=False)
    # Force the REAL vision path so decode is attempted; if real vision is absent this
    # still exercises the stub (which won't raise), so we only assert no-leak, not status.
    from nunchi.service import deps

    deps.reset_services()
    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app

    marker = b"NOT_A_JPEG_MARKER_0xBADF00D"
    with TestClient(create_app()) as c:
        sid = c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"}).json()[
            "session_id"
        ]
        r = c.post(
            "/v1/frames",
            data={"session_id": sid, "t": "1.0", "phase": "run"},
            files={"frame": ("f.jpg", b"\xff\xd8" + marker, "image/jpeg")},
        )
        body = r.text.encode()
        assert marker not in body
        assert base64.b64encode(marker) not in body
    deps.reset_services()
