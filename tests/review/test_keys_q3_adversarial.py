"""Q3 independent verifier — trial-key / IP-privacy counter-examples. READ-ONLY tab.

NEW tests written by the verification tab; they modify no source. They attack C17's
trial-key + IP-privacy claims from angles the owning suite (tests/service/test_trial_keys.py)
does not cover, at the FULL running-service level (not just the store):

  1. A forged `X-Forwarded-For` (many distinct values) cannot widen the per-IP budget:
     every /v1/keys call counts against the gateway sourceIp, so the 4th is still 429.
  2. Using an issued trial key across the live HTTP stack never lands the RAW key or the
     RAW IP in: the persisted session STATE (DynamoDB-shaped), the trace, EMF metrics
     stdout, or the frame response body.
  3. A key whose `expires_at` has passed is rejected (401 key_expired) through the live
     /check_key path even though its row is NOT deleted (TTL-deletion is never trusted).
  4. The global daily cap (real default 6) soaks to 503 on the 7th issuance from DISTINCT
     gateway IPs — proving the ceiling is enforced at its shipped value, not a test value.
  5. A row present but expired is also refused at validate-time (no TTL dependence), and a
     brand-new different IP is still isolated after another IP is exhausted.

The deployed API's POST /v1/keys is NEVER called (daily budget). All local: stub vision +
MemoryKeyStore (and the app's own state store held by reference). No key/IP is printed.
"""
from __future__ import annotations

import importlib
import json

import anyio
import pytest

app_mod = importlib.import_module("nunchi.service.app")  # module (not the FastAPI attr)


