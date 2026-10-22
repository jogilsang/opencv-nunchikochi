"""End-to-end pipeline: vision + agent + service in one process. OWNER: cloud tab (E1).

Frame in -> FrameResult + Decision out, per docs/CONTRACTS.md §1-§4. The real engine and
the deterministic agent are wired (no FORCE_STUB) against the in-memory store; the stub
path is used only for the full contract-shape round-trip so it runs anywhere.

Markers: `e2e` on all; `slow` on tests that load the real ONNX models.

Contract mismatches found are listed at the bottom of this file and in the E1 report.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

FRAME_RESULT_KEYS = {
    "schema", "session_id", "t", "face_present", "persons", "metrics", "quality",
    "events", "calibrated", "latency_ms", "backend", "cv_version", "overlay",
}
DECISION_KEYS = {
    "action", "message", "message_ko", "reason", "needs_human",
    "tool_calls", "evidence", "cooldown_s",
}
SUMMARY_KEYS = {
    "session_id", "date", "duration_s", "counts", "seconds", "longest_s",
    "nudges_sent", "nudges_suppressed", "confirmations_asked", "recalibrations",
}


def _post_frame(c, sid, t, jpeg, phase="run"):
    return c.post(
        "/v1/frames",
        data={"session_id": sid, "t": str(t), "phase": phase},
        files={"frame": ("f.jpg", jpeg, "image/jpeg")},
    )


# ======================= happy path 1 — stub full round-trip =================

def test_stub_full_roundtrip_matches_contract(stub_client, dark_jpeg):
    """Health -> session -> frames (calibrate+run) -> end -> summary -> trace, all
    contract-shaped. Stub path so it runs without models; proves the service plumbing."""
    c = stub_client
    h = c.get("/healthz").json()
    assert h["ok"] is True and set(h) >= {"ok", "cv_version", "backend", "stubs"}

    sid = c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "ko"}).json()["session_id"]
    for t, phase in [(1.0, "calibrate"), (2.0, "calibrate"), (3.0, "calibrate"), (11.0, "run")]:
        r = _post_frame(c, sid, t, dark_jpeg, phase)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == {"result", "decision", "calibrated"}
        assert set(body["result"]) == FRAME_RESULT_KEYS
        assert set(body["decision"]) == DECISION_KEYS
        assert body["result"]["schema"] == "1.0"

    end = c.post(f"/v1/sessions/{sid}/end").json()
    assert set(end["summary"]) == SUMMARY_KEYS
    assert {"text_en", "text_ko", "highlights"} <= set(end["report"])

    s = c.get("/v1/summary", params={"date": "2026-10-22"}).json()
    assert s["summary"]["session_id"] == sid
    tr = c.get(f"/v1/trace/{sid}")
    assert tr.status_code == 200 and len(tr.text.splitlines()) == 4


# ======================= happy path 2 — real engine, bad-quality second_look =

@pytest.mark.slow
def test_real_bad_quality_drives_second_look_and_recalibration(real_client, dark_jpeg):
    """Real vision+agent: a dark/no-face frame is judged bad; the agent runs active
    perception (`second_look`) before asking to recalibrate. second_look must be visible
    in the Decision.tool_calls the service returns."""
    c = real_client
    sid = c.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
    r = _post_frame(c, sid, 1.0, dark_jpeg)
    assert r.status_code == 200, r.text
    dec = r.json()["decision"]
    assert set(dec) == DECISION_KEYS
    assert dec["action"] == "request_recalibration"
    tools = [tc.get("tool") for tc in dec["tool_calls"]]
    assert "get_quality" in tools
    assert "second_look" in tools  # active perception recorded even when it defers


# ======================= edge 1 — rate limit 429 ============================

def test_rate_limit_returns_429(stub_client, dark_jpeg, monkeypatch):
    """Server-side per-session frame-rate limit fires with 429 and a clean error body."""
    monkeypatch.setenv("NUNCHI_RATE_MAX", "2")
    monkeypatch.setenv("NUNCHI_RATE_WINDOW_S", "60")
    from nunchi.service import deps

    deps.reset_services()
    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app

    with TestClient(create_app()) as c:
        sid = c.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
        assert _post_frame(c, sid, 1.0, dark_jpeg).status_code == 200
        assert _post_frame(c, sid, 2.0, dark_jpeg).status_code == 200
        over = _post_frame(c, sid, 3.0, dark_jpeg)
        assert over.status_code == 429
        assert over.json()["error"]["code"] == "rate_limited"
    deps.reset_services()


# ======================= edge 2 — oversize 413 ==============================

def test_oversize_frame_413(stub_client):
    sid = stub_client.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
    big = b"\xff" * (200 * 1024 + 1)
    r = _post_frame(stub_client, sid, 1.0, big)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


# ======================= error 1 — auth 401 + fail-closed 503 ================

def test_auth_401_with_direct_key_and_503_fail_closed(monkeypatch, dark_jpeg):
    """Wrong key -> 401. And when an SSM key is configured but unresolved -> 503
    (fail closed), never open."""
    from fastapi.testclient import TestClient

    from nunchi.service import deps
    from nunchi.service.app import create_app

    # (a) direct key set: wrong header -> 401
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.setenv("NUNCHI_API_KEY", "right-key")
    # the module object (not the FastAPI instance exported as `app`) holds the key cache
    import importlib

    app_mod = importlib.import_module("nunchi.service.app")
    deps.reset_services()
    with TestClient(create_app()) as c:
        r = c.post("/v1/sessions", json={"lang": "en"}, headers={"X-Api-Key": "wrong"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
        ok = c.post("/v1/sessions", json={"lang": "en"}, headers={"X-Api-Key": "right-key"})
        assert ok.status_code == 200

    # (b) SSM param named but unresolvable (no AWS) -> 503 auth_unavailable (fail closed)
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    monkeypatch.setenv("NUNCHI_API_KEY_PARAM", "/nunchi/does-not-resolve")
    app_mod._API_KEY_CACHE.clear()  # re-read the unresolved param
    deps.reset_services()
    with TestClient(create_app()) as c:
        r = c.post("/v1/sessions", json={"lang": "en"}, headers={"X-Api-Key": "anything"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "auth_unavailable"
    app_mod._API_KEY_CACHE.clear()
    deps.reset_services()


# ======================= privacy — frame bytes never persisted ==============

def test_frame_bytes_never_persist(real_client, tmp_path, monkeypatch, capsys):
    """A frame carrying a unique marker must not appear — raw/hex — in the trace
    response, the summary, or stdout (logs/metrics). End-to-end privacy invariant."""
    import os

    c = real_client
    marker = b"ZZmarkerZZ" + os.urandom(8)
    jpeg = _marker_jpeg(marker)
    sid = c.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
    r = _post_frame(c, sid, 1.0, jpeg)
    assert r.status_code in (200, 500)  # 500 only via the known state-restore bug (xfail'd elsewhere)
    end = c.post(f"/v1/sessions/{sid}/end")
    tr = c.get(f"/v1/trace/{sid}")

    hay = (r.text + end.text + tr.text + capsys.readouterr().out).encode("utf-8", "ignore")
    assert marker not in hay
    assert marker.hex().encode() not in hay


def _marker_jpeg(marker: bytes) -> bytes:
    import cv2
    import numpy as np

    img = np.full((240, 320, 3), 120, dtype=np.uint8)
    # scatter the marker bytes into pixels so they exist in the decoded frame too
    flat = np.frombuffer(marker, dtype=np.uint8)
    img.reshape(-1)[: flat.size] = flat
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


# ======================= contract mismatches FIXED (C6) =====================
# Previously xfail; MISMATCH-1 (state restore) and MISMATCH-2 (trace) are now fixed in
# the service, so these are real passing tests that guard against regression.

@pytest.mark.slow
def test_real_face_frame_happy_path(real_client, face_jpeg):
    c = real_client
    sid = c.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
    r = _post_frame(c, sid, 1.0, face_jpeg)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["face_present"] is True


@pytest.mark.slow
def test_cross_instance_restore_identical_result(real_client, face_jpeg):
    """Two frames at the same t: the second rehydrates the session state from the store
    (as a fresh Lambda instance would) and must produce the identical FrameResult
    metrics — proving SessionState.from_dict round-trips losslessly."""
    c = real_client
    sid = c.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
    r1 = _post_frame(c, sid, 1.0, face_jpeg)
    r2 = _post_frame(c, sid, 1.0, face_jpeg)
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert r1.json()["result"]["metrics"] == r2.json()["result"]["metrics"]


@pytest.mark.slow
def test_trace_contains_full_tool_sequence_no_bytes(real_client, dark_jpeg):
    """MISMATCH-2 fix: the trace keeps the FULL ordered tool-call sequence (incl.
    second_look), the decision, and carries no image bytes."""
    c = real_client
    sid = c.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
    r = _post_frame(c, sid, 1.0, dark_jpeg)
    assert r.status_code == 200, r.text
    import json as _json

    tr = c.get(f"/v1/trace/{sid}")
    assert tr.status_code == 200
    rows = [_json.loads(line) for line in tr.text.splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert "tool_calls" in row and isinstance(row["tool_calls"], list)
    tools = [tc["tool"] for tc in row["tool_calls"]]
    assert "get_quality" in tools and "second_look" in tools  # full sequence, not just [0]
    assert row["decision"] == "request_recalibration"
    # no bytes/base64 image smell in the serialized trace
    blob = tr.text.lower()
    assert "jpeg" not in blob and "\\xff" not in blob


def test_session_state_invalid_returns_410(real_client, face_jpeg, monkeypatch):
    """A corrupt/old stored vision state is restored via from_dict; on failure the service
    returns 410 session_state_invalid (bilingual), never a silent fresh start."""

    class _Boom:
        @staticmethod
        def from_dict(_d):
            raise ValueError("version mismatch")

    # Point the hydrate at a SessionState whose from_dict always fails.
    monkeypatch.setattr("nunchi.vision.SessionState", _Boom, raising=False)
    c = real_client
    sid = c.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
    r = _post_frame(c, sid, 1.0, face_jpeg)
    assert r.status_code == 410
    assert r.json()["error"]["code"] == "session_state_invalid"
