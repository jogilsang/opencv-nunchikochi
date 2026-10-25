"""C17 — 30-minute trial-key issuing + validation. OWNER: cloud tab.

Covers (>= normal 2, exception 2, error 1):
- normal: issue -> use a /v1/* route with the issued key (200); /healthz reports key_issuing.
- normal: different IPs are isolated (each gets its own 3/day budget).
- exception: 4th issuance from the same IP -> 429 ip_daily_limit (flat shape + retry_after_s).
- exception: expired key -> 401 key_expired (expiry checked in code, NOT via TTL deletion);
  a key present but past expires_at is rejected even though the row still exists.
- error: global daily cap -> 503 capacity; and a store failure on issue -> 503 while the
  MASTER key path keeps working.
Plus privacy: no raw IP / raw key is stored or returned to the caller.

Store logic is tested directly (deterministic `now=`), and the HTTP contract is tested via
TestClient. The source-IP extractor is tested against a synthetic API Gateway v2 event
(X-Forwarded-For is deliberately ignored).
"""
from __future__ import annotations

import json

import pytest

from nunchi.service.keys import (
    GlobalLimitError,
    IpLimitError,
    MemoryKeyStore,
    hash_ip,
    hash_key,
    seconds_until_utc_midnight,
    utc_date,
)

# ---------------------------------------------------------------------------
# Store-level logic (deterministic clock)
# ---------------------------------------------------------------------------


def test_issue_then_validate_ok():
    """normal: a freshly issued key validates OK and reports the contract fields."""
    store = MemoryKeyStore()
    now = 1_700_000_000.0
    issued = store.issue("203.0.113.7", now=now)
    assert set(issued) == {"key", "expires_at", "ttl_s", "remaining_today"}
    assert issued["ttl_s"] == 1800
    assert len(issued["key"]) >= 32 and all(c in "0123456789abcdef" for c in issued["key"])
    assert issued["remaining_today"] == 2  # 3/day, one used
    assert issued["expires_at"].endswith("Z")
    assert store.validate(issued["key"], now=now) == "ok"
    assert store.validate(issued["key"], now=now + 60) == "ok"


def test_fourth_issue_from_same_ip_blocked():
    """exception: the 4th issuance from one IP in a UTC day is refused (per-IP cap 3)."""
    store = MemoryKeyStore()
    now = 1_700_000_000.0
    ip = "198.51.100.9"
    r = [store.issue(ip, now=now) for _ in range(3)]
    assert [x["remaining_today"] for x in r] == [2, 1, 0]
    with pytest.raises(IpLimitError):
        store.issue(ip, now=now)


def test_different_ips_isolated():
    """normal: a different IP has its own budget (one IP exhausting does not block another)."""
    store = MemoryKeyStore()
    now = 1_700_000_000.0
    for _ in range(3):
        store.issue("198.51.100.1", now=now)
    with pytest.raises(IpLimitError):
        store.issue("198.51.100.1", now=now)
    # A different IP still issues fine.
    other = store.issue("198.51.100.2", now=now)
    assert other["remaining_today"] == 2


def test_expired_key_rejected_even_before_ttl_deletion():
    """exception: a key past its 30-min expiry is 'key_expired' even though the row persists
    (the item TTL carries a cushion; correctness comes from the expires_at check, not TTL)."""
    store = MemoryKeyStore()
    now = 1_700_000_000.0
    issued = store.issue("203.0.113.1", now=now)
    kh = hash_key(issued["key"])
    assert kh in store._keys  # row still present (not yet reaped)
    # just before expiry: ok; just after: expired (row unchanged)
    assert store.validate(issued["key"], now=now + 1800 - 1) == "ok"
    assert store.validate(issued["key"], now=now + 1800 + 1) == "key_expired"
    assert kh in store._keys  # still present => we rejected by expires_at, not by deletion
    # expiry is 30 min after issue
    assert float(store._keys[kh]["expires_at"]) == pytest.approx(now + 1800)


