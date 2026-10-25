"""Measurable facial-expression numbers from Face Mesh landmarks (V14).

These are **geometric movements of the face**, normalised to the user's
5-second neutral calibration. They are NOT emotion estimates: nothing here says
"happy" or "sad". We only report how far the eyes/mouth/brows have moved from the
calibrated neutral pose, each as a 0..1 value (or ``None`` when it cannot be
measured). A web "face doll" can mirror these so the puppet's face follows the
user's; see ``docs/eval/FACE_EXPRESSION.md`` for definitions and honest limits.

Fields (each 0..1 or None):
  eye_l, eye_r  per-eye openness: 0 = closed (EAR at/below the calibrated low
                end), 1 = open (EAR at/above the calibrated open reference).
  mouth_open    jaw opening from MAR vs the calibrated resting mouth.
  smile         lip-corner spread/raise vs resting (geometry proxy, not emotion).
  brow_raise    eyebrow-to-eye distance vs resting; None if brow landmarks are
                unreliable (documented limitation).

Pure NumPy on landmark coordinates — no image, no inference, no pixels. The
engine stabilises these with a short EMA (filters.py) and drops them to None when
confidence is low. Raw values feed ``overlay.expr`` (display-only); they are
never persisted or traced (see tests/review/test_privacy_no_frame_leak.py and
tests/vision/test_expression_privacy.py).
"""
from __future__ import annotations

import numpy as np

from nunchi.vision import metrics as M

# MediaPipe Face Mesh eyebrow points (lower edge of each brow, roughly above the
# eye centre). Used only as a relative brow-raise proxy vs the calibrated resting
# distance; absolute values are meaningless. If these indices are degenerate the
# proxy returns None (honest limitation, see FACE_EXPRESSION.md).
LEFT_BROW = 105
RIGHT_BROW = 334


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (min(x, 1.0))


def _eye_open_norm(ear: float, ear_open: float, ear_low: float) -> float | None:
    """Map an EAR to 0..1 openness using the calibrated open/low references.

    ``ear_open`` = neutral open-eye EAR (1.0), ``ear_low`` = low end of the
    open-eye spread treated as near-closed (0.0). Returns None if the references
    are degenerate (no usable spread).
    """
    span = ear_open - ear_low
    if not np.isfinite(ear) or span <= 1e-4:
        return None
    return round(_clamp01((ear - ear_low) / span), 3)


def smile_proxy_raw(pts: np.ndarray) -> float | None:
    """Raw lip-corner spread+raise geometry (dimensionless), normalised by face height.

    smile here = how far the mouth corners sit apart (width) and how high they
    sit relative to the lip centre line, divided by face height so it is scale/
    distance invariant. This is a GEOMETRY proxy for a smile shape, NOT a happiness
    detector. Returns None on degenerate geometry.
    """
    fh = M.face_height(pts)
    if not np.isfinite(fh) or fh <= 1e-4:
        return None
    left = pts[M.MOUTH["left"]]
    right = pts[M.MOUTH["right"]]
    up_in = pts[M.MOUTH["up_in"]]
    lo_in = pts[M.MOUTH["lo_in"]]
    width = float(np.linalg.norm(left - right))
    # lip centre-line y (midpoint of inner upper/lower lip); corners above it = raised
    centre_y = (float(up_in[1]) + float(lo_in[1])) / 2.0
    corner_y = (float(left[1]) + float(right[1])) / 2.0
    # image y grows downward, so "corner higher than centre" = corner_y < centre_y.
    raise_up = (centre_y - corner_y)
    val = (width + raise_up) / fh
    return round(float(val), 4) if np.isfinite(val) else None


def brow_eye_distance_raw(pts: np.ndarray) -> float | None:
    """Raw mean eyebrow-to-eye vertical distance, normalised by face height.

    Larger = brows raised (surprise-like movement, geometry only). Returns None if
    the brow landmarks coincide with the eye (degenerate / unreliable), so the
    engine can report ``brow_raise = None`` rather than a bogus number.
    """
    fh = M.face_height(pts)
    if not np.isfinite(fh) or fh <= 1e-4:
        return None
    try:
        lb = pts[LEFT_BROW]
        rb = pts[RIGHT_BROW]
    except (IndexError, TypeError):
        return None
    le_up = pts[M.LEFT_EYE["up1"]]
    re_up = pts[M.RIGHT_EYE["up1"]]
    dl = abs(float(lb[1]) - float(le_up[1]))
    dr = abs(float(rb[1]) - float(re_up[1]))
    if dl < 1e-4 and dr < 1e-4:
        return None  # brow coincides with eyelid -> unreliable
    val = ((dl + dr) / 2.0) / fh
    return round(float(val), 4) if np.isfinite(val) else None


def raw_expression(
    pts: np.ndarray,
    *,
    ear_open: float,
    ear_low: float,
    mar_rest: float,
    smile_rest: float | None = None,
    brow_rest: float | None = None,
) -> dict:
    """Per-frame expression numbers from landmarks, normalised to the baseline.

    All references come from the user's 5-second neutral calibration so a person
    with naturally narrow eyes / a wide resting mouth is not mislabelled. Each
    value is 0..1 or None. This is raw (pre-smoothing); the engine applies a short
    EMA and None-on-low-confidence. NO emotion labels.

    - eye_l/eye_r: per-eye EAR mapped via (ear_low=0 .. ear_open=1).
    - mouth_open: how far MAR exceeds the resting mouth, saturating ~2x resting.
    - smile: increase in the lip-corner spread/raise proxy vs resting.
    - brow_raise: increase in brow-eye distance vs resting, or None.
    """
    roll = M.head_roll_deg(pts)
    ear_l = M.roll_aligned_ear(pts, M.LEFT_EYE, roll)
    ear_r = M.roll_aligned_ear(pts, M.RIGHT_EYE, roll)
    mar = M.mouth_aspect_ratio(pts)

    eye_l = _eye_open_norm(ear_l, ear_open, ear_low)
    eye_r = _eye_open_norm(ear_r, ear_open, ear_low)

    # mouth_open: 0 at resting MAR, 1 when MAR has grown by one resting-MAR (i.e.
    # roughly doubled). rest<=0 -> fall back to an absolute small span.
    rest = mar_rest if (mar_rest and mar_rest > 1e-3) else 0.1
    mouth_open: float | None = round(_clamp01((mar - rest) / rest), 3)

    # smile: positive change in the geometry proxy vs resting. Without a resting
    # reference we cannot separate "smiling" from a naturally wide mouth, so None.
    smile: float | None = None
    s_now = smile_proxy_raw(pts)
    if s_now is not None and smile_rest is not None:
        # saturate at +50% of the resting proxy (a broad grin); tuneable.
        span = max(1e-4, 0.5 * abs(smile_rest) if smile_rest else 0.5 * s_now)
        smile = round(_clamp01((s_now - smile_rest) / span), 3)

    brow_raise: float | None = None
    b_now = brow_eye_distance_raw(pts)
    if b_now is not None and brow_rest is not None and brow_rest > 1e-4:
        # saturate at +40% of resting brow-eye distance (brows fully up).
        span = max(1e-4, 0.4 * brow_rest)
        brow_raise = round(_clamp01((b_now - brow_rest) / span), 3)

    return {
        "eye_l": eye_l,
        "eye_r": eye_r,
        "mouth_open": mouth_open,
        "smile": smile,
        "brow_raise": brow_raise,
    }
