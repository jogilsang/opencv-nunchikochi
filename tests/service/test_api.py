"""HTTP contract tests (CONTRACTS §3). OWNER: cloud tab.

Coverage: 2 happy paths, 2 edge/exception paths, 1 error path, plus auth & CORS.
Runs against stubs (conftest forces NUNCHI_FORCE_STUB=1), so shapes are the contract,
not an accident of the real vision/agent wiring.
"""
from __future__ import annotations


# --- happy path 1: healthz reports contract fields -------------------------
def test_healthz_shape(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    for k in ("ok", "cv_version", "backend", "arch", "build", "stubs"):
        assert k in body, f"missing {k}"
    assert body["ok"] is True
    assert body["stubs"] is True  # conftest forces stubs


# --- happy path 2: full session round-trip ---------------------------------
def test_session_frame_end_roundtrip(client, make_session, jpeg_bytes):
    sid = make_session(lang="ko")

    # calibrate frames then a run frame that triggers the stub's head_tilt -> nudge
    actions = []
    for t, phase in [(1.0, "calibrate"), (2.0, "calibrate"), (3.0, "calibrate"), (11.0, "run")]:
        r = client.post(
            "/v1/frames",
            data={"session_id": sid, "t": str(t), "phase": phase},
            files={"frame": ("f.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert set(j) == {"result", "decision", "calibrated"}
        assert j["result"]["schema"] == "1.0"
        actions.append(j["decision"]["action"])
    assert j["calibrated"] is True
    assert "nudge" in actions  # the sustained head_tilt at t>=10 drove a nudge

    end = client.post(f"/v1/sessions/{sid}/end")
    assert end.status_code == 200, end.text
    ebody = end.json()
    assert ebody["summary"]["session_id"] == sid
    assert ebody["summary"]["nudges_sent"] >= 1
    assert {"text_en", "text_ko", "highlights"} <= set(ebody["report"])

    # summary by date and trace
    s = client.get("/v1/summary", params={"date": "2026-10-22"})
    assert s.status_code == 200 and s.json()["summary"]["session_id"] == sid
    tr = client.get(f"/v1/trace/{sid}")
    assert tr.status_code == 200
    assert len(tr.text.splitlines()) == 4  # one trace line per frame


# --- edge 1: oversize frame rejected with 413 (independent of session) -----
def test_frame_too_large(client, make_session):
    sid = make_session()
    big = b"\xff" * (200 * 1024 + 1)
    r = client.post(
        "/v1/frames",
        data={"session_id": sid, "t": "1.0", "phase": "run"},
        files={"frame": ("f.jpg", big, "image/jpeg")},
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


# --- edge 2: bad inputs (t out of range, wrong mime, bad phase) -------------
def test_bad_inputs(client, make_session, jpeg_bytes):
    sid = make_session()
    # t out of range
    r = client.post("/v1/frames", data={"session_id": sid, "t": "-5", "phase": "run"},
                    files={"frame": ("f.jpg", jpeg_bytes, "image/jpeg")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"
    # unsupported mime
    r = client.post("/v1/frames", data={"session_id": sid, "t": "1.0", "phase": "run"},
                    files={"frame": ("f.png", jpeg_bytes, "image/png")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "unsupported_media"
    # bad phase
    r = client.post("/v1/frames", data={"session_id": sid, "t": "1.0", "phase": "warmup"},
                    files={"frame": ("f.jpg", jpeg_bytes, "image/jpeg")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"


# --- error path: unknown session -------------------------------------------
def test_unknown_session(client, jpeg_bytes):
    r = client.post("/v1/frames", data={"session_id": "does-not-exist", "t": "1.0", "phase": "run"},
                    files={"frame": ("f.jpg", jpeg_bytes, "image/jpeg")})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "session_not_found"


# --- auth: api key enforced when configured --------------------------------
def test_api_key_enforced(monkeypatch, make_session, jpeg_bytes):
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.setenv("NUNCHI_API_KEY", "secret-key")
    from nunchi.service import deps

    deps.reset_services()
    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app

    with TestClient(create_app()) as c:
        # no key -> 401
        r = c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
        # correct key -> 200
        r = c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"},
                   headers={"X-Api-Key": "secret-key"})
        assert r.status_code == 200
    deps.reset_services()


def test_lang_validation(client):
    r = client.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "fr"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"
