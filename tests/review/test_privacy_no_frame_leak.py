"""Independent verifier (Q1) — adversarial 'frame never persists' counter-tests.

OWNER: review (verifier). This file is NOT the cloud tab's own test; it independently
attacks the privacy claim from angles the owning test does not, WITHOUT modifying any
source. If any of these fail, that is a finding for the cloud tab — do not fix here.

Angles beyond tests/service/test_no_persist.py:
  1. The in-memory STATE STORE (what would be written to DynamoDB) never contains the
     marker, in any encoding, after several frames — tracked by reading the store directly.
  2. The EMF metrics stream (stdout JSON lines → CloudWatch) never contains the marker.
  3. The /v1/trace payload never contains image/base64 tokens across many frames.
All in stub mode (no real models, no network).
"""
from __future__ import annotations

import base64
import io
import json
import sys

import cv2
import numpy as np
import pytest

MARKER = b"NUNCHI_Q1_VERIFIER_MARKER_0xFEEDFACE"


def _needles() -> list[bytes]:
    return [
        MARKER,
        MARKER.hex().encode(),
        base64.b64encode(MARKER),
        base64.b64encode(MARKER).rstrip(b"="),
    ]


def _marked_jpeg() -> bytes:
    img = np.full((240, 320, 3), 99, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes() + MARKER  # literal needle appended as trailing bytes


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    monkeypatch.delenv("NUNCHI_API_KEY_PARAM", raising=False)
    import importlib

    from fastapi.testclient import TestClient

    from nunchi.service import deps

    # The package attr `nunchi.service.app` is shadowed by the FastAPI instance
    # (__init__ does `from .app import app`), so get the real module explicitly.
    app_mod = importlib.import_module("nunchi.service.app")

    deps.reset_services()
    # Capture the state store instance the app will use, so we can read it directly.
    # app.py calls the module-level name `make_state_store`, so patch it there.
    captured: dict = {}
    real_make = app_mod.make_state_store

    def _capturing_make(*a, **k):
        store = real_make(*a, **k)
        captured["store"] = store
        return store

    monkeypatch.setattr(app_mod, "make_state_store", _capturing_make)

    the_app = app_mod.create_app()
    with TestClient(the_app) as c:
        yield c, captured
    deps.reset_services()


def _run_frames(c) -> str:
    sid = c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"}).json()[
        "session_id"
    ]
    jpeg = _marked_jpeg()
    for t, phase in [(1.0, "calibrate"), (2.0, "run"), (3.0, "run"), (4.0, "run")]:
        r = c.post(
            "/v1/frames",
            data={"session_id": sid, "t": str(t), "phase": phase},
            files={"frame": ("f.jpg", jpeg, "image/jpeg")},
        )
        assert r.status_code == 200, r.text
    return sid


def test_state_store_never_holds_frame_bytes(client):
    """The session STATE (the thing persisted to DynamoDB) carries no frame bytes."""
    c, captured = client
    sid = _run_frames(c)
    store = captured.get("store")
    assert store is not None, "could not capture the state store"
    state = store.get(sid)
    assert state is not None, "session state missing mid-session"
    blob = json.dumps(state, default=str).encode()
    for n in _needles():
        assert n not in blob, "frame marker leaked into persisted session STATE"
    # also no obvious image fields
    for banned in (b"jpeg", b"image", b"base64", b"/9j/"):
        assert banned not in blob.lower(), f"state exposes {banned!r}"


def test_emf_metrics_stream_has_no_frame_bytes(client, monkeypatch):
    """EMF metric lines (stdout → CloudWatch) carry numbers + labels only, no marker."""
    c, _ = client
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    try:
        _run_frames(c)
    finally:
        monkeypatch.undo()
    emitted = buf.getvalue().encode()
    for n in _needles():
        assert n not in emitted, "frame marker leaked into EMF metrics"
    # the EMF lines that are present must be valid JSON with only known fields
    for line in buf.getvalue().splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        doc = json.loads(line)
        if "_aws" in doc:  # an EMF record
            for key in doc:
                assert key in {"_aws", "Decision", "ErrorCode", "Event",
                               "FrameLatencyMs", "Decisions", "Errors",
                               "Sessions", "RateLimited"}, f"unexpected EMF field {key}"


def test_trace_endpoint_has_no_image_tokens_over_many_frames(client):
    """/v1/trace never exposes image/base64 tokens, even after several frames."""
    c, _ = client
    sid = _run_frames(c)
    trace = c.get(f"/v1/trace/{sid}").text
    low = trace.encode().lower()
    for banned in (b"jpeg", b"image", b"base64", b"data:image", b"/9j/"):
        assert banned not in low, f"trace exposes {banned!r}"
    for n in _needles():
        assert n not in trace.encode(), "marker leaked into trace"
    # trace lines must be valid NDJSON with no bytes-ish fields
    for line in trace.splitlines():
        if line.strip():
            row = json.loads(line)
            assert set(row).issubset(
                {"ts", "session_id", "frame_t", "decision", "reason",
                 "tool_calls", "evidence"}
            ), f"unexpected trace field in {set(row)}"
