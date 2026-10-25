"""Q2 independent verifier — adversarial privacy counter-examples. READ-ONLY tab.

These are NEW tests written by the verification tab; they do not modify any source.
They attack the privacy claims of the new storage path (summary_store + X-Anon-Id)
from angles the existing suite (test_no_persist, test_history_trend) does not cover:

  * the stored partition key reveals nothing about the raw anon token (one-way,
    token not a substring of the hash, different tokens -> different hashes);
  * a maliciously-shaped summary with image/coord/landmark fields buried deep in
    nested maps AND inside list elements is still fully stripped;
  * bytes / ndarray values never survive into the stored item;
  * a frame marker pushed through the summary (simulating an upstream bug) never
    lands in the stored DynamoDB-shaped item;
  * reading one user's history can never surface another user's rows, even when
    both wrote on the same day.

If any of these fail, the "numbers-only, no raw id, isolated" claim is broken.
"""
from __future__ import annotations

import importlib
import json

import numpy as np

from nunchi.service.summary_store import (
    MemorySummaryStore,
    _key_ok,
    _numbers_only,
    sanitize_summary,
)

# `nunchi.service.app` the package attr is the FastAPI instance; the module (with
# _anon_hash) must be fetched explicitly (same pattern as test_history_trend).
app_mod = importlib.import_module("nunchi.service.app")

_BANNED = ("image", "jpeg", "base64", "landmark", "frame", "pixel",
           "overlay", "coord", "point", "bytes", "data:")

# a concrete needle a buggy upstream might try to stash in a summary
MARKER = "NUNCHI_FRAME_MARKER_0xDEADBEEF"


# --- normal 1: the hash is one-way and never equals / contains the token -----
def test_anon_hash_is_one_way_and_hides_token():
    """normal: a valid token maps to a 32-hex hash that does not contain the token,
    is stable, and differs for different tokens (no truncation collision in practice)."""
    tok = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"          # 32 hex
    h = app_mod._anon_hash(tok)
    assert h is not None and len(h) == 32
    assert tok not in h and h != tok                   # token not recoverable from hash
    assert app_mod._anon_hash(tok) == h                # deterministic
    # a one-character change yields a completely different partition
    h2 = app_mod._anon_hash("b1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
    assert h2 != h


# --- normal 2: the raw token never appears in the store, even as the pk -------
def test_raw_token_absent_from_stored_data():
    """normal: writing under a token stores it hashed; the raw token is in neither
    the keys nor the values of the store."""
    store = MemorySummaryStore()
    tok = "feedfacefeedfacefeedfacefeedface"
    uh = app_mod._anon_hash(tok)
    store.put_day(uh, "2026-10-26", "sid00001",
                  {"session_id": "s1", "date": "2026-10-26", "counts": {"blink": 2}})
    dumped = json.dumps(store._data)
    assert tok not in dumped                            # token never serialised
    assert uh in dumped                                 # only the hash is a key


# --- exception 1: banned fields buried deep / in lists are all stripped -------
def test_deeply_nested_and_list_image_fields_are_stripped():
    """exception: image/landmark/coord keys nested several maps deep AND inside list
    elements are removed; whitelisted numbers around them survive."""
    dirty = {
        "session_id": "s1", "date": "2026-10-26", "counts": {"blink": 1},
        "timeline": {
            "per_hour_rate": 2.0,
            "bad_posture": {"5m": [
                {"start_s": 0, "events": 1, "overlay_points": [[1, 2], [3, 4]]},
                {"start_s": 300, "events": 2, "frame_jpeg_base64": "/9j/AAAA"},
            ]},
            "nested": {"a": {"b": {"c": {"landmark_xy": [0.1, 0.2], "keep": 9}}}},
        },
    }
    clean = sanitize_summary(dirty)
    blob = json.dumps(clean).lower()
    for b in _BANNED:
        assert b not in blob, f"banned substring {b!r} survived sanitise at depth"
    # the legitimate numbers are intact
    assert clean["counts"] == {"blink": 1}
    assert clean["timeline"]["per_hour_rate"] == 2.0
    assert clean["timeline"]["bad_posture"]["5m"][0] == {"start_s": 0, "events": 1}
    assert clean["timeline"]["nested"]["a"]["b"]["c"] == {"keep": 9}


# --- exception 2: bytes / ndarray values never survive ------------------------
def test_bytes_and_ndarray_never_stored():
    """exception: raw bytes (JPEG) or a numpy array placed in a value is dropped to
    None, so no pixel payload can ride into the item through a non-image key name."""
    dirty = {
        "session_id": "s", "date": "2026-10-26",
        "seconds": {"blob": b"\xff\xd8" + MARKER.encode(), "arr": np.zeros((2, 2))},
        "counts": {"ok": 3},
    }
    clean = sanitize_summary(dirty)
    blob = json.dumps(clean)
    assert MARKER not in blob and "\\xff" not in blob
    # the non-serialisable values collapsed to null, the sibling number stayed
    assert clean["seconds"]["blob"] is None
    assert clean["seconds"]["arr"] is None or isinstance(clean["seconds"]["arr"], list)
    assert clean["counts"] == {"ok": 3}


# --- error 1: a marker forced through end() never reaches the stored item -----
def test_marker_in_summary_never_reaches_store_item():
    """error/abuse: even if an upstream bug attaches a marker-bearing image field to
    the summary, the DynamoDB-shaped item built from it carries no marker."""
    # exercise the Dynamo item builder's sanitise without touching AWS by reusing the
    # memory store's identical sanitise gate, then also prove the key whitelist.
    store = MemorySummaryStore()
    uh = app_mod._anon_hash("0123456789abcdef0123456789abcdef")
    store.put_day(uh, "2026-10-26", "sid1", {
        "session_id": "s", "date": "2026-10-26", "counts": {"blink": 1},
        "frame_jpeg": "/9j/" + MARKER, "image": MARKER, "landmarks": [[0, 0]],
    })
    rows = store.recent(uh, 5)
    blob = json.dumps(rows)
    assert MARKER not in blob
    for b in _BANNED:
        assert b not in blob.lower()
    assert rows and rows[0]["counts"] == {"blink": 1}
    # the helper itself refuses banned keys and accepts whitelisted ones
    assert not _key_ok("frame_jpeg") and not _key_ok("landmark_pts")
    assert _key_ok("counts") and _key_ok("timeline")
    # defensive: _numbers_only caps recursion depth (no stack blow-up on hostile input)
    deep: dict = {}
    cur = deep
    for _ in range(50):
        cur["counts"] = {}
        cur = cur["counts"]
    assert _numbers_only(deep) is not None   # returns, does not recurse forever


# --- normal 3: cross-user isolation on the same day --------------------------
def test_same_day_two_users_isolated_in_store():
    """normal: two users writing the same date never see each other's rows."""
    store = MemorySummaryStore()
    ua = app_mod._anon_hash("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    ub = app_mod._anon_hash("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    assert ua != ub
    store.put_day(ua, "2026-10-26", "s1", {"session_id": "a", "date": "2026-10-26", "counts": {"blink": 1}})
    store.put_day(ub, "2026-10-26", "s1", {"session_id": "b", "date": "2026-10-26", "counts": {"yawn": 9}})
    ra = store.recent(ua, 5)
    rb = store.recent(ub, 5)
    assert len(ra) == 1 and len(rb) == 1
    assert ra[0]["counts"] == {"blink": 1}
    assert rb[0]["counts"] == {"yawn": 9}
    assert json.dumps(ra) != json.dumps(rb)
