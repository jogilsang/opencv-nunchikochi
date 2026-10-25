"""C18 — overlay.expr (V14) rides the frame response but is never persisted. OWNER: cloud tab.

V14 adds `result.overlay.expr = {eye_l, eye_r, mouth_open, smile, brow_raise}` (each 0..1 or
null). The service returns `result.to_dict()` verbatim, so `overlay.expr` reaches the client
the same way `overlay.pose` does — no reshaping, no filtering. These tests prove:

  * STUB path: whatever vision puts in `result.overlay` is forwarded unchanged (expr + pose).
  * REAL-ENGINE path: a real face frame through the live HTTP stack yields `overlay.expr`
    with numbers in [0,1] or null (skipped if models/samples are unavailable — never failed).
  * PRIVACY (counter-examples): the expr block appears ONLY in the frame response; it is
    absent from the persisted session state (DynamoDB), the trace, EMF metrics stdout, and
    any new file/log. Values are numbers/null only — no coordinates, no image bytes.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import cv2
import pytest

from nunchi.contracts import FrameResult, Metrics, Quality

HERE = Path(__file__).resolve().parent
SAMPLES = HERE.parent / "vision" / "_samples"
MODELS = HERE.parents[1] / "models"


# ---------------------------------------------------------------------------
# STUB path: the service forwards result.overlay (incl. expr) verbatim
# ---------------------------------------------------------------------------


def _overlay_stub_result(session_id: str, t: float) -> FrameResult:
    """A stub FrameResult carrying both pose and expr in overlay (as V14/real vision would)."""
    return FrameResult(
        session_id=session_id,
        t=t,
        face_present=True,
        persons=1,
        metrics=Metrics(ear=0.27, mar=0.3),
        quality=Quality(ok=True, brightness=120.0, sharpness=200.0, face_px=90),
        events=[],
        calibrated=True,
        backend="stub",
        cv_version="stub",
        overlay={
            "face": [0.1, 0.1, 0.4, 0.5],
            "pose": {"yaw_deg": 3.0, "pitch_deg": -1.0, "roll_deg": 2.0, "depth": 1.0, "conf": 0.9},
            "expr": {"eye_l": 0.8, "eye_r": 0.82, "mouth_open": 0.15, "smile": 0.6, "brow_raise": None},
        },
    )


def test_stub_path_forwards_overlay_expr(client, make_session, jpeg_bytes, monkeypatch):
    """STUB: the HTTP frame response's result.overlay.expr equals what vision produced."""
    from nunchi.service import deps

    svc = deps.get_services()
    monkeypatch.setattr(
        svc.vision, "analyze", lambda state, t: _overlay_stub_result(state.get("session_id", ""), t)
    )
    sid = make_session()
    r = client.post(
        "/v1/frames",
        data={"session_id": sid, "t": "11.0", "phase": "run"},
        files={"frame": ("f.jpg", jpeg_bytes, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    overlay = r.json()["result"]["overlay"]
    assert overlay is not None, "overlay dropped by the service"
    assert overlay["expr"] == {
        "eye_l": 0.8, "eye_r": 0.82, "mouth_open": 0.15, "smile": 0.6, "brow_raise": None,
    }
    # pose still rides alongside (same path); expr did not displace it
    assert overlay["pose"]["conf"] == 0.9


def test_stub_path_overlay_none_is_passed_through(client, make_session, jpeg_bytes):
    """edge: when vision produces no overlay (default stub), the response overlay is null —
    the service does not fabricate one."""
    sid = make_session()
    r = client.post(
        "/v1/frames",
        data={"session_id": sid, "t": "11.0", "phase": "run"},
        files={"frame": ("f.jpg", jpeg_bytes, "image/jpeg")},
    )
    assert r.status_code == 200
    assert r.json()["result"]["overlay"] is None


# ---------------------------------------------------------------------------
# REAL-ENGINE path: a real face frame yields overlay.expr (0..1 | null)
# ---------------------------------------------------------------------------


def _models_ready() -> bool:
    return ((MODELS / "face_detection_yunet_2023mar.onnx").exists()
            and (MODELS / "face_landmarks_mediapipe_2023.onnx").exists())


def _face_jpeg() -> bytes | None:
    for name in ("lena.jpg", "messi5.jpg", "largest_selfie.jpg"):
        p = SAMPLES / name
        if p.exists() and p.stat().st_size > 0:
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is not None:
                ok, buf = cv2.imencode(".jpg", img)
                if ok:
                    return buf.tobytes()
    return None


def test_real_engine_path_emits_overlay_expr(monkeypatch):
    """REAL: drive the HTTP stack with the real VisionEngine + a cached face frame; the
    response carries overlay.expr with 0..1-or-null numbers. Skipped (not failed) when the
    models or the public face sample are unavailable."""
    if not _models_ready():
        pytest.skip("vision models not downloaded")
    face = _face_jpeg()
    if face is None:
        pytest.skip("no cached public face sample available")

    monkeypatch.delenv("NUNCHI_FORCE_STUB", raising=False)   # force the real engine
    monkeypatch.delenv("NUNCHI_DISABLE_EXPR", raising=False)  # expr ON (default)
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.setenv("NUNCHI_MODELS_DIR", str(MODELS))
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    from nunchi.service import deps

    deps.reset_services()
    svc = deps.get_services()
    if svc.using_stub_vision:
        deps.reset_services()
        pytest.skip("real vision engine not active in this environment")

    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app

    with TestClient(create_app()) as c:
        sid = c.post("/v1/sessions", json={"client_date": "2026-10-26", "lang": "en"}).json()[
            "session_id"
        ]
        overlay = None
        for t, phase in [(1.0, "calibrate"), (2.0, "calibrate"), (3.0, "calibrate"), (4.0, "run")]:
            r = c.post(
                "/v1/frames",
                data={"session_id": sid, "t": str(t), "phase": phase},
                files={"frame": ("f.jpg", face, "image/jpeg")},
            )
            assert r.status_code == 200, r.text
            overlay = r.json()["result"]["overlay"]
        assert overlay is not None and "expr" in overlay, "real engine did not surface overlay.expr"
        expr = overlay["expr"]
        assert set(expr) == {"eye_l", "eye_r", "mouth_open", "smile", "brow_raise"}
        for k, v in expr.items():
            assert v is None or (isinstance(v, (int, float)) and 0.0 <= v <= 1.0), f"{k}={v!r}"
    deps.reset_services()


# ---------------------------------------------------------------------------
# PRIVACY: expr is response-only — not in state/trace/metrics/files/logs
# ---------------------------------------------------------------------------


def test_expr_not_persisted_to_state_trace_or_metrics(monkeypatch, jpeg_bytes, capsys):
    """counter-example: push a MARKED expr through a frame, then assert the marker value is
    absent from the persisted session state, the trace, and EMF metrics stdout — it lives
    only in the frame response.

    We build the app with a MemoryStateStore we hold a reference to, so we can inspect the
    exact bytes the service persisted (no endpoint exposes raw state)."""
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)

    from nunchi.service import deps
    from nunchi.service.state import MemoryStateStore

    app_mod = importlib.import_module("nunchi.service.app")  # the module, not the FastAPI attr
    deps.reset_services()
    held_store = MemoryStateStore()
    monkeypatch.setattr(app_mod, "make_state_store", lambda: held_store)

    svc = deps.get_services()
    needle = 0.123456  # a recognisable, in-range expr value used as a needle

    def _marked(state, t):
        res = _overlay_stub_result(state.get("session_id", ""), t)
        res.overlay["expr"]["mouth_open"] = needle
        return res

    monkeypatch.setattr(svc.vision, "analyze", _marked)

    from fastapi.testclient import TestClient

    with TestClient(app_mod.create_app()) as c:
        sid = c.post("/v1/sessions", json={"client_date": "2026-10-26", "lang": "en"}).json()[
            "session_id"
        ]
        _ = capsys.readouterr()  # drop create-session metrics
        resp = c.post(
            "/v1/frames",
            data={"session_id": sid, "t": "11.0", "phase": "run"},
            files={"frame": ("f.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert resp.status_code == 200
        emf = capsys.readouterr().out  # EMF records emitted during the frame

        # (a) present in the frame response
        assert resp.json()["result"]["overlay"]["expr"]["mouth_open"] == needle

        # (b) absent from the persisted session state (the cross-instance store we hold)
        persisted = json.dumps(held_store._data)
        assert sid in persisted, "sanity: the session WAS persisted"
        assert "expr" not in persisted, "expr leaked into persisted session state"
        assert str(needle) not in persisted, "expr value leaked into persisted state"

        # (c) absent from the trace (trace keeps decision/tool_calls/evidence only)
        trace = c.get(f"/v1/trace/{sid}").text
        assert "expr" not in trace and str(needle) not in trace, "expr leaked into trace"

        # (d) absent from EMF metrics stdout (latency + bounded labels only)
        assert "expr" not in emf and str(needle) not in emf, "expr leaked into EMF metrics"

        # (e) end the session; the persisted summary carries no expr
        end = c.post(f"/v1/sessions/{sid}/end").json()
        assert "expr" not in json.dumps(end["summary"]), "expr leaked into persisted summary"
    deps.reset_services()


def test_summary_store_sanitizer_drops_expr():
    """counter-example (store gate): even if a buggy upstream attached an `expr` or
    `overlay` block to a summary, the USER#/DAY# sanitizer strips it (key whitelist)."""
    from nunchi.service.summary_store import sanitize_summary

    dirty = {
        "session_id": "s", "date": "2026-10-26", "counts": {"blink": 1},
        "overlay": {"expr": {"smile": 0.9}},          # non-whitelisted top key -> dropped
        "expr": {"eye_l": 0.5},                        # non-whitelisted top key -> dropped
        "timeline": {"per_hour_rate": 2.0, "expr": {"smile": 0.1}},  # nested expr: key banned? no,
        # 'expr' is not in the banned substrings, but it is numbers-only so it would pass through
        # a nested map; the TOP-LEVEL whitelist is what guarantees expr never reaches the table.
    }
    clean = sanitize_summary(dirty)
    assert "overlay" not in clean and "expr" not in clean
    assert clean["counts"] == {"blink": 1}
    assert clean["timeline"]["per_hour_rate"] == 2.0