def test_global_daily_cap_blocks_with_capacity():
    """error: once the global daily cap (default 6) is hit, further issues raise
    GlobalLimitError (maps to 503 capacity) even from brand-new IPs."""
    store = MemoryKeyStore()
    now = 1_700_000_000.0
    # six distinct IPs each issue once -> global count 6
    for i in range(6):
        store.issue(f"198.51.100.{i}", now=now)
    with pytest.raises(GlobalLimitError):
        store.issue("203.0.113.254", now=now)  # new IP, but the day is exhausted


def test_unknown_key_is_invalid():
    """error: a key never issued validates as key_invalid (not expired)."""
    store = MemoryKeyStore()
    assert store.validate("deadbeef" * 8) == "key_invalid"


def test_no_raw_ip_or_key_in_store():
    """privacy: neither the raw IP nor the raw key appears in the store's data; only hashes."""
    store = MemoryKeyStore()
    now = 1_700_000_000.0
    ip = "203.0.113.77"
    issued = store.issue(ip, now=now)
    blob = json.dumps({"keys": store._keys, "ip": store._ip, "day": store._day})
    assert ip not in blob               # raw IP never stored
    assert issued["key"] not in blob    # raw key never stored
    assert hash_ip(ip) in blob          # only the keyed hash
    assert hash_key(issued["key"]) in blob


def test_time_helpers():
    """normal: UTC date + retry-after helpers are sane at a known instant."""
    # 2023-11-14T22:13:20Z
    now = 1_700_000_000.0
    assert utc_date(now) == "2023-11-14"
    s = seconds_until_utc_midnight(now)
    assert 0 < s <= 24 * 3600


# ---------------------------------------------------------------------------
# HTTP contract (TestClient) with key-issuing enabled
# ---------------------------------------------------------------------------


@pytest.fixture()
def key_client(monkeypatch):
    """Client with key-issuing ON and a fixed IP salt (so tests do not touch SSM)."""
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.setenv("NUNCHI_KEY_ISSUING", "1")
    monkeypatch.setenv("NUNCHI_IP_SALT", "test-salt-fixed")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    monkeypatch.delenv("NUNCHI_API_KEY_PARAM", raising=False)
    monkeypatch.delenv("NUNCHI_KEY_GLOBAL_DAILY", raising=False)
    monkeypatch.delenv("NUNCHI_KEY_IP_DAILY", raising=False)
    from nunchi.service import deps

    deps.reset_services()
    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app

    with TestClient(create_app()) as c:
        yield c
    deps.reset_services()


def test_healthz_reports_key_issuing(key_client):
    assert key_client.get("/healthz").json()["key_issuing"] is True


def test_healthz_key_issuing_false_by_default(client):
    # the shared `client` fixture does not set NUNCHI_KEY_ISSUING
    assert client.get("/healthz").json()["key_issuing"] is False


def test_issue_key_http_and_use_it(key_client):
    """normal HTTP: POST /v1/keys (no key) -> 200 contract shape; the key then authorises
    a protected route."""
    r = key_client.post("/v1/keys")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"key", "expires_at", "ttl_s", "remaining_today"}
    assert body["ttl_s"] == 1800 and body["remaining_today"] == 2
    # the issued trial key authorises /v1/sessions (master key is not configured here)
    s = key_client.post(
        "/v1/sessions",
        json={"client_date": "2026-10-26", "lang": "en"},
        headers={"X-Api-Key": body["key"]},
    )
    assert s.status_code == 200, s.text
    # a bogus key is rejected flat
    bad = key_client.post(
        "/v1/sessions", json={"lang": "en"}, headers={"X-Api-Key": "nope" * 8}
    )
    assert bad.status_code == 401 and bad.json() == {"error": "key_invalid"}


def test_ip_daily_limit_http_429(key_client):
    """exception HTTP: TestClient always comes from one socket IP, so the 4th call is 429
    with the flat ip_daily_limit shape + retry_after_s + limit."""
    for _ in range(3):
        assert key_client.post("/v1/keys").status_code == 200
    over = key_client.post("/v1/keys")
    assert over.status_code == 429
    body = over.json()
    assert body["error"] == "ip_daily_limit"
    assert body["limit"] == 3
    assert isinstance(body["retry_after_s"], int) and body["retry_after_s"] > 0