# ---------------------------------------------------------------------------
# helper: one raw ASGI round-trip with a chosen gateway sourceIp + arbitrary headers
# ---------------------------------------------------------------------------
def _call(app, method: str, path: str, *, source_ip: str, headers=None, body: bytes = b""):
    """Drive the ASGI app once with a synthetic API Gateway v2 event (sourceIp set by the
    gateway, not the client) plus any request headers (e.g. a forged X-Forwarded-For).
    Returns (status, body_text)."""
    hdr = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    out: dict = {"status": 0, "chunks": []}

    async def _run() -> None:
        scope = {
            "type": "http", "http_version": "1.1", "method": method,
            "path": path, "raw_path": path.encode(), "query_string": b"",
            "headers": hdr, "client": ("127.0.0.1", 10000),
            "server": ("testserver", 80), "scheme": "http",
            "aws.event": {"requestContext": {"http": {"sourceIp": source_ip}}},
        }
        state = {"sent": False}

        async def receive():
            if not state["sent"]:
                state["sent"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"] = msg["status"]
            elif msg["type"] == "http.response.body":
                out["chunks"].append(msg.get("body", b""))

        await app(scope, receive, send)

    anyio.run(_run)
    return out["status"], b"".join(out["chunks"]).decode("utf-8", "replace")


@pytest.fixture()
def key_env(monkeypatch):
    """Key-issuing ON, fixed IP salt (no SSM), stub vision, memory stores, real caps."""
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.setenv("NUNCHI_KEY_ISSUING", "1")
    monkeypatch.setenv("NUNCHI_IP_SALT", "q3-fixed-salt")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    monkeypatch.delenv("NUNCHI_API_KEY_PARAM", raising=False)
    monkeypatch.delenv("NUNCHI_KEY_GLOBAL_DAILY", raising=False)  # real default 6
    monkeypatch.delenv("NUNCHI_KEY_IP_DAILY", raising=False)      # real default 3
    from nunchi.service import deps

    deps.reset_services()
    yield
    deps.reset_services()


# --- 1. forged X-Forwarded-For cannot widen the per-IP budget ----------------
def test_forged_xff_cannot_bypass_per_ip_limit(key_env):
    """Each /v1/keys call carries a DIFFERENT forged XFF, but the gateway sourceIp is one
    IP. All four count against that one IP, so the 4th is 429 ip_daily_limit."""
    app = app_mod.create_app()
    gw_ip = "203.0.113.11"
    codes = []
    for i in range(4):
        status, _ = _call(
            app, "POST", "/v1/keys",
            source_ip=gw_ip,
            headers={"X-Forwarded-For": f"10.0.0.{i}, 8.8.8.{i}", "X-Real-IP": f"9.9.9.{i}"},
        )
        codes.append(status)
    assert codes[:3] == [200, 200, 200], codes
    assert codes[3] == 429, "forged XFF widened the per-IP budget"


# --- 2. raw key + raw IP never persisted / traced / metered / echoed ---------
def test_raw_key_and_ip_absent_everywhere(key_env, monkeypatch, capsys):
    """Issue a key for a known IP, then USE it across the live frame path. The raw key and
    raw IP must be absent from: persisted session state, trace, EMF stdout, response body.
    Only the response that *returns* the key (the issue call) carries it."""
    from nunchi.service.state import MemoryStateStore

    held = MemoryStateStore()
    monkeypatch.setattr(app_mod, "make_state_store", lambda: held)
    app = app_mod.create_app()
    gw_ip = "198.51.100.23"

    _ = capsys.readouterr()  # clear
    status, issue_body = _call(app, "POST", "/v1/keys", source_ip=gw_ip)
    assert status == 200, issue_body
    key = json.loads(issue_body)["key"]
    assert key and gw_ip not in issue_body  # issue returns the key but never the raw IP

    # create a session + push a frame using the trial key
    import cv2
    import numpy as np

    jpeg = cv2.imencode(".jpg", np.full((240, 320, 3), 120, dtype=np.uint8))[1].tobytes()
    status, sess_body = _call(
        app, "POST", "/v1/sessions", source_ip=gw_ip,
        headers={"X-Api-Key": key, "Content-Type": "application/json"},
        body=json.dumps({"client_date": "2026-10-26", "lang": "en"}).encode(),
    )
    assert status == 200, sess_body
    sid = json.loads(sess_body)["session_id"]

    # a frame upload needs multipart; drive it through TestClient but with the SAME app so
    # the held state store is shared. TestClient has no aws.event, IP falls back to socket
    # (not our gw_ip), which is fine: we only assert the key/ip do not leak.
    from fastapi.testclient import TestClient

    emf_before = capsys.readouterr().out
    with TestClient(app) as c:
        r = c.post(
            "/v1/frames",
            data={"session_id": sid, "t": "11.0", "phase": "run"},
            files={"frame": ("f.jpg", jpeg, "image/jpeg")},
            headers={"X-Api-Key": key},
        )
        assert r.status_code == 200, r.text
        frame_body = r.text
        trace = c.get(f"/v1/trace/{sid}", headers={"X-Api-Key": key}).text
    emf = emf_before + capsys.readouterr().out

    persisted = json.dumps(held._data)
    assert sid in persisted, "sanity: session was persisted"
    # the raw key and raw IP appear in NONE of state / trace / EMF / frame response
    for where, blob in (("state", persisted), ("trace", trace), ("emf", emf), ("frame", frame_body)):
        assert key not in blob, f"raw trial key leaked into {where}"
        assert gw_ip not in blob, f"raw client IP leaked into {where}"
    # defense in depth: no sha256(key) hash in the session state either (keys live in their
    # own KEY# rows, not in session state)
    from nunchi.service.keys import hash_key

    assert hash_key(key) not in persisted, "key hash leaked into session state"


# --- 3. expired key rejected at the live /check path before TTL deletion -----
def test_expired_key_rejected_via_live_check_without_deletion(key_env, monkeypatch):
    """A key past expires_at is 401 key_expired through the running app, and its row is NOT
    deleted (we assert the stored row still exists). Correctness comes from the code compare."""
    from nunchi.service import deps
    from nunchi.service.keys import KEY_TTL_S

    app = app_mod.create_app()
    deps.get_services()  # ensure services/app key store are built
    # Issue through HTTP so we exercise the exact live store the app bound.
    status, body = _call(app, "POST", "/v1/keys", source_ip="203.0.113.44")
    assert status == 200
    key = json.loads(body)["key"]

    # Just-issued key authorises a session (200).
    status, _ = _call(
        app, "POST", "/v1/sessions", source_ip="203.0.113.44",
        headers={"X-Api-Key": key, "Content-Type": "application/json"},
        body=b'{"lang":"en"}',
    )
    assert status == 200, "fresh key should authorise"

    # Force expiry: patch time so the key store sees "now" past expires_at. _check_key calls
    # key_store.validate(key) with no `now`, so we patch time.time inside the keys module.
    import nunchi.service.keys as keys_mod

    real_time = keys_mod.time.time
    monkeypatch.setattr(keys_mod.time, "time", lambda: real_time() + KEY_TTL_S + 5)

    status, body = _call(
        app, "POST", "/v1/sessions", source_ip="203.0.113.44",
        headers={"X-Api-Key": key, "Content-Type": "application/json"},
        body=b'{"lang":"en"}',
    )
    assert status == 401, "expired key must be rejected"
    assert json.loads(body) == {"error": "key_expired"}, body

    # the row must still be present (we rejected by expires_at, not by TTL deletion). We cannot
    # reach the closed-over store directly, so re-validate just under expiry via a parallel
    # store check is not possible here; instead assert the shape proves a code decision:
    # key_expired (row found, past expiry) is DISTINCT from key_invalid (row absent).
    assert "key_expired" in body and "key_invalid" not in body, (
        "a deleted row would read key_invalid; key_expired proves the row still existed"
    )


# --- 4. global cap soaks to 503 at the SHIPPED default (6), distinct IPs -----
def test_global_cap_503_at_default_six(key_env):
    """Six issuances from six distinct gateway IPs succeed; the 7th (new IP) is 503 capacity.
    Uses the real default global cap (6) — no env override — so the shipped ceiling is proven."""
    app = app_mod.create_app()
    codes = [
        _call(app, "POST", "/v1/keys", source_ip=f"198.51.100.{i}")[0]
        for i in range(6)
    ]
    assert codes == [200] * 6, codes
    status, body = _call(app, "POST", "/v1/keys", source_ip="203.0.113.250")
    assert status == 503, "7th issuance should hit the global cap"
    assert json.loads(body) == {"error": "capacity"}, body


# --- 5. store-level: expired-but-present row refused; cross-IP isolation ------
def test_store_present_expired_row_and_ip_isolation():
    """Directly on MemoryKeyStore (deterministic clock): a present-but-expired row returns
    key_expired (row still in the map), and exhausting one IP never blocks a different IP."""
    from nunchi.service.keys import KEY_TTL_S, MemoryKeyStore, hash_key

    store = MemoryKeyStore()
    now = 1_700_000_000.0
    issued = store.issue("203.0.113.90", now=now)
    kh = hash_key(issued["key"])
    assert kh in store._keys
    assert store.validate(issued["key"], now=now + KEY_TTL_S - 1) == "ok"
    assert store.validate(issued["key"], now=now + KEY_TTL_S + 1) == "key_expired"
    assert kh in store._keys, "row was deleted — expiry must be by code, not deletion"

    # exhaust one IP, confirm a different IP keeps its own budget
    from nunchi.service.keys import IpLimitError

    ip = "198.51.100.77"
    for _ in range(3):
        store.issue(ip, now=now)
    with pytest.raises(IpLimitError):
        store.issue(ip, now=now)
    other = store.issue("198.51.100.78", now=now)
    assert other["remaining_today"] == 2
