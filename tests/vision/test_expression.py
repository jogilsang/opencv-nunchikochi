"""V14 face-expression tests: synthetic landmark geometry, no model/image.

These assert the MEASURED movement (geometry), never an emotion label. Values are
0..1 or None. Normal cases: a smile-shaped mouth raises `smile`, an opened jaw
raises `mouth_open`. Exception cases: a partially occluded eye / pre-calibration
degrade gracefully. Error case: no landmarks is handled by the engine path, here
we assert the raw helpers refuse degenerate input with None.
"""
from __future__ import annotations

import numpy as np

from nunchi.vision import expression as X
from nunchi.vision import metrics as M


def _base_pts() -> np.ndarray:
    """478-point array with a neutral, level, open-eyed resting face."""
    pts = np.zeros((478, 2), dtype=np.float32)
    # left eye around x=40, right around x=90, level, open
    pts[M.LEFT_EYE["outer"]] = (30, 50); pts[M.LEFT_EYE["inner"]] = (50, 50)
    pts[M.LEFT_EYE["up1"]] = (40, 46); pts[M.LEFT_EYE["lo1"]] = (40, 54)
    pts[M.LEFT_EYE["up2"]] = (43, 46); pts[M.LEFT_EYE["lo2"]] = (43, 54)
    pts[M.RIGHT_EYE["outer"]] = (100, 50); pts[M.RIGHT_EYE["inner"]] = (80, 50)
    pts[M.RIGHT_EYE["up1"]] = (90, 46); pts[M.RIGHT_EYE["lo1"]] = (90, 54)
    pts[M.RIGHT_EYE["up2"]] = (87, 46); pts[M.RIGHT_EYE["lo2"]] = (87, 54)
    # resting mouth (slightly open inner lips)
    pts[M.MOUTH["left"]] = (55, 120); pts[M.MOUTH["right"]] = (75, 120)
    pts[M.MOUTH["up_in"]] = (65, 116); pts[M.MOUTH["lo_in"]] = (65, 124)
    pts[M.MOUTH["up_out"]] = (65, 112); pts[M.MOUTH["lo_out"]] = (65, 128)
    # face box + nose + brows above each eye
    pts[M.FOREHEAD] = (65, 20); pts[M.CHIN] = (65, 140); pts[M.NOSE_TIP] = (65, 80)
    pts[X.LEFT_BROW] = (40, 38); pts[X.RIGHT_BROW] = (90, 38)
    return pts


def _refs(pts: np.ndarray) -> dict:
    """Resting references as the calibrator would compute them for this face."""
    roll = M.head_roll_deg(pts)
    ear = M.mean_ear(pts, roll_deg=roll)
    return {
        "ear_open": ear,
        "ear_low": ear * 0.4,       # near-closed reference
        "mar_rest": M.mouth_aspect_ratio(pts),
        "smile_rest": X.smile_proxy_raw(pts),
        "brow_rest": X.brow_eye_distance_raw(pts),
    }


# -- normal 1: open mouth raises mouth_open above resting ---------------------
def test_mouth_open_rises_with_jaw():
    base = _base_pts()
    refs = _refs(base)
    rest = X.raw_expression(base, **refs)
    assert rest["mouth_open"] is not None and rest["mouth_open"] < 0.2  # ~resting
    opened = base.copy()
    opened[M.MOUTH["lo_in"]] = (65, 150); opened[M.MOUTH["lo_out"]] = (65, 165)
    e = X.raw_expression(opened, **refs)
    assert e["mouth_open"] > rest["mouth_open"]
    assert 0.0 <= e["mouth_open"] <= 1.0