def test_global_cap_http_503(monkeypatch):
    """error HTTP: with the global cap lowered to 2 (still > per-request), the 3rd issue from
    DIFFERENT ips is 503 capacity. We vary the IP via a synthetic API Gateway event."""
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.setenv("NUNCHI_KEY_ISSUING", "1")
    monkeypatch.setenv("NUNCHI_IP_SALT", "salt")
    monkeypatch.setenv("NUNCHI_KEY_GLOBAL_DAILY", "2")
    monkeypatch.setenv("NUNCHI_KEY_IP_DAILY", "3")
    from nunchi.service import deps

    deps.reset_services()
    from nunchi.service.app import create_app

    app = create_app()
    # drive the ASGI app directly with a per-call sourceIp (bypasses the single socket IP)
    codes = [_issue_with_ip(app, f"198.51.100.{i}") for i in range(3)]
    assert codes[:2] == [200, 200]
    assert codes[2] == 503  # global cap 2 reached; capacity
    deps.reset_services()


def test_issue_disabled_returns_404(client):
    """error: a deployment with key-issuing off (local service) 404s the route."""
    r = client.post("/v1/keys")
    assert r.status_code == 404 and r.json()["error"] == "key_issuing_disabled"


def test_master_key_still_works_with_issuing_on(monkeypatch):
    """the SSM master key (operations/local) stays valid even when trial issuing is on."""
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.setenv("NUNCHI_KEY_ISSUING", "1")
    monkeypatch.setenv("NUNCHI_IP_SALT", "salt")
    monkeypatch.setenv("NUNCHI_API_KEY", "master-secret")
    from nunchi.service import deps

    deps.reset_services()
    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app

    with TestClient(create_app()) as c:
        # master key authorises
        ok = c.post("/v1/sessions", json={"lang": "en"}, headers={"X-Api-Key": "master-secret"})
        assert ok.status_code == 200
        # no key -> 401 (unauthorized, the master-key shape, not a trial-key shape)
        no = c.post("/v1/sessions", json={"lang": "en"})
        assert no.status_code == 401
        # issuing still works alongside the master key
        assert c.post("/v1/keys").status_code == 200
    deps.reset_services()


def test_issue_store_failure_503_but_master_key_survives(monkeypatch):
    """error: if the key store raises on issue, /v1/keys returns 503 issue_failed, and a
    protected route still accepts the MASTER key (issuing failure must not break ops)."""
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.setenv("NUNCHI_KEY_ISSUING", "1")
    monkeypatch.setenv("NUNCHI_IP_SALT", "salt")
    monkeypatch.setenv("NUNCHI_API_KEY", "master-secret")
    from nunchi.service import deps

    deps.reset_services()
    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app
    from nunchi.service.keys import MemoryKeyStore

    def _boom(*_a, **_k):
        raise RuntimeError("ddb down")

    # Patch the store's issue so the app's live key_store raises; build app AFTER the patch.
    monkeypatch.setattr(MemoryKeyStore, "issue", _boom)
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/v1/keys")
        assert r.status_code == 503 and r.json()["error"] == "issue_failed"
        # master key path unaffected
        ok = c.post("/v1/sessions", json={"lang": "en"}, headers={"X-Api-Key": "master-secret"})
        assert ok.status_code == 200
    deps.reset_services()


# ---------------------------------------------------------------------------
# source-IP extraction: trust API Gateway, ignore X-Forwarded-For
# ---------------------------------------------------------------------------


def test_source_ip_from_apigw_event_ignores_xff():
    """The limiter keys on requestContext.http.sourceIp; a forged X-Forwarded-For header
    must not change the identity."""
    from starlette.requests import Request

    from nunchi.service.app import _source_ip

    scope = {
        "type": "http",
        "headers": [(b"x-forwarded-for", b"1.2.3.4")],
        "client": ("127.0.0.1", 55555),
        "aws.event": {"requestContext": {"http": {"sourceIp": "203.0.113.50"}}},
    }
    assert _source_ip(Request(scope)) == "203.0.113.50"  # gateway IP, not the XFF header

    # no AWS event (local dev): fall back to the socket peer, still not XFF
    scope2 = {"type": "http", "headers": [(b"x-forwarded-for", b"9.9.9.9")],
              "client": ("127.0.0.1", 40000)}
    assert _source_ip(Request(scope2)) == "127.0.0.1"


