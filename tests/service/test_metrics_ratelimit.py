"""C5 — EMF metrics format + per-session frame-rate limit. OWNER: cloud tab.

Covers: rate-limit 429 (normal + edge), EMF record shape, and the privacy invariant that
metrics never carry image bytes / api keys / response bodies.
"""
from __future__ import annotations

import importlib
import json

import pytest

# ------------------------- EMF metrics format -------------------------------

def _emf_records(capsys) -> list[dict]:
    out = capsys.readouterr().out
    recs = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{") and '"_aws"' in line:
            recs.append(json.loads(line))
    return recs


def test_emf_frame_metric_is_valid_and_has_no_pixels(capsys):
    """frame_processed emits a well-formed EMF record with latency + decision, and nothing
    that could be image bytes or a secret."""
    m = importlib.import_module("nunchi.service.metrics")
    m.frame_processed(12.5, "nudge")
    recs = _emf_records(capsys)
    assert len(recs) == 1
    rec = recs[0]
    # EMF skeleton
    cw = rec["_aws"]["CloudWatchMetrics"][0]
    assert cw["Namespace"] == "nunchikochi"
    names = {md["Name"] for md in cw["Metrics"]}
    assert {"FrameLatencyMs", "Decisions"} <= names
    assert rec["FrameLatencyMs"] == 12.5
    assert rec["Decision"] == "nudge"
    # privacy: values are only numbers + the bounded dimension string
    blob = json.dumps(rec)
    assert "jpeg" not in blob.lower() and "\\xff" not in blob
    assert all(not isinstance(v, (bytes, bytearray)) for v in rec.values())


def test_emf_error_and_session_and_ratelimit_records(capsys):
    m = importlib.import_module("nunchi.service.metrics")
    m.error("payload_too_large")
    m.session_event("create")
    m.rate_limited()
    recs = _emf_records(capsys)
    assert len(recs) == 3
    assert recs[0]["ErrorCode"] == "payload_too_large" and recs[0]["Errors"] == 1
    assert recs[1]["Event"] == "create" and recs[1]["Sessions"] == 1
    assert recs[2]["RateLimited"] == 1


def test_metrics_disabled_emits_nothing(capsys, monkeypatch):
    monkeypatch.setenv("NUNCHI_METRICS", "0")
    m = importlib.reload(importlib.import_module("nunchi.service.metrics"))
    m.frame_processed(1.0, "none")
    assert _emf_records(capsys) == []
    monkeypatch.delenv("NUNCHI_METRICS", raising=False)
    importlib.reload(m)  # restore enabled state for other tests


# ------------------------- per-session rate limit ---------------------------

@pytest.fixture()
def rl_client(monkeypatch):
    """A client with a tiny rate limit (2 frames / 60s) so the edge is easy to hit."""
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.setenv("NUNCHI_RATE_MAX", "2")
    monkeypatch.setenv("NUNCHI_RATE_WINDOW_S", "60")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    from nunchi.service import deps

    deps.reset_services()
    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app

    with TestClient(create_app()) as c:
        yield c
    deps.reset_services()


def _post_frame(c, sid, t, jpeg):
    return c.post(
        "/v1/frames",
        data={"session_id": sid, "t": str(t), "phase": "run"},
        files={"frame": ("f.jpg", jpeg, "image/jpeg")},
    )


def test_rate_limit_allows_up_to_max_then_429(rl_client, jpeg_bytes):
    r = rl_client.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"})
    sid = r.json()["session_id"]
    assert _post_frame(rl_client, sid, 1.0, jpeg_bytes).status_code == 200  # 1st
    assert _post_frame(rl_client, sid, 2.0, jpeg_bytes).status_code == 200  # 2nd (== max)
    over = _post_frame(rl_client, sid, 3.0, jpeg_bytes)                     # 3rd -> blocked
    assert over.status_code == 429
    assert over.json()["error"]["code"] == "rate_limited"


def test_rate_limit_is_per_session_not_global(rl_client, jpeg_bytes):
    a = rl_client.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
    b = rl_client.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
    assert _post_frame(rl_client, a, 1.0, jpeg_bytes).status_code == 200
    assert _post_frame(rl_client, a, 2.0, jpeg_bytes).status_code == 200
    assert _post_frame(rl_client, a, 3.0, jpeg_bytes).status_code == 429
    # a different session still has its own budget
    assert _post_frame(rl_client, b, 1.0, jpeg_bytes).status_code == 200


def test_rate_limited_body_has_no_frame_bytes(rl_client):
    """429 body is a plain error code, never the uploaded bytes."""
    sid = rl_client.post("/v1/sessions", json={"lang": "en"}).json()["session_id"]
    marker = b"\xde\xad\xbe\xefMARKER" + b"\xff" * 2048
    for t in (1.0, 2.0, 3.0):
        r = rl_client.post(
            "/v1/frames",
            data={"session_id": sid, "t": str(t), "phase": "run"},
            files={"frame": ("f.jpg", marker, "image/jpeg")},
        )
    assert r.status_code == 429
    assert "MARKER" not in r.text and "deadbeef" not in r.text.lower()
    assert set(r.json()["error"]) == {"code", "message"}
