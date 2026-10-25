"""C14 — anonymous multi-session history + trend, and the USER#/DAY# summary store.

OWNER: cloud tab. Verifies the CONTRACTS §4 / C14 wiring:
- `/end` persists a numbers-only daily summary under the hashed anonymous id and the
  response carries `summary.timeline` + `report.trend`;
- `/v1/summary` returns `{summary, previous, history:[<=5 oldest-first]}` (back-compat);
- no / malformed anon id => "no-record mode" (nothing stored, no error);
- different anon ids are isolated;
- a store failure never fails `/end` (record is skipped);
- the stored item carries NO image/landmark key (whitelist proof).

Normal 2, exception 2, error 1 (+ privacy proof), per docs/RULES.md testing rules.
"""
from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from nunchi.service import deps
from nunchi.service.summary_store import (
    MemorySummaryStore,
    _key_ok,
    sanitize_summary,
)

# The package attr `nunchi.service.app` is the FastAPI instance (see __init__), so the
# module must be fetched explicitly (same pattern as the privacy verifier).
app_mod = importlib.import_module("nunchi.service.app")

ANON_A = "a1b2c3d4e5f60718"          # 16 hex — valid
ANON_B = "ffeeddccbbaa99887766554433221100"  # 32 hex — valid, different user
BAD_ID = "not-a-hex-token!!"         # malformed


def _build_client(monkeypatch, *, summary_store=None):
    """Fresh stub app. Optionally inject a summary store (to capture or to fail)."""
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    monkeypatch.delenv("NUNCHI_API_KEY_PARAM", raising=False)
    deps.reset_services()
    if summary_store is not None:
        monkeypatch.setattr(app_mod, "make_summary_store", lambda: summary_store)
    the_app = app_mod.create_app()
    return TestClient(the_app)


