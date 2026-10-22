"""C6 — state-serialization contract at the service boundary. OWNER: cloud tab.

Covers the 8KB cap (save refused) and the trace sanitizer (full tool sequence, no bytes),
unit-level so they run without the real models.
"""
from __future__ import annotations

import importlib

import pytest

app_mod = importlib.import_module("nunchi.service.app")


# ---- 8KB state cap ---------------------------------------------------------

def test_to_jsonable_accepts_small_state():
    small = {"schema": "1.0", "session_id": "s", "frames_seen": 3}
    assert app_mod._to_jsonable(small) == small


def test_to_jsonable_refuses_over_8kb():
    big = {"schema": "1.0", "blob": "x" * (9 * 1024)}
    with pytest.raises(app_mod._StateTooLarge):
        app_mod._to_jsonable(big)


# ---- trace sanitizer -------------------------------------------------------

def test_safe_tool_calls_keeps_full_ordered_sequence():
    tcs = [
        {"tool": "get_quality", "args": {}, "result_summary": "too_dark"},
        {"tool": "second_look", "args": {"variant": "enhance"}, "result_summary": "skipped:no_variant"},
        {"tool": "request_recalibration", "args": {}, "result_summary": "requested"},
    ]
    out = app_mod._safe_tool_calls(tcs)
    assert [t["tool"] for t in out] == ["get_quality", "second_look", "request_recalibration"]
    assert out[1]["args"]["variant"] == "enhance"


def test_safe_jsonable_strips_bytes_and_unknown_types():
    import numpy as np

    payload = {
        "raw": b"\xff\xd8\xff\xe0JPEGDATA",          # image-like bytes -> tag, not content
        "arr": np.zeros((2, 2), dtype=np.uint8),       # ndarray -> type tag
        "ok": 1.5,
        "label": "fine",
    }
    out = app_mod._safe_jsonable(payload)
    assert out["ok"] == 1.5 and out["label"] == "fine"
    assert out["raw"].startswith("<bytes:") and "JPEGDATA" not in out["raw"]
    assert out["arr"].startswith("<ndarray")


def test_safe_jsonable_truncates_long_strings():
    out = app_mod._safe_jsonable("a" * 1000)
    assert out.endswith("…") and len(out) <= 257


def test_safe_tool_calls_ignores_non_dicts():
    assert app_mod._safe_tool_calls([None, "x", 3, {"tool": "ok"}]) == [
        {"tool": "ok", "args": {}, "result_summary": ""}
    ]