# ---------------------------------------------------------------------------
# helper: drive the ASGI app once with a chosen API Gateway sourceIp
# ---------------------------------------------------------------------------


def _issue_with_ip(app, ip: str) -> int:
    """POST /v1/keys through the raw ASGI app with a synthetic API Gateway v2 event so the
    per-call sourceIp varies (TestClient alone always uses one socket IP). Returns status."""
    import anyio

    status: dict[str, int] = {}

    async def _run() -> None:
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/v1/keys",
            "raw_path": b"/v1/keys",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 10000),
            "server": ("testserver", 80),
            "scheme": "http",
            "aws.event": {"requestContext": {"http": {"sourceIp": ip}}},
        }
        sent: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            sent.append(msg)

        await app(scope, receive, send)
        for m in sent:
            if m["type"] == "http.response.start":
                status["code"] = m["status"]

    anyio.run(_run)
    return status.get("code", 0)


# ---------------------------------------------------------------------------
# DynamoKeyStore via moto: atomic conditional increment really caps the count
# ---------------------------------------------------------------------------


def _make_table(boto3):
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName="nunchi-sessions",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                   {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                              {"AttributeName": "sk", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb


def test_dynamo_keystore_caps_are_atomic(monkeypatch):
    """The DynamoDB adapter enforces per-IP (3) and global (6) caps via a conditional ADD,
    stores no raw IP/key, and rejects expired keys by code (not TTL)."""
    moto = pytest.importorskip("moto")
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("NUNCHI_IP_SALT", "salt")
    monkeypatch.delenv("NUNCHI_KEY_IP_DAILY", raising=False)
    monkeypatch.delenv("NUNCHI_KEY_GLOBAL_DAILY", raising=False)

    with moto.mock_aws():
        ddb = _make_table(boto3)
        from nunchi.service.keys import (
            DynamoKeyStore,
            GlobalLimitError,
            IpLimitError,
            hash_ip,
            hash_key,
        )

        store = DynamoKeyStore(table_name="nunchi-sessions")
        now = 1_700_000_000.0
        ip = "203.0.113.5"

        issued = [store.issue(ip, now=now) for _ in range(3)]
        assert [x["remaining_today"] for x in issued] == [2, 1, 0]
        # 4th from same IP -> per-IP cap (the global count is only 3, so it IS the IP cap)
        with pytest.raises(IpLimitError):
            store.issue(ip, now=now)

        # issued keys validate ok now, expired later (by code; row still present)
        k0 = issued[0]["key"]
        assert store.validate(k0, now=now) == "ok"
        assert store.validate(k0, now=now + 1800 + 1) == "key_expired"
        raw = ddb.Table("nunchi-sessions").get_item(
            Key={"pk": f"KEY#{hash_key(k0)}", "sk": "KEY"}
        )["Item"]
        assert "expires_at" in raw  # still present => rejected by expires_at, not deletion

        # fill the global day to 6 using fresh IPs (3 already used), then capacity
        for i in range(3):
            store.issue(f"198.51.100.{i}", now=now)  # 3 more -> global 6
        with pytest.raises(GlobalLimitError):
            store.issue("198.51.100.200", now=now)

        # privacy: scan the whole table — no raw IP, no raw key anywhere
        items = ddb.Table("nunchi-sessions").scan()["Items"]
        blob = json.dumps(items, default=str)
        assert ip not in blob
        for x in issued:
            assert x["key"] not in blob
        assert hash_ip(ip) in blob  # only the hash is a key


def test_dynamo_keystore_read_failure_is_key_invalid(monkeypatch):
    """A store read failure during validate fails closed (key_invalid), never a 500."""
    moto = pytest.importorskip("moto")
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("NUNCHI_IP_SALT", "salt")

    with moto.mock_aws():
        _make_table(boto3)
        from nunchi.service.keys import DynamoKeyStore

        store = DynamoKeyStore(table_name="nunchi-sessions")

        def _boom(*_a, **_k):
            raise RuntimeError("ddb unavailable")

        monkeypatch.setattr(store._table, "get_item", _boom)
        assert store.validate("whatever" * 8) == "key_invalid"
