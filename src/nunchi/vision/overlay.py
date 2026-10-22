"""Build the display-only overlay for FrameResult (web draws "what OpenCV sees").

Contract (CONTRACTS §1): coordinates only, 0-1 normalised to the analysed frame,
no pixels, never persisted/traced. We export a small, fixed set (<=20 points) —
the 5 YuNet-style key points plus a sparse eye/mouth contour — not the raw 478
mesh points. Web handles mirroring and scaling.

The head-pose block (``overlay["pose"]`` = yaw/pitch/roll/depth/conf for the web
posture doll, V10) is MERGED IN BY THE ENGINE after this builder — it is numbers,
not coordinate points, so it is not counted against ``MAX_OVERLAY_POINTS``.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from nunchi.vision import metrics as M

# Sparse eye/mouth contour indices (subset of Face Mesh), kept small for display.
_EYE_L_CONTOUR = [M.LEFT_EYE["outer"], M.LEFT_EYE["up1"], M.LEFT_EYE["inner"], M.LEFT_EYE["lo1"]]
_EYE_R_CONTOUR = [M.RIGHT_EYE["outer"], M.RIGHT_EYE["up1"], M.RIGHT_EYE["inner"], M.RIGHT_EYE["lo1"]]
_MOUTH_CONTOUR = [M.MOUTH["left"], M.MOUTH["up_out"], M.MOUTH["right"], M.MOUTH["lo_out"]]
# Max points we will ever emit (5 key + 4+4+4 contour = 17) — asserted <=20.
MAX_OVERLAY_POINTS = 20


def _n(x: float, y: float, w: int, h: int) -> list[float]:
    return [round(float(x) / w, 4), round(float(y) / h, 4)]


def build_overlay(pts: np.ndarray | None, bbox: tuple[int, int, int, int] | None,
                  frame_w: int, frame_h: int) -> dict[str, Any] | None:
    """Return normalised overlay dict, or None when there is no face.

    ``pts`` is the (478,2) Face Mesh array in full-frame pixels; ``bbox`` is the
    YuNet face box (x,y,w,h) in pixels.
    """
    if pts is None or bbox is None or frame_w <= 0 or frame_h <= 0:
        return None

    x, y, w, h = bbox
    face = [round(x / frame_w, 4), round(y / frame_h, 4),
            round(w / frame_w, 4), round(h / frame_h, 4)]

    key = {
        "eye_l": _n(*pts[M.LEFT_EYE["outer"]], frame_w, frame_h),
        "eye_r": _n(*pts[M.RIGHT_EYE["outer"]], frame_w, frame_h),
        "nose": _n(*pts[M.NOSE_TIP], frame_w, frame_h),
        "mouth_l": _n(*pts[M.MOUTH["left"]], frame_w, frame_h),
        "mouth_r": _n(*pts[M.MOUTH["right"]], frame_w, frame_h),
    }
    contour = {
        "eye_l": [_n(*pts[i], frame_w, frame_h) for i in _EYE_L_CONTOUR],
        "eye_r": [_n(*pts[i], frame_w, frame_h) for i in _EYE_R_CONTOUR],
        "mouth": [_n(*pts[i], frame_w, frame_h) for i in _MOUTH_CONTOUR],
    }
    n_points = len(key) + sum(len(v) for v in contour.values())
    assert n_points <= MAX_OVERLAY_POINTS, f"overlay has {n_points} points (>{MAX_OVERLAY_POINTS})"
    return {"face": face, "points": key, "contour": contour}
