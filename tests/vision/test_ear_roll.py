"""V6 roll-aligned EAR — synthetic, no model/image.

Build a tiny set of eye landmarks with a known aperture, rotate them by a known
head tilt, and show the roll-aligned EAR stays ~constant while the plain EAR
drifts. This is the structural fix for "big rotation inflates EAR variance".
"""
from __future__ import annotations

import numpy as np

from nunchi.vision.metrics import LEFT_EYE, eye_aspect_ratio, roll_aligned_ear


def _eye_points(aperture: float = 0.3, half_w: float = 1.0):
    """A synthetic full-mesh array where LEFT_EYE indices form an open eye.

    Eye centred at origin: outer/inner on the x-axis (± half_w), upper lids above,
    lower lids below by ``aperture`` (so EAR ≈ aperture/half_w).
    """
    pts = np.zeros((478, 2), dtype=np.float64)
    e = LEFT_EYE
    pts[e["outer"]] = [-half_w, 0.0]
    pts[e["inner"]] = [half_w, 0.0]
    pts[e["up1"]] = [-0.3, aperture]
    pts[e["up2"]] = [0.3, aperture]
    pts[e["lo1"]] = [-0.3, -aperture]
    pts[e["lo2"]] = [0.3, -aperture]
    return pts


def _rotate_all(pts: np.ndarray, deg: float) -> np.ndarray:
    th = np.radians(deg)
    c, s = np.cos(th), np.sin(th)
    m = np.array([[c, -s], [s, c]])
    return pts @ m.T


# -- normal 1: plain EAR drifts under rotation; aligned EAR holds -------------
def test_roll_aligned_ear_is_tilt_invariant():
    base = _eye_points(aperture=0.3)
    ear0 = eye_aspect_ratio(base, LEFT_EYE)
    aligned0 = roll_aligned_ear(base, LEFT_EYE, 0.0)
    assert abs(ear0 - aligned0) < 1e-6          # no tilt -> identical

    for deg in (10, 20, 30):
        rot = _rotate_all(base, deg)
        plain = eye_aspect_ratio(rot, LEFT_EYE)
        aligned = roll_aligned_ear(rot, LEFT_EYE, deg)
        # aligned EAR must stay close to the untilted value...
        assert abs(aligned - aligned0) < 0.02, f"aligned drifted at {deg}deg: {aligned} vs {aligned0}"
        # ...and be at least as stable as the plain EAR at big tilt
        if deg >= 20:
            assert abs(aligned - aligned0) <= abs(plain - ear0) + 1e-9


# -- normal 2: a closed eye still reads lower EAR after alignment --------------
def test_roll_aligned_ear_tracks_closure():
    open_eye = _eye_points(aperture=0.3)
    closed_eye = _eye_points(aperture=0.05)
    for deg in (0, 25):
        o = roll_aligned_ear(_rotate_all(open_eye, deg), LEFT_EYE, deg)
        c = roll_aligned_ear(_rotate_all(closed_eye, deg), LEFT_EYE, deg)
        assert c < o                              # closure lowers EAR at any tilt


# -- exception: zero-size / degenerate eye doesn't divide by zero -------------
def test_roll_aligned_ear_degenerate_no_crash():
    pts = np.zeros((478, 2), dtype=np.float64)    # all points coincide
    val = roll_aligned_ear(pts, LEFT_EYE, 15.0)
    assert np.isfinite(val)                       # 1e-6 guard -> finite, no crash
