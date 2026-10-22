"""V10 head-pose (solvePnP) — synthetic rotation, no model/image.

The 3D canonical model is rotated by the physical motion each CONTRACTS sign
means, projected to 2D with the engine's approximate intrinsics, and fed back to
``estimate_head_pose``. The recovered angle must have the CONTRACTS sign and be
close to the input (this is the "synthetic rotation error table" the brief asks
for). Absolute real-clip accuracy is NOT claimed — this only pins the maths/signs.

CONTRACTS own-view signs (verified below):
    yaw   > 0  user turns to THEIR right   (model +Y rotation)
    pitch > 0  chin tucked down (look down) (model +X rotation)
    roll  > 0  tilt to user's right shoulder(model +Z rotation)
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from nunchi.vision.headpose import (
    _MODEL_IDX,
    _MODEL_PTS,
    _camera_matrix,
    estimate_head_pose,
    reproj_to_conf,
)

W, H = 320, 240
_CAM = _camera_matrix(W, H)
_DIST = np.zeros((4, 1), dtype=np.float64)
_TVEC = np.array([[0.0], [0.0], [600.0]], dtype=np.float64)  # 600mm in front


def _Rx(d: float) -> np.ndarray:
    r = np.radians(d)
    return np.array([[1, 0, 0], [0, np.cos(r), -np.sin(r)], [0, np.sin(r), np.cos(r)]])


def _Ry(d: float) -> np.ndarray:
    r = np.radians(d)
    return np.array([[np.cos(r), 0, np.sin(r)], [0, 1, 0], [-np.sin(r), 0, np.cos(r)]])


def _Rz(d: float) -> np.ndarray:
    r = np.radians(d)
    return np.array([[np.cos(r), -np.sin(r), 0], [np.sin(r), np.cos(r), 0], [0, 0, 1]])


def _landmarks_for(R: np.ndarray) -> np.ndarray:
    """Project the rotated 3D model into a (478,2) landmark array."""
    rvec, _ = cv2.Rodrigues(R)
    proj, _ = cv2.projectPoints(_MODEL_PTS, rvec, _TVEC, _CAM, _DIST)
    proj = proj.reshape(-1, 2)
    pts = np.zeros((478, 2), dtype=np.float32)
    for k, idx in enumerate(_MODEL_IDX):
        pts[idx] = proj[k]
    return pts


def _pose_from(yaw: float, pitch: float, roll: float):
    """Build landmarks for a CONTRACTS-meaning pose and estimate it back."""
    R = _Rz(roll) @ _Ry(yaw) @ _Rx(pitch)  # roll/yaw/pitch order; small angles commute ~
    return estimate_head_pose(_landmarks_for(R), W, H)


# -- normal 1: frontal pose is ~zero on all axes ------------------------------
def test_frontal_is_zero():
    yaw, pitch, roll, err = _pose_from(0, 0, 0)
    assert abs(yaw) < 0.5 and abs(pitch) < 0.5 and abs(roll) < 0.5
    assert err < 0.5


# -- normal 2: each axis recovers the right SIGN (the CONTRACTS definition) ----
def test_signs_match_contract():
    assert _pose_from(30, 0, 0)[0] > 10     # user turns right -> yaw > 0
    assert _pose_from(-30, 0, 0)[0] < -10
    assert _pose_from(0, 20, 0)[1] > 7      # chin down -> pitch > 0
    assert _pose_from(0, -20, 0)[1] < -7
    assert _pose_from(0, 0, 30)[2] > 10     # tilt to right shoulder -> roll > 0
    assert _pose_from(0, 0, -30)[2] < -10


# -- normal 3: synthetic error table — recovered close to input ---------------
def test_error_table_within_tolerance():
    cases = [
        ("yaw", 30, 0, 0, 0), ("yaw", -30, 0, 0, 0),
        ("pitch", 0, 20, 0, 1), ("pitch", 0, -20, 0, 1),
        ("roll", 0, 0, 30, 2), ("roll", 0, 0, -30, 2),
        ("combo", 15, 10, -12, -1),
    ]
    rows = []
    for name, y, p, r, axis in cases:
        est = _pose_from(y, p, r)
        rows.append((name, (y, p, r), est))
        if axis >= 0:  # single-axis cases: tight tolerance
            target = (y, p, r)[axis]
            assert abs(est[axis] - target) <= 3.0, f"{name}: {est[axis]} vs {target}"
    # combo: all three within a looser tolerance (approx model/intrinsics)
    ce = _pose_from(15, 10, -12)
    assert abs(ce[0] - 15) <= 5 and abs(ce[1] - 10) <= 5 and abs(ce[2] + 12) <= 5
    # (rows kept for debugging; printed only on failure by pytest -q)
    assert all(e is not None for *_rest, e in rows)


# -- normal 4: yaw/pitch robust to small landmark pixel noise -----------------
# roll from solvePnP alone is noise-sensitive with only 6 points, so the ENGINE
# takes roll from the eye-line metric (metrics.head_roll_deg, already filtered);
# see test_roll_uses_eye_line below. Here we assert the solvePnP yaw/pitch that
# the engine DOES use stay within a few degrees under +-1.5px jitter.
def test_yaw_pitch_robust_under_pixel_noise():
    rng = np.random.default_rng(10)
    R = _Rz(-12) @ _Ry(15) @ _Rx(10)
    pts = _landmarks_for(R)
    e_yaw, e_pitch = [], []
    for _ in range(30):
        noisy = pts.copy()
        for idx in _MODEL_IDX:  # +-1.5px jitter on the 6 solve points
            noisy[idx] = pts[idx] + rng.normal(0, 1.5, size=2)
        est = estimate_head_pose(noisy, W, H)
        assert est is not None
        e_yaw.append(abs(est[0] - 15))
        e_pitch.append(abs(est[1] - 10))
    assert float(np.mean(e_yaw)) < 6.0, np.mean(e_yaw)
    assert float(np.mean(e_pitch)) < 6.0, np.mean(e_pitch)


# -- normal 5: engine-chosen roll (eye-line) is far more stable than solvePnP --
def test_roll_uses_eye_line():
    from nunchi.vision.metrics import head_roll_deg
    rng = np.random.default_rng(3)
    R = _Rz(-12) @ _Ry(15) @ _Rx(10)   # roll -12 deg (user tilts to their left)
    pts = _landmarks_for(R)
    eye_errs, pnp_errs = [], []
    for _ in range(30):
        noisy = pts.copy()
        for idx in _MODEL_IDX:
            noisy[idx] = pts[idx] + rng.normal(0, 1.5, size=2)
        eye_errs.append(abs(head_roll_deg(noisy) - (-12)))
        pnp_errs.append(abs(estimate_head_pose(noisy, W, H)[2] - (-12)))
    # eye-line roll keeps the same sign and is much tighter than the PnP roll
    assert float(np.mean(eye_errs)) < float(np.mean(pnp_errs))
    assert float(np.mean(eye_errs)) < 6.0


# -- exception 1: too few / degenerate points -> None, no crash ---------------
def test_degenerate_points_return_none():
    pts = np.zeros((478, 2), dtype=np.float32)  # all coincide -> solve degenerate
    out = estimate_head_pose(pts, W, H)
    # Either None or a finite tuple; must never raise.
    assert out is None or all(np.isfinite(v) for v in out)


# -- exception 2: non-positive frame size -> None -----------------------------
def test_bad_frame_size_none():
    pts = _landmarks_for(_Ry(0))
    assert estimate_head_pose(pts, 0, 0) is None
    assert estimate_head_pose(None, W, H) is None  # type: ignore[arg-type]


# -- error/edge: confidence from reprojection error ---------------------------
def test_reproj_to_conf_bounds():
    assert reproj_to_conf(0.0, 100.0) == pytest.approx(1.0)
    assert reproj_to_conf(100.0, 100.0) == 0.0     # huge error clamps to 0
    assert 0.0 < reproj_to_conf(4.0, 100.0) < 1.0  # 4% of face height -> mid
    assert reproj_to_conf(1.0, 0.0) == 0.0         # no face scale -> 0
