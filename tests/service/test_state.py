"""Session-state store tests (CONTRACTS §4). OWNER: cloud tab.

MemoryStateStore for local dev; DynamoStateStore mocked with moto so no AWS calls.
Covers put/get/delete, TTL expiry, and that only JSON state (no image) is stored.
"""
from __future__ import annotations

import time

import pytest


# --- memory adapter: happy path --------------------------------------------
def test_memory_put_get_delete():
    from nunchi.service.state import MemoryStateStore

    s = MemoryStateStore()
    assert s.get("a") is None
    s.put("a", {"vision": {"frames_seen": 1}, "counts": {}})
    got = s.get("a")
    assert got["vision"]["frames_seen"] == 1
    # returns a copy: mutating the result must not change the store
    got["vision"]["frames_seen"] = 99
    assert s.get("a")["vision"]["frames_seen"] == 1
    s.delete("a")
    assert s.get("a") is None


# --- memory adapter: TTL expiry (edge) -------------------------------------
def test_memory_ttl_expiry(monkeypatch):
    from nunchi.service import state as state_mod
    from nunchi.service.state import MemoryStateStore

    s = MemoryStateStore()
    s.put("a", {"x": 1})
    # fast-forward past TTL (capture real now once to avoid recursive time.time)
    future = time.time() + state_mod.SESSION_TTL_S + 1
    monkeypatch.setattr(state_mod.time, "time", lambda: future)
    assert s.get("a") is None


# --- factory selects adapter from env (edge) -------------------------------
def test_make_state_store_default_memory(monkeypatch):
    monkeypatch.delenv("NUNCHI_STATE_BACKEND", raising=False)
    from nunchi.service.state import MemoryStateStore, make_state_store

    assert isinstance(make_state_store(), MemoryStateStore)


# --- dynamo adapter via moto: happy path -----------------------------------
def test_dynamo_roundtrip_moto(monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with moto.mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="nunchi-sessions",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        from nunchi.service.state import DynamoStateStore

        store = DynamoStateStore(table_name="nunchi-sessions")
        assert store.get("sid1") is None
        store.put("sid1", {"vision": {"frames_seen": 2}, "lang": "ko"})
        got = store.get("sid1")
        assert got["vision"]["frames_seen"] == 2 and got["lang"] == "ko"

        # stored item has a ttl attribute and no image fields
        raw = ddb.Table("nunchi-sessions").get_item(
            Key={"pk": "SESSION#sid1", "sk": "STATE"}
        )["Item"]
        assert "ttl" in raw and int(raw["ttl"]) > int(time.time())
        assert not any(k in json_lower(raw) for k in ("image", "jpeg", "frame_bytes", "pixels"))

        store.delete("sid1")
        assert store.get("sid1") is None


# --- dynamo adapter: expired item treated as missing (error/edge) ----------
def test_dynamo_expired_item_missing(monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with moto.mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="nunchi-sessions",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        # write an already-expired item directly
        ddb.Table("nunchi-sessions").put_item(
            Item={"pk": "SESSION#old", "sk": "STATE", "state": {"x": 1}, "ttl": int(time.time()) - 10}
        )
        from nunchi.service.state import DynamoStateStore

        store = DynamoStateStore(table_name="nunchi-sessions")
        assert store.get("old") is None  # expired-but-not-reaped is treated as gone


def json_lower(obj) -> str:
    import json

    return json.dumps(obj, default=str).lower()


# --- dynamo adapter: float state round-trips (regression for the deploy bug) ----
def test_dynamo_float_state_roundtrip_moto(monkeypatch):
    """DynamoDB rejects Python float ('use Decimal'). The real session state carries
    floats (timestamps, metric values); the store must convert float<->Decimal so a
    face frame does not 500. This reproduces the first-deploy failure."""
    moto = pytest.importorskip("moto")
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with moto.mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="nunchi-sessions",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        from nunchi.service.state import DynamoStateStore

        store = DynamoStateStore(table_name="nunchi-sessions")
        state = {
            "started": 1792000000.5,                       # float timestamp
            "vision": {"baseline": {"roll": -5.02, "ear": 0.1425}},  # float metrics
            "counts": {"head_tilt": 2},                     # int preserved
            "seconds": {"head_tilt": 1.5},                  # nested float
            "nudges_sent": 1,
        }
        store.put("floaty", state)                          # must NOT raise
        got = store.get("floaty")
        assert got["started"] == 1792000000.5
        assert got["vision"]["baseline"]["roll"] == -5.02
        assert got["counts"]["head_tilt"] == 2 and isinstance(got["counts"]["head_tilt"], int)
        assert got["seconds"]["head_tilt"] == 1.5

