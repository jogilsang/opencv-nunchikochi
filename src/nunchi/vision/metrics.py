"""Geometric metrics from 478 Face Mesh landmarks (EAR, MAR, roll, pitch proxy, face scale).

Pure NumPy on landmark coordinates — no image, no inference here. Index constants
are MediaPipe Face Mesh standard points. These produce raw per-frame values; the
engine stabilises them (filters.py) and interprets them relative to the calibrated
baseline (calibration.py).
"""
from __future__ import annotations

import numpy as np

from nunchi.contracts import Metrics

# MediaPipe Face Mesh eyelid points for EAR. Each eye: (outer, inner, up1, up2, lo1, lo2).
# EAR = (|up1-lo1| + |up2-lo2|) / (2 * |outer-inner|)
LEFT_EYE = {"outer": 33, "inner": 133, "up1": 159, "up2": 158, "lo1": 145, "lo2": 153}
RIGHT_EYE = {"outer": 263, "inner": 362, "up1": 386, "up2": 385, "lo1": 374, "lo2": 380}

# Mouth points for MAR. horizontal: 61 (left corner) - 291 (right corner);
# vertical pairs: upper/lower lip 13/14 (inner), 0/17 (outer center).
MOUTH = {"left": 61, "right": 291, "up_in": 13, "lo_in": 14, "up_out": 0, "lo_out": 17}

# Head roll from the eye line (outer corners); pitch proxy from nose-tip vs eye line.
NOSE_TIP = 1
CHIN = 152
FOREHEAD = 10


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


def _rotate_pts(pts: np.ndarray, deg: float) -> np.ndarray:
    """Rotate 2D points about their centroid by ``deg`` (CCW in image coords)."""
    if abs(deg) < 1e-6:
        return pts
    c = pts.mean(axis=0)
    th = np.radians(deg)
    cos, sin = np.cos(th), np.sin(th)
    m = np.array([[cos, -sin], [sin, cos]], dtype=np.float64)
    return (pts - c) @ m.T + c


def eye_aspect_ratio(pts: np.ndarray, eye: dict) -> float:
    o, i = pts[eye["outer"]], pts[eye["inner"]]
    v = _dist(pts[eye["up1"]], pts[eye["lo1"]]) + _dist(pts[eye["up2"]], pts[eye["lo2"]])
    h = _dist(o, i)
    return v / (2.0 * h + 1e-6)


def roll_aligned_ear(pts: np.ndarray, eye: dict, roll_deg: float) -> float:
    """EAR with the eye's six points de-rotated by the head ``roll_deg`` first.

    When the head (camera) is tilted, the raw vertical/horizontal eyelid
    distances mix, inflating EAR variance. De-rotating the eye points by
    ``-roll_deg`` about their centroid realigns the eye to the image axes so the
    aspect ratio is tilt-invariant. Falls back to the plain EAR geometry; only the
    coordinate frame changes (no new landmarks, no model).
    """
    idx = [eye["outer"], eye["inner"], eye["up1"], eye["up2"], eye["lo1"], eye["lo2"]]
    sub = np.asarray(pts[idx], dtype=np.float64)
    rot = _rotate_pts(sub, -roll_deg)
    # remap into a tiny dict-free local layout matching `idx` order
    o, i, up1, up2, lo1, lo2 = rot
    v = float(np.linalg.norm(up1 - lo1)) + float(np.linalg.norm(up2 - lo2))
    h = float(np.linalg.norm(o - i))
    return v / (2.0 * h + 1e-6)


def mean_ear(pts: np.ndarray, *, roll_deg: float | None = None) -> float:
    """Mean EAR of both eyes. If ``roll_deg`` given, uses roll-aligned EAR (V6)."""
    if roll_deg is None:
        return (eye_aspect_ratio(pts, LEFT_EYE) + eye_aspect_ratio(pts, RIGHT_EYE)) / 2.0
    return (roll_aligned_ear(pts, LEFT_EYE, roll_deg)
            + roll_aligned_ear(pts, RIGHT_EYE, roll_deg)) / 2.0


def mouth_aspect_ratio(pts: np.ndarray) -> float:
    h = _dist(pts[MOUTH["left"]], pts[MOUTH["right"]])
    v = _dist(pts[MOUTH["up_in"]], pts[MOUTH["lo_in"]]) + _dist(pts[MOUTH["up_out"]], pts[MOUTH["lo_out"]])
    return v / (2.0 * h + 1e-6)


def head_roll_deg(pts: np.ndarray) -> float:
    """Roll (in-image-plane tilt) from the line between the two outer eye corners."""
    le, re = pts[LEFT_EYE["outer"]], pts[RIGHT_EYE["outer"]]
    return float(np.degrees(np.arctan2(re[1] - le[1], re[0] - le[0])))


def face_height(pts: np.ndarray) -> float:
    """Forehead-to-chin pixel height; used for face_scale vs calibrated baseline."""
    return _dist(pts[FOREHEAD], pts[CHIN])


def pitch_proxy(pts: np.ndarray) -> float:
    """Dimensionless forward/down proxy: nose-tip offset below the eye line,
    normalised by face height. Larger = chin tucked / head forward-down.
    Absolute value is meaningless; only the delta vs calibration baseline matters.
    """
    eye_mid_y = (pts[LEFT_EYE["outer"]][1] + pts[RIGHT_EYE["outer"]][1]) / 2.0
    fh = face_height(pts)
    return float((pts[NOSE_TIP][1] - eye_mid_y) / (fh + 1e-6))


def mouth_centre(pts: np.ndarray) -> tuple[float, float]:
    """Mouth centre (x, y) in full-frame pixels, from the lip corners/centre.
    Used for hand-near-mouth proximity (drink, V7)."""
    xs = (pts[MOUTH["left"]][0] + pts[MOUTH["right"]][0]
          + pts[MOUTH["up_in"]][0] + pts[MOUTH["lo_in"]][0]) / 4.0
    ys = (pts[MOUTH["left"]][1] + pts[MOUTH["right"]][1]
          + pts[MOUTH["up_in"]][1] + pts[MOUTH["lo_in"]][1]) / 4.0
    return (float(xs), float(ys))


def raw_metrics(pts: np.ndarray, *, baseline_face_px: float | None = None) -> Metrics:
    """Per-frame raw Metrics from landmarks. face_scale is None without a baseline.

    EAR is roll-aligned (V6): the eye points are de-rotated by the head roll
    before the aspect ratio, so tilt doesn't inflate blink variance.
    """
    roll = head_roll_deg(pts)
    ear = mean_ear(pts, roll_deg=roll)
    mar = mouth_aspect_ratio(pts)
    pitch = pitch_proxy(pts)
    scale = None
    if baseline_face_px:
        scale = round(face_height(pts) / float(baseline_face_px), 3)
    return Metrics(
        ear=round(ear, 4),
        mar=round(mar, 4),
        head_roll_deg=round(roll, 2),
        head_pitch_proxy=round(pitch, 4),
        face_scale=scale,
    )
