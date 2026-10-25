"""Trial-key issuing + validation store (C17). OWNER: cloud tab.

The cloud demo lets a judge press "Get a trial key" (no key needed) to obtain a key that
is valid for 30 minutes. Abuse guards:
- per client IP: at most ISSUE_PER_IP_PER_DAY issuances per UTC date (default 3);
- global: at most ISSUE_GLOBAL_PER_DAY issuances per UTC date (default 6, env-tunable).

Privacy (docs/RULES.md, docs/cloud/ENDPOINT.md):
- The raw client IP is NEVER stored, logged, or traced. We store only a keyed HMAC-SHA256
  hash of it (secret from SSM SecureString `/nunchi/ip-salt`). The daily-count item is
  keyed by that hash + date.
- The issued key's plaintext is NEVER stored. We store only `KEY#<sha256(key)>` with the
  expiry. Validation compares `expires_at` in code (DynamoDB TTL deletion is best-effort
  and lags hours, so TTL is never trusted for correctness).

Reuses the single `nunchi-sessions` DynamoDB table (no new resource): item kinds
  KEY#<sha256(key)>          sk=KEY    -> issued key, expires_at
  IP#<hash>#<YYYY-MM-DD>      sk=COUNT  -> per-IP daily counter (conditional increment, < N)
  DAY#<YYYY-MM-DD>           sk=ISSUE  -> global daily counter (conditional increment, < N)
Counters use an atomic conditional ADD so a burst can never exceed the cap (no read race).

Two adapters, same interface (mirrors state.py / summary_store.py):
- MemoryKeyStore: local dev / tests (single process; models the atomic conditions).
- DynamoKeyStore: the shared table, lazy boto3.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import os
import secrets
import time
from typing import Any, Protocol

# Key lifetime: 30 minutes (C17). TTL on the stored item carries a cushion so DynamoDB does
# not reap a still-referenced row early; correctness always comes from the expires_at check.
KEY_TTL_S = 30 * 60
KEY_ITEM_TTL_CUSHION_S = 60 * 60  # keep the row ~1h past expiry for debuggability
# Per-IP daily counter row lives 48h (brief §1), well past the UTC day it counts.
IP_COUNT_TTL_S = 48 * 60 * 60
# Global daily counter row: keep a couple of days.
DAY_COUNT_TTL_S = 48 * 60 * 60


def _issue_per_ip_per_day() -> int:
    return int(os.environ.get("NUNCHI_KEY_IP_DAILY", "3"))


def _issue_global_per_day() -> int:
    # User decision 2026-10-25: global daily cap default 6 (was 200), still env-tunable.
    return int(os.environ.get("NUNCHI_KEY_GLOBAL_DAILY", "6"))


def utc_date(now: float | None = None) -> str:
    """UTC calendar date (YYYY-MM-DD) for the day a request falls in."""
    ts = time.time() if now is None else now
    return _dt.datetime.fromtimestamp(ts, tz=_dt.UTC).strftime("%Y-%m-%d")


def seconds_until_utc_midnight(now: float | None = None) -> int:
    """Seconds until the next UTC 00:00 (for the 429 retry_after_s)."""
    ts = time.time() if now is None else now
    dt = _dt.datetime.fromtimestamp(ts, tz=_dt.UTC)
    nxt = (dt + _dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(0, int(nxt.timestamp() - ts))


def _ip_salt() -> bytes:
    """HMAC salt for IP hashing. From SSM SecureString `/nunchi/ip-salt` (resolved once,
    cached) or env NUNCHI_IP_SALT (local/tests). Never logged. If neither is present the
    hash still works with a per-process random salt, but then per-IP counting is not stable
    across instances — deploy.sh provisions the SSM value so this does not happen in prod."""
    env = os.environ.get("NUNCHI_IP_SALT")
    if env:
        return env.encode("utf-8")
    param = os.environ.get("NUNCHI_IP_SALT_PARAM")
    if param:
        cached = _SALT_CACHE.get(param)
        if cached is not None:
            return cached
        value: bytes | None = None
        try:
            import boto3

            ssm = boto3.client("ssm")
            raw = ssm.get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
            value = raw.encode("utf-8") if raw else None
        except Exception:  # noqa: BLE001 - unreachable SSM: fall through to ephemeral salt
            value = None
        if value is None:
            value = _EPHEMERAL_SALT
        _SALT_CACHE[param] = value
        return value
    return _EPHEMERAL_SALT


_SALT_CACHE: dict[str, bytes] = {}
_EPHEMERAL_SALT = secrets.token_bytes(32)  # last-resort per-process salt (never for prod counting)


def hash_ip(ip: str) -> str:
    """Keyed HMAC-SHA256 of the client IP, hex[:32]. The raw IP never leaves this function."""
    return hmac.new(_ip_salt(), (ip or "").encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def hash_key(key: str) -> str:
    """sha256 of the issued key (so the plaintext key is never stored)."""
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()


def new_key() -> str:
    """A fresh opaque key: 32 bytes -> 64 hex chars (>= the 32+ hex the contract promises)."""
    return secrets.token_hex(32)


class IpLimitError(Exception):
    """Per-IP daily issuance cap reached."""


class GlobalLimitError(Exception):
    """Global daily issuance cap reached."""


class KeyStore(Protocol):
    def issue(self, ip: str, now: float | None = None) -> dict[str, Any]: ...

    def validate(self, key: str, now: float | None = None) -> str: ...


class MemoryKeyStore:
    """In-process trial-key store for local dev and tests.

    Models the same atomicity as DynamoDB conditional increments: counts never exceed the
    cap even under a burst (single-threaded here, but the check-then-set is the same shape).
    """

    def __init__(self) -> None:
        self._keys: dict[str, dict[str, Any]] = {}   # sha256(key) -> {expires_at, ttl}
        self._ip: dict[str, int] = {}                # "IP#<hash>#<date>" -> count
        self._day: dict[str, int] = {}               # "DAY#<date>" -> count

    def issue(self, ip: str, now: float | None = None) -> dict[str, Any]:
        ts = time.time() if now is None else now
        date = utc_date(ts)
        ip_key = f"IP#{hash_ip(ip)}#{date}"
        day_key = f"DAY#{date}"
        ip_cap = _issue_per_ip_per_day()
        global_cap = _issue_global_per_day()

        # Per-IP first (hard limit): a per-IP rejection must not consume a global slot.
        if self._ip.get(ip_key, 0) >= ip_cap:
            raise IpLimitError()
        # Global ceiling next. If the day is exhausted, do not take the per-IP slot.
        if self._day.get(day_key, 0) >= global_cap:
            raise GlobalLimitError()

        # Both checks passed: take the slots (atomic-style; counts can never exceed caps).
        self._ip[ip_key] = self._ip.get(ip_key, 0) + 1
        self._day[day_key] = self._day.get(day_key, 0) + 1

        key = new_key()
        expires_at = ts + KEY_TTL_S
        self._keys[hash_key(key)] = {
            "expires_at": expires_at,
            "ttl": expires_at + KEY_ITEM_TTL_CUSHION_S,
        }
        remaining = max(0, ip_cap - self._ip[ip_key])
        return {
            "key": key,
            "expires_at": _iso_utc(expires_at),
            "ttl_s": KEY_TTL_S,
            "remaining_today": remaining,
        }

    def validate(self, key: str, now: float | None = None) -> str:
        """Return "ok" | "key_expired" | "key_invalid". Correctness from expires_at, not TTL."""
        ts = time.time() if now is None else now
        row = self._keys.get(hash_key(key))
        if row is None:
            return "key_invalid"
        if float(row.get("expires_at", 0)) <= ts:
            return "key_expired"
        return "ok"


class DynamoKeyStore:
    """DynamoDB-backed trial-key store on the shared `nunchi-sessions` table (no new table).

    Items:
      pk=KEY#<sha256(key)>       sk=KEY    attrs: expires_at (N), ttl (N)
      pk=IP#<hash>#<date>        sk=COUNT  attrs: n (N, conditional ADD < cap), ttl (N)
      pk=DAY#<date>              sk=ISSUE  attrs: n (N, conditional ADD < cap), ttl (N)

    The counters use UpdateItem `ADD n :one` with a `ConditionExpression attribute_not_exists(n)
    OR n < :cap`, so a concurrent burst can never push the count past the cap (atomic, no read
    race). A ConditionalCheckFailedException maps to the cap error.
    """

    def __init__(self, table_name: str | None = None, *, region: str = "us-east-1") -> None:
        import boto3  # lazy: local/memory mode needs no AWS deps at import time

        self._table_name = table_name or os.environ.get("NUNCHI_TABLE", "nunchi-sessions")
        self._table = boto3.resource("dynamodb", region_name=region).Table(self._table_name)

    def _bump(self, pk: str, sk: str, cap: int, ttl: int) -> None:
        """Atomic conditional increment; raise if it would exceed `cap`."""
        from botocore.exceptions import ClientError

        try:
            self._table.update_item(
                Key={"pk": pk, "sk": sk},
                UpdateExpression="SET #ttl = :ttl ADD #n :one",
                ConditionExpression="attribute_not_exists(#n) OR #n < :cap",
                ExpressionAttributeNames={"#n": "n", "#ttl": "ttl"},
                ExpressionAttributeValues={":one": 1, ":cap": cap, ":ttl": ttl},
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise _CapReached() from exc
            raise

    def _refund(self, pk: str, sk: str) -> None:
        """Best-effort decrement of a counter (used to roll back a per-IP increment when the
        global cap then rejects the issuance). Never raises into the request path."""
        try:
            self._table.update_item(
                Key={"pk": pk, "sk": sk},
                UpdateExpression="ADD #n :neg",
                ConditionExpression="attribute_exists(#n) AND #n > :zero",
                ExpressionAttributeNames={"#n": "n"},
                ExpressionAttributeValues={":neg": -1, ":zero": 0},
            )
        except Exception:  # noqa: BLE001, S110 - refund is best-effort; a drift of 1 is acceptable
            pass

    def issue(self, ip: str, now: float | None = None) -> dict[str, Any]:
        ts = time.time() if now is None else now
        date = utc_date(ts)
        ip_cap = _issue_per_ip_per_day()
        global_cap = _issue_global_per_day()
        ip_pk = f"IP#{hash_ip(ip)}#{date}"

        # Per-IP first (the hard, common limit): a per-IP rejection must NOT consume a
        # global slot. Only after the per-IP slot is secured do we take a global slot.
        try:
            self._bump(ip_pk, "COUNT", ip_cap, int(ts + IP_COUNT_TTL_S))
        except _CapReached as exc:
            raise IpLimitError() from exc
        # Global ceiling next. If the day is exhausted, give the per-IP slot back so a
        # blocked-by-global request does not permanently burn this IP's allowance.
        try:
            self._bump(f"DAY#{date}", "ISSUE", global_cap, int(ts + DAY_COUNT_TTL_S))
        except _CapReached as exc:
            self._refund(ip_pk, "COUNT")  # best-effort rollback of the per-IP increment
            raise GlobalLimitError() from exc

        key = new_key()
        expires_at = ts + KEY_TTL_S
        self._table.put_item(
            Item={
                "pk": f"KEY#{hash_key(key)}",
                "sk": "KEY",
                "expires_at": int(expires_at),
                "ttl": int(expires_at + KEY_ITEM_TTL_CUSHION_S),
            }
        )
        # remaining_today reads the per-IP counter back (best-effort; defaults conservatively).
        remaining = max(0, ip_cap - self._read_ip_count(ip, date))
        return {
            "key": key,
            "expires_at": _iso_utc(expires_at),
            "ttl_s": KEY_TTL_S,
            "remaining_today": remaining,
        }

    def _read_ip_count(self, ip: str, date: str) -> int:
        try:
            resp = self._table.get_item(Key={"pk": f"IP#{hash_ip(ip)}#{date}", "sk": "COUNT"})
            item = resp.get("Item") or {}
            return int(item.get("n", _issue_per_ip_per_day()))  # conservative if missing
        except Exception:  # noqa: BLE001 - a read failure must not break issuance
            return _issue_per_ip_per_day()

    def validate(self, key: str, now: float | None = None) -> str:
        ts = time.time() if now is None else now
        try:
            resp = self._table.get_item(Key={"pk": f"KEY#{hash_key(key)}", "sk": "KEY"})
        except Exception:  # noqa: BLE001 - a store read failure => treat as invalid (fail closed)
            return "key_invalid"
        item = resp.get("Item")
        if not item:
            return "key_invalid"
        # expires_at is the source of truth (TTL deletion lags; never trust it for correctness).
        if float(item.get("expires_at", 0)) <= ts:
            return "key_expired"
        return "ok"


class _CapReached(Exception):
    """Internal: a conditional counter increment hit its cap."""


def _iso_utc(ts: float) -> str:
    return (
        _dt.datetime.fromtimestamp(ts, tz=_dt.UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def make_key_store() -> KeyStore:
    """Pick adapter from env (same switch as state/summary). dynamo|memory, default memory."""
    backend = os.environ.get("NUNCHI_STATE_BACKEND", "memory").lower()
    if backend == "dynamo":
        return DynamoKeyStore()
    return MemoryKeyStore()


def key_issuing_enabled() -> bool:
    """Whether this deployment issues trial keys. Off by default (local service => false);
    the cloud deploy sets NUNCHI_KEY_ISSUING=1. Surfaced at /healthz so the web hides the
    button when off."""
    return os.environ.get("NUNCHI_KEY_ISSUING", "0") == "1"
