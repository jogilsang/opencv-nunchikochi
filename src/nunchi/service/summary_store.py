"""Per-user daily summary store (CONTRACTS §4). OWNER: cloud tab.

Stores the numbers-only session summary (counts, accumulated seconds, the A11
`timeline`/`per_hour_rate`, and the agent's own tallies) so the web app can draw a
multi-session trend WITHOUT any login. "Same user" is linked only by an opaque,
browser-held anonymous token; the service never stores the raw token — the DynamoDB
partition key is a SHA-256 hash of it (CONTRACTS §4, C14 brief §1).

Keys:    pk = USER#<hash32>          (hash32 = sha256(token).hexdigest()[:32])
         sk = DAY#<date>#<sid>      (date = client_date, sid = session id; unique per session)
TTL:     30 days (CONTRACTS §4).

Privacy invariant (enforced here, not just upstream): every value written goes through
`sanitize_summary`, a strict numeric/whitelist filter. Images, landmarks, raw coordinates
and any non-whitelisted key are dropped before the item is built, so a bug upstream can
never push pixel data into this table. The matching test proves no
`jpeg|image|base64|landmark` key is ever stored.

Two adapters, same interface (mirrors state.py):
- MemorySummaryStore: local dev / tests.
- DynamoSummaryStore: same `nunchi-sessions` table, USER#/DAY# keys (no new table).
"""
from __future__ import annotations

import os
import time
from typing import Any, Protocol

# Daily aggregate TTL: 30 days (CONTRACTS §4).
SUMMARY_TTL_S = 30 * 24 * 60 * 60

# Keys allowed in a stored summary. Everything else is dropped. Deliberately excludes
# anything that could carry pixels/coordinates (no "overlay", "landmark", "image", ...).
_ALLOWED_TOP = {
    "session_id", "date", "duration_s", "counts", "seconds", "longest_s",
    "nudges_sent", "nudges_suppressed", "confirmations_asked", "recalibrations",
    "timeline",
}
# Forbidden substrings — a key containing any of these is never stored, at any depth.
_BANNED_SUBSTR = ("image", "jpeg", "base64", "landmark", "frame", "pixel", "overlay",
                  "coord", "point", "bytes", "data:")


def _key_ok(key: str) -> bool:
    k = key.lower()
    return not any(b in k for b in _BANNED_SUBSTR)


def _numbers_only(value: Any, _depth: int = 0) -> Any:
    """Recursively keep only JSON numbers/strings/bools/None and nested maps/lists of those.
    Map keys must pass `_key_ok`. Anything else is dropped (returns a sentinel caller skips)."""
    if _depth > 8:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        # short labels only (behaviour names / date / direction); never a blob
        return value[:64]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            ks = str(k)
            if not _key_ok(ks):
                continue
            cleaned = _numbers_only(v, _depth + 1)
            out[ks[:64]] = cleaned
        return out
    if isinstance(value, (list, tuple)):
        return [_numbers_only(v, _depth + 1) for v in list(value)[:500]]
    # bytes / ndarray / unknown types are dropped entirely
    return None


def sanitize_summary(summary_dict: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a serialized summary with ONLY the whitelisted, numbers-only keys.

    This is the hard privacy gate for the USER#/DAY# table: a non-whitelisted or
    image/landmark-looking key never reaches DynamoDB regardless of upstream bugs.
    """
    clean: dict[str, Any] = {}
    for k, v in (summary_dict or {}).items():
        if k not in _ALLOWED_TOP or not _key_ok(k):
            continue
        clean[k] = _numbers_only(v)
    return clean


class SummaryStore(Protocol):
    def put_day(self, user_hash: str, date: str, sid_suffix: str, summary: dict[str, Any]) -> None: ...

    def recent(self, user_hash: str, n: int = 5) -> list[dict[str, Any]]: ...


class MemorySummaryStore:
    """In-process daily-summary store for local dev and tests."""

    def __init__(self) -> None:
        # user_hash -> { sk -> {"summary":..., "ttl":...} }
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    @staticmethod
    def _sk(date: str, sid_suffix: str) -> str:
        return f"DAY#{date}#{sid_suffix}"

    def put_day(self, user_hash: str, date: str, sid_suffix: str, summary: dict[str, Any]) -> None:
        clean = sanitize_summary(summary)
        sk = self._sk(date, sid_suffix)
        self._data.setdefault(user_hash, {})[sk] = {
            "summary": clean,
            "ttl": time.time() + SUMMARY_TTL_S,
        }

    def recent(self, user_hash: str, n: int = 5) -> list[dict[str, Any]]:
        now = time.time()
        rows = self._data.get(user_hash, {})
        live = [(sk, v["summary"]) for sk, v in rows.items() if v.get("ttl", now + 1) >= now]
        # sort by sk (DAY#<date>#<sid>) so it is chronological, oldest first
        live.sort(key=lambda kv: kv[0])
        return [s for _sk, s in live][-n:]


class DynamoSummaryStore:
    """DynamoDB-backed daily-summary store. Same table as state (no new resource).

    pk=USER#<hash32>, sk=DAY#<date>#<sid>, native TTL attribute `ttl`. Only sanitized,
    numbers-only summaries are written (`sanitize_summary`). Floats round-trip via the
    same Decimal helpers as the state store.
    """

    def __init__(self, table_name: str | None = None, *, region: str = "us-east-1") -> None:
        import boto3  # lazy: local/memory mode needs no AWS deps at import time

        self._table_name = table_name or os.environ.get("NUNCHI_TABLE", "nunchi-sessions")
        self._table = boto3.resource("dynamodb", region_name=region).Table(self._table_name)

    @staticmethod
    def _sk(date: str, sid_suffix: str) -> str:
        return f"DAY#{date}#{sid_suffix}"

    def put_day(self, user_hash: str, date: str, sid_suffix: str, summary: dict[str, Any]) -> None:
        from .state import _floats_to_decimal

        clean = sanitize_summary(summary)
        item = {
            "pk": f"USER#{user_hash}",
            "sk": self._sk(date, sid_suffix),
            "summary": _floats_to_decimal(clean),
            "ttl": int(time.time() + SUMMARY_TTL_S),
        }
        self._table.put_item(Item=item)

    def recent(self, user_hash: str, n: int = 5) -> list[dict[str, Any]]:
        from boto3.dynamodb.conditions import Key

        from .state import _decimals_to_native

        now = time.time()
        resp = self._table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{user_hash}")
            & Key("sk").begins_with("DAY#"),
            ScanIndexForward=True,  # ascending sk => oldest first
            Limit=max(1, n) * 4,    # over-read a little to skip TTL-expired rows
        )
        rows = resp.get("Items", [])
        out: list[dict[str, Any]] = []
        for it in rows:
            ttl = it.get("ttl")
            if ttl is not None and float(ttl) < now:
                continue
            s = it.get("summary")
            if s is not None:
                out.append(_decimals_to_native(s))
        return out[-n:]


def make_summary_store() -> SummaryStore:
    """Pick adapter from env (same switch as state). dynamo|memory, default memory."""
    backend = os.environ.get("NUNCHI_STATE_BACKEND", "memory").lower()
    if backend == "dynamo":
        return DynamoSummaryStore()
    return MemorySummaryStore()
