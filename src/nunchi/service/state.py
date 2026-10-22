"""Session-state store. OWNER: cloud tab.

Lambda instances do not share memory, so calibration baseline, the behaviour
state machine and the agent context must live outside the process. We persist
only JSON-serialisable *state* here — never image bytes (privacy, docs/RULES.md).

Two adapters, same interface:
- MemoryStateStore: local dev / tests (single process).
- DynamoStateStore: pk=SESSION#<id> sk=STATE, TTL 24h (CONTRACTS §4).

Decision rationale is written in docs/ARCHITECTURE.md "세션 상태".
"""
from __future__ import annotations

import copy
import os
import time
from typing import Any, Protocol

# Session state TTL: 24h (CONTRACTS §4). Stale sessions self-expire.
SESSION_TTL_S = 24 * 60 * 60


class StateStore(Protocol):
    """Opaque per-session JSON state. The service owns the schema; callers treat it as a dict."""

    def get(self, session_id: str) -> dict[str, Any] | None: ...

    def put(self, session_id: str, state: dict[str, Any]) -> None: ...

    def delete(self, session_id: str) -> None: ...


class MemoryStateStore:
    """In-process store for local dev and tests. Honours TTL so expiry behaviour is testable."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._expiry: dict[str, float] = {}

    def _expired(self, session_id: str) -> bool:
        exp = self._expiry.get(session_id)
        return exp is not None and exp < time.time()

    def get(self, session_id: str) -> dict[str, Any] | None:
        if session_id not in self._data or self._expired(session_id):
            self._data.pop(session_id, None)
            self._expiry.pop(session_id, None)
            return None
        return copy.deepcopy(self._data[session_id])

    def put(self, session_id: str, state: dict[str, Any]) -> None:
        self._data[session_id] = copy.deepcopy(state)
        self._expiry[session_id] = time.time() + SESSION_TTL_S

    def delete(self, session_id: str) -> None:
        self._data.pop(session_id, None)
        self._expiry.pop(session_id, None)


class DynamoStateStore:
    """DynamoDB-backed store. pk=SESSION#<id>, sk=STATE, native TTL attribute `ttl`.

    Table name from env NUNCHI_TABLE (default nunchi-sessions). Region us-east-1 (RULES).
    Only aggregate/state JSON is stored — no image data.

    DynamoDB's document types reject Python float (TypeError: use Decimal). Session state
    carries floats (timestamps, metric values), so we round-trip floats<->Decimal on the
    boundary via JSON (surfaced on the real backend; moto/memory never hit this).
    """

    def __init__(self, table_name: str | None = None, *, region: str = "us-east-1") -> None:
        import boto3  # imported lazily so local/memory mode needs no AWS deps at import time

        self._table_name = table_name or os.environ.get("NUNCHI_TABLE", "nunchi-sessions")
        self._table = boto3.resource("dynamodb", region_name=region).Table(self._table_name)

    @staticmethod
    def _key(session_id: str) -> dict[str, str]:
        return {"pk": f"SESSION#{session_id}", "sk": "STATE"}

    def get(self, session_id: str) -> dict[str, Any] | None:
        resp = self._table.get_item(Key=self._key(session_id))
        item = resp.get("Item")
        if not item:
            return None
        ttl = item.get("ttl")
        if ttl is not None and float(ttl) < time.time():
            return None  # expired but not yet reaped by DynamoDB
        state = item.get("state")
        return _decimals_to_native(state) if state is not None else None

    def put(self, session_id: str, state: dict[str, Any]) -> None:
        item = {
            **self._key(session_id),
            "state": _floats_to_decimal(state),
            "ttl": int(time.time() + SESSION_TTL_S),
        }
        self._table.put_item(Item=item)

    def delete(self, session_id: str) -> None:
        self._table.delete_item(Key=self._key(session_id))


def _floats_to_decimal(value: Any) -> Any:
    """Recursively convert floats to Decimal for DynamoDB (via JSON for exact, cheap pass).
    DynamoDB document types accept Decimal, int, str, bool, None, list, map — not float."""
    import json
    from decimal import Decimal

    return json.loads(json.dumps(value), parse_float=Decimal)


def _decimals_to_native(value: Any) -> Any:
    """Recursively convert DynamoDB Decimals back to int/float for the service/JSON layer."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        i = int(value)
        return i if value == i else float(value)
    if isinstance(value, dict):
        return {k: _decimals_to_native(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimals_to_native(v) for v in value]
    return value


def make_state_store() -> StateStore:
    """Pick adapter from env. NUNCHI_STATE_BACKEND=memory|dynamo (default memory for safe local dev)."""
    backend = os.environ.get("NUNCHI_STATE_BACKEND", "memory").lower()
    if backend == "dynamo":
        return DynamoStateStore()
    return MemoryStateStore()