# -- normal 2: a wider + raised mouth raises `smile` --------------------------
def test_smile_rises_with_corner_spread_and_raise():
    base = _base_pts()
    refs = _refs(base)
    rest = X.raw_expression(base, **refs)
    assert rest["smile"] is not None and rest["smile"] < 0.2  # near resting
    smiling = base.copy()
    # corners move apart AND up (lower y) relative to the lip centre line
    smiling[M.MOUTH["left"]] = (48, 112); smiling[M.MOUTH["right"]] = (82, 112)
    e = X.raw_expression(smiling, **refs)
    assert e["smile"] > rest["smile"]
    assert 0.0 <= e["smile"] <= 1.0
    # geometry only: nothing claims happiness
    assert set(e) == {"eye_l", "eye_r", "mouth_open", "smile", "brow_raise"}


# -- exception 1: one eye occluded (flattened) reads low but finite -----------
def test_one_eye_occluded_still_finite():
    base = _base_pts()
    refs = _refs(base)
    occ = base.copy()
    # flatten the left eyelids toward the eye line -> near-closed
    for k in ("up1", "up2", "lo1", "lo2"):
        occ[M.LEFT_EYE[k]] = (occ[M.LEFT_EYE[k]][0], 50)
    e = X.raw_expression(occ, **refs)
    assert e["eye_l"] is not None and 0.0 <= e["eye_l"] <= 1.0
    assert e["eye_l"] < e["eye_r"]  # occluded eye reads more closed


# -- exception 2: before calibration (no smile/brow refs) -> those are None ---
def test_pre_calibration_smile_brow_none_but_eyes_mouth_work():
    base = _base_pts()
    roll = M.head_roll_deg(base)
    ear = M.mean_ear(base, roll_deg=roll)
    e = X.raw_expression(base, ear_open=ear, ear_low=ear * 0.4, mar_rest=0.0,
                         smile_rest=None, brow_rest=None)
    assert e["smile"] is None            # can't tell smile from a wide mouth
    assert e["brow_raise"] is None       # no resting brow reference
    assert e["eye_l"] is not None and e["mouth_open"] is not None


# -- error 1: degenerate geometry -> raw helpers return None ------------------
def test_degenerate_geometry_returns_none():
    pts = _base_pts()
    pts[M.CHIN] = pts[M.FOREHEAD]        # face height 0
    assert X.smile_proxy_raw(pts) is None
    assert X.brow_eye_distance_raw(pts) is None
    # eye-open mapping refuses a zero-span reference
    assert X._eye_open_norm(0.2, ear_open=0.2, ear_low=0.2) is None


# -- brow_raise: brow lifting away from the eye raises the value --------------
def test_brow_raise_rises_when_brows_lift():
    base = _base_pts()
    refs = _refs(base)
    rest = X.raw_expression(base, **refs)
    assert rest["brow_raise"] is not None and rest["brow_raise"] < 0.2
    raised = base.copy()
    raised[X.LEFT_BROW] = (40, 30); raised[X.RIGHT_BROW] = (90, 30)  # brows up
    e = X.raw_expression(raised, **refs)
    assert e["brow_raise"] > rest["brow_raise"]
    assert 0.0 <= e["brow_raise"] <= 1.0


# -- stabilisation: EMA damps a single-frame jitter yet tracks a real move ----
def test_ema_smoothing_damps_jitter_and_tracks():
    from nunchi.vision.filters import FilterConfig, StabilizedMetric

    f = StabilizedMetric.from_config(FilterConfig(ema_alpha=0.5, median_window=3))
    # settle at a resting value
    for _ in range(4):
        f.update(0.2)
    rest = f.smoothed
    assert rest is not None and abs(rest - 0.2) < 0.05  # settled at resting
    # a one-frame spike must not fully propagate (median+EMA damp it)
    spiked = f.update(1.0).smoothed
    assert spiked < 0.6, f"single-frame jitter not damped: {spiked}"
    # a sustained move is tracked within a couple of frames (lag < ~200ms @2fps)
    f2 = StabilizedMetric.from_config(FilterConfig(ema_alpha=0.5, median_window=3))
    for _ in range(3):
        f2.update(0.2)
    for _ in range(3):
        f2.update(0.9)
    assert f2.smoothed > 0.6, f"sustained move not tracked: {f2.smoothed}"