def _session_and_end(c, anon: str | None, date: str) -> dict:
    sid = c.post(
        "/v1/sessions", json={"client_date": date, "lang": "en"}
    ).json()["session_id"]
    headers = {"X-Anon-Id": anon} if anon is not None else {}
    r = c.post(f"/v1/sessions/{sid}/end", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# --- normal 1: two sessions stored -> history 2 + trend ---------------------
def test_two_sessions_build_history_and_trend(monkeypatch):
    store = MemorySummaryStore()
    c = _build_client(monkeypatch, summary_store=store)
    _session_and_end(c, ANON_A, "2026-10-26")
    _session_and_end(c, ANON_A, "2026-10-27")
    # store now holds two rows for this hashed user
    uh = app_mod._anon_hash(ANON_A)
    hist = store.recent(uh, 5)
    assert len(hist) == 2
    # /v1/summary returns them as history (oldest-first), back-compat keys present
    r = c.get("/v1/summary", params={"date": "2026-10-27"}, headers={"X-Anon-Id": ANON_A})
    body = r.json()
    assert r.status_code == 200
    assert set(("summary", "previous", "history")).issubset(body)
    assert len(body["history"]) == 2
    # end response shape carries the A11 fields
    end = _session_and_end(c, ANON_A, "2026-10-28")
    assert "timeline" in end["summary"]            # numbers-only timeline present
    assert "trend" in end["report"]                # trend attached to report


# --- normal 2: trend computes an improving direction from history rates -----
def test_trend_direction_from_history_rates(monkeypatch):
    # Seed the store directly with prior per-hour rates, then ask compare for a trend.
    store = MemorySummaryStore()
    uh = "deadbeefdeadbeefdeadbeefdeadbeef"
    for i, rate in enumerate((6.0, 5.0)):
        store.put_day(uh, f"2026-10-2{i}", f"sid{i:05d}",
                      {"session_id": f"s{i}", "date": f"2026-10-2{i}",
                       "timeline": {"per_hour_rate": rate, "bad_posture": {}}})
    history = store.recent(uh, 5)
    assert [h["timeline"]["per_hour_rate"] for h in history] == [6.0, 5.0]  # oldest-first
    # today rate 3.0 < mean(5.5) => improving
    from nunchi.contracts import SessionSummary

    trend = app_mod.compare(
        SessionSummary(session_id="t", date="2026-10-22"),
        None, history=history, today_rate=3.0,
    )["trend"]
    assert trend["direction"] == "improving"
    assert trend["n"] == 2 and trend["baseline_rate"] == 5.5


# --- exception 1: no / malformed anon id -> nothing stored (no-record mode) --
def test_no_or_malformed_anon_id_is_not_stored(monkeypatch):
    store = MemorySummaryStore()
    c = _build_client(monkeypatch, summary_store=store)
    # no header at all
    end1 = _session_and_end(c, None, "2026-10-26")
    assert end1["report"]["trend"]["direction"] == "na"
    # malformed token
    end2 = _session_and_end(c, BAD_ID, "2026-10-26")
    assert end2["report"]["trend"]["direction"] == "na"
    # store received nothing under any hash
    assert store._data == {}
    # summary endpoint returns empty history for a missing/invalid token
    r = c.get("/v1/summary", params={"date": "2026-10-26"}, headers={"X-Anon-Id": BAD_ID})
    assert r.json()["history"] == []
    assert app_mod._anon_hash(BAD_ID) is None
    assert app_mod._anon_hash(None) is None


# --- exception 2: different anon ids are isolated ---------------------------
def test_different_anon_ids_are_isolated(monkeypatch):
    store = MemorySummaryStore()
    c = _build_client(monkeypatch, summary_store=store)
    _session_and_end(c, ANON_A, "2026-10-26")
    _session_and_end(c, ANON_B, "2026-10-26")
    _session_and_end(c, ANON_B, "2026-10-27")
    assert len(store.recent(app_mod._anon_hash(ANON_A), 5)) == 1
    assert len(store.recent(app_mod._anon_hash(ANON_B), 5)) == 2
    # A's summary call never sees B's rows
    ra = c.get("/v1/summary", params={"date": "2026-10-26"}, headers={"X-Anon-Id": ANON_A})
    assert len(ra.json()["history"]) == 1
    # raw token hashing: the stored key is the hash, never the token itself
    assert ANON_A not in json.dumps(store._data)
    assert app_mod._anon_hash(ANON_A) != app_mod._anon_hash(ANON_B)


# --- error 1: a store failure must not fail /end ----------------------------
def test_store_failure_does_not_fail_end(monkeypatch):
    class _BoomStore(MemorySummaryStore):
        def put_day(self, *a, **k):
            raise RuntimeError("dynamo down / 다이나모 장애")

    c = _build_client(monkeypatch, summary_store=_BoomStore())
    sid = c.post(
        "/v1/sessions", json={"client_date": "2026-10-26", "lang": "en"}
    ).json()["session_id"]
    r = c.post(f"/v1/sessions/{sid}/end", headers={"X-Anon-Id": ANON_A})
    assert r.status_code == 200, "end must succeed even when the summary write fails"
    assert "summary" in r.json() and "report" in r.json()


# --- privacy: stored item is numbers-only, no image/landmark keys -----------
def test_stored_summary_has_no_image_or_landmark_keys():
    dirty = {
        "session_id": "s1", "date": "2026-10-26", "duration_s": 12.0,
        "counts": {"blink": 3}, "seconds": {"forward_head": 4.5},
        "timeline": {"per_hour_rate": 2.0, "bad_posture": {"5m": [{"start_s": 0, "events": 1, "seconds": 2.0}]}},
        # the following must all be stripped
        "overlay": {"pose": {"yaw_deg": 10.0}},
        "landmarks": [[0.1, 0.2]],
        "image": "/9j/4AAQSkZJRg==",
        "frame_jpeg_base64": "AAAA",
        "nudges_sent": 1,
    }
    clean = sanitize_summary(dirty)
    blob = json.dumps(clean).lower()
    for banned in ("image", "jpeg", "base64", "landmark", "overlay", "coord", "point"):
        assert banned not in blob, f"sanitized summary still exposes {banned!r}"
    # whitelisted numbers survived
    assert clean["counts"] == {"blink": 3}
    assert clean["timeline"]["per_hour_rate"] == 2.0
    assert clean["nudges_sent"] == 1
    assert "overlay" not in clean and "image" not in clean and "landmarks" not in clean
    assert not _key_ok("landmark_points") and _key_ok("counts")


# --- also prove the end-to-end persisted item (via the store) is clean -------
def test_end_persisted_item_is_clean(monkeypatch):
    store = MemorySummaryStore()
    c = _build_client(monkeypatch, summary_store=store)
    _session_and_end(c, ANON_A, "2026-10-26")
    rows = store.recent(app_mod._anon_hash(ANON_A), 5)
    assert rows, "a row should have been stored"
    blob = json.dumps(rows).lower()
    for banned in ("image", "jpeg", "base64", "landmark", "overlay"):
        assert banned not in blob
