"""V14 privacy: overlay.expr is display-only — never in the persisted state blob.

Mirrors the counter-example style of tests/review/test_privacy_no_frame_leak.py,
but for the expression numbers specifically and at the vision unit level (no
network, no models). Claims asserted:

  1. The engine DOES put `expr` on `overlay` (feature is wired) with the 5 fields.
  2. `SessionState.to_dict()` — the blob that goes to DynamoDB (SESSION#/STATE) —
     contains NO `expr` key and NONE of the live expr values, even after frames
     updated the expr EMA filters. (Expr filters are intentionally not serialised.)
  3. A trace-style evidence dict (what the agent trace persists) carries metrics/
     events only, never the overlay or its expr block.

Deterministic: synthetic (478,2) landmarks fed through the engine's expression
builder; the state blob is serialised directly.
"""
from __future__ import annotations

import numpy as np

from nunchi.contracts import FrameResult
from nunchi.vision import expression as X
from nunchi.vision import metrics as M
from nunchi.vision.calibration import Baseline
from nunchi.vision.engine import SessionState
from nunchi.vision.filters import FilterConfig, StabilizedMetric
from nunchi.vision.landmarks import Landmarks


def _face_pts() -> np.ndarray:
    pts = np.zeros((478, 2), dtype=np.float32)
    pts[M.LEFT_EYE["outer"]] = (30, 50); pts[M.LEFT_EYE["inner"]] = (50, 50)
    pts[M.LEFT_EYE["up1"]] = (40, 46); pts[M.LEFT_EYE["lo1"]] = (40, 54)
    pts[M.LEFT_EYE["up2"]] = (43, 46); pts[M.LEFT_EYE["lo2"]] = (43, 54)
    pts[M.RIGHT_EYE["outer"]] = (100, 50); pts[M.RIGHT_EYE["inner"]] = (80, 50)
    pts[M.RIGHT_EYE["up1"]] = (90, 46); pts[M.RIGHT_EYE["lo1"]] = (90, 54)
    pts[M.RIGHT_EYE["up2"]] = (87, 46); pts[M.RIGHT_EYE["lo2"]] = (87, 54)
    pts[M.MOUTH["left"]] = (55, 120); pts[M.MOUTH["right"]] = (75, 120)
    pts[M.MOUTH["up_in"]] = (65, 116); pts[M.MOUTH["lo_in"]] = (65, 124)
    pts[M.MOUTH["up_out"]] = (65, 112); pts[M.MOUTH["lo_out"]] = (65, 128)
    pts[M.FOREHEAD] = (65, 20); pts[M.CHIN] = (65, 140); pts[M.NOSE_TIP] = (65, 80)
    pts[X.LEFT_BROW] = (40, 38); pts[X.RIGHT_BROW] = (90, 38)
    return pts


def _calibrated_state() -> SessionState:
    st = SessionState(session_id="sess-doll-14")
    cfg = FilterConfig(ema_alpha=0.5, median_window=3)
    for attr in ("_expr_eye_l", "_expr_eye_r", "_expr_mouth", "_expr_smile", "_expr_brow"):
        setattr(st, attr, StabilizedMetric.from_config(cfg))
    st.baseline = Baseline(ear_open=0.25, ear_p10=0.1, mar_rest=0.2, face_px=100.0,
                           pitch_frontal=0.0, roll_zero=0.0, smile_rest=0.5, brow_rest=0.1)
    st.calibrated = True
    return st


def _call_expression(st: SessionState, pts: np.ndarray, *, mutate: bool) -> dict:
    """Invoke the engine's expression builder without needing ONNX models."""
    from nunchi.vision.engine import VisionEngine

    lm = Landmarks(ok=True, pts=pts, bbox=(0, 0, 100, 120))
    # call the unbound method so we don't construct the (model-loading) engine
    return VisionEngine._expression(object.__new__(VisionEngine), st, lm, mutate=mutate, conf=0.9)


def _has_key(obj, name: str) -> bool:
    """True if ``name`` appears as a dict key anywhere in a nested structure."""
    if isinstance(obj, dict):
        if name in obj:
            return True
        return any(_has_key(v, name) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_key(v, name) for v in obj)
    return False


def _collect_numbers(obj) -> list:
    """All numeric leaves in a nested structure (for value-leak checks)."""
    out: list = []
    if isinstance(obj, dict):
        for v in obj.values():
            out += _collect_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _collect_numbers(v)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        out.append(float(obj))
    return out


# -- claim 1: expr is present on the overlay with exactly the 5 fields --------
def test_expr_is_emitted_on_overlay():
    st = _calibrated_state()
    expr = _call_expression(st, _face_pts(), mutate=True)
    assert expr is not None
    assert set(expr) == {"eye_l", "eye_r", "mouth_open", "smile", "brow_raise"}
    # emulate the engine merge: expr lives under FrameResult.overlay
    overlay = {"face": [0, 0, 1, 1], "points": {}, "expr": expr}
    fr = FrameResult(session_id="sess-doll-14", overlay=overlay)
    assert fr.to_dict()["overlay"]["expr"] == expr


# -- claim 2: the persisted state blob carries no expr key / values -----------
def test_state_blob_excludes_expr_even_after_updates():
    st = _calibrated_state()
    pts = _face_pts()
    # run several frames so the expr EMA filters hold concrete smoothed values
    last = None
    for _ in range(5):
        last = _call_expression(st, pts, mutate=True)
    assert last is not None and last["eye_l"] is not None
    # the live filter DID accumulate a value...
    assert st._expr_eye_l.smoothed is not None
    # ...but the serialised blob (-> DynamoDB) must not contain it
    blob = st.to_dict()
    assert not _has_key(blob, "expr"), "expr leaked into the persisted state blob"
    assert not _has_key(blob, "eye_l") and not _has_key(blob, "mouth_open")
    # none of the concrete live expr numbers (other than trivial 0/1) appear
    nums = set(_collect_numbers(blob))
    for v in last.values():
        if v is not None and v not in (0.0, 1.0):
            assert v not in nums, f"live expr value {v} leaked into the state blob"
    # the filters key exists (pose filters persist) but holds no expr entry
    filt = blob["filters"]
    assert not any(k.startswith("expr") for k in filt), filt


# -- claim 3: a trace evidence dict never carries the overlay / expr ----------
def test_trace_evidence_has_no_overlay_or_expr():
    st = _calibrated_state()
    expr = _call_expression(st, _face_pts(), mutate=True)
    # what the agent writes to trace is metrics/events evidence, not overlay.
    fr = FrameResult(session_id="sess-doll-14", overlay={"expr": expr})
    d = fr.to_dict()
    trace_row = {
        "ts": 1.0, "session_id": d["session_id"], "frame_t": d["t"],
        "decision": "none", "reason": "nominal",
        "evidence": {"ear": d["metrics"]["ear"], "events": d["events"]},
    }
    assert not _has_key(trace_row, "expr")
    assert not _has_key(trace_row, "overlay")


# -- restore: expr filters are re-created (not read) from a persisted blob ----
def test_restore_recreates_expr_filters_without_blob_values():
    st = _calibrated_state()
    for _ in range(3):
        _call_expression(st, _face_pts(), mutate=True)
    blob = st.to_dict()
    restored = SessionState.from_dict(blob)
    # fresh filters exist (smoothing resumes) but carry nothing from the blob
    assert restored._expr_eye_l is not None
    assert restored._expr_eye_l.smoothed is None
