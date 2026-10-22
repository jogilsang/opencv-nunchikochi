"""Tests for geometric metrics (synthetic landmark arrays, no model/image)."""
from __future__ import annotations

import numpy as np

from nunchi.vision import metrics as M


def _base_pts() -> np.ndarray:
    """A minimal 478-point array with the indices we use placed sensibly."""
    pts = np.zeros((478, 2), dtype=np.float32)
    # eyes: outer/inner on a horizontal line; upper/lower symmetric about it
    # left eye around x=40
    pts[M.LEFT_EYE["outer"]] = (30, 50); pts[M.LEFT_EYE["inner"]] = (50, 50)
    pts[M.LEFT_EYE["up1"]] = (40, 46); pts[M.LEFT_EYE["lo1"]] = (40, 54)
    pts[M.LEFT_EYE["up2"]] = (43, 46); pts[M.LEFT_EYE["lo2"]] = (43, 54)
    # right eye around x=90
    pts[M.RIGHT_EYE["outer"]] = (100, 50); pts[M.RIGHT_EYE["inner"]] = (80, 50)
    pts[M.RIGHT_EYE["up1"]] = (90, 46); pts[M.RIGHT_EYE["lo1"]] = (90, 54)
    pts[M.RIGHT_EYE["up2"]] = (87, 46); pts[M.RIGHT_EYE["lo2"]] = (87, 54)
    # mouth
    pts[M.MOUTH["left"]] = (55, 120); pts[M.MOUTH["right"]] = (75, 120)
    pts[M.MOUTH["up_in"]] = (65, 116); pts[M.MOUTH["lo_in"]] = (65, 124)
    pts[M.MOUTH["up_out"]] = (65, 112); pts[M.MOUTH["lo_out"]] = (65, 128)
    # face box + nose
    pts[M.FOREHEAD] = (65, 20); pts[M.CHIN] = (65, 140); pts[M.NOSE_TIP] = (65, 80)
    return pts


# -- normal 1: open eye has higher EAR than a closed (flattened) eye ----------
def test_ear_open_higher_than_closed():
    pts = _base_pts()
    ear_open = M.eye_aspect_ratio(pts, M.LEFT_EYE)
    closed = pts.copy()
    # flatten eyelids toward the eye line -> smaller vertical gap
    for k in ("up1", "up2"):
        closed[M.LEFT_EYE[k]] = (closed[M.LEFT_EYE[k]][0], 50)
    for k in ("lo1", "lo2"):
        closed[M.LEFT_EYE[k]] = (closed[M.LEFT_EYE[k]][0], 50)
    ear_closed = M.eye_aspect_ratio(closed, M.LEFT_EYE)
    assert ear_open > ear_closed
    assert ear_closed < 0.05


# -- normal 2: open mouth has higher MAR than closed --------------------------
def test_mar_open_higher_than_closed():
    pts = _base_pts()
    mar_rest = M.mouth_aspect_ratio(pts)
    openm = pts.copy()
    openm[M.MOUTH["lo_in"]] = (65, 150); openm[M.MOUTH["lo_out"]] = (65, 160)
    assert M.mouth_aspect_ratio(openm) > mar_rest


# -- normal 3: roll sign follows a tilted eye line ----------------------------
def test_roll_follows_tilt():
    pts = _base_pts()
    assert abs(M.head_roll_deg(pts)) < 1.0  # level eyes -> ~0
    tilted = pts.copy()
    tilted[M.RIGHT_EYE["outer"]] = (100, 70)  # right eye lower -> positive angle
    assert M.head_roll_deg(tilted) > 5.0


# -- normal 4: face_scale is ratio to baseline; None without baseline ---------
def test_face_scale_ratio():
    pts = _base_pts()
    m_none = M.raw_metrics(pts)
    assert m_none.face_scale is None
    fh = M.face_height(pts)
    m_half = M.raw_metrics(pts, baseline_face_px=fh * 2)  # face is half of baseline
    assert m_half.face_scale == 0.5


# -- exception 1: degenerate eye (zero width) does not divide by zero ---------
def test_ear_degenerate_no_crash():
    pts = _base_pts()
    pts[M.LEFT_EYE["inner"]] = pts[M.LEFT_EYE["outer"]]  # width 0
    val = M.eye_aspect_ratio(pts, M.LEFT_EYE)
    assert np.isfinite(val)


# -- exception 2: zero face height -> pitch proxy finite ----------------------
def test_pitch_zero_height_finite():
    pts = _base_pts()
    pts[M.CHIN] = pts[M.FOREHEAD]  # height 0
    assert np.isfinite(M.pitch_proxy(pts))


# -- error/edge: raw_metrics rounds and fills all contract fields -------------
def test_raw_metrics_fields():
    m = M.raw_metrics(_base_pts(), baseline_face_px=100.0)
    assert m.ear is not None and m.mar is not None
    assert m.head_roll_deg is not None and m.head_pitch_proxy is not None
    assert m.face_scale is not None
