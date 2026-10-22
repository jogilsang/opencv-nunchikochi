"""Image enhancement for the `enhance` analyze variant (active perception).

CLAHE (contrast-limited adaptive histogram equalisation) on the luma channel plus
gamma correction, so a too-dark / low-contrast frame becomes analysable before the
agent asks the user to fix lighting. OpenCV only. Returns a new BGR array; the
input is not mutated or stored.
"""
from __future__ import annotations

import cv2
import numpy as np


def auto_gamma(mean_luma: float, target: float = 130.0) -> float:
    """Gamma ``g`` s.t. applying ``out = in**g`` nudges mean luma toward ``target``.

    For a dark frame (mean < target) this returns g < 1 (brightening). Clamped to
    a sane range. Apply as ``(pixel/255)**g * 255``.
    """
    m = max(1.0, min(254.0, mean_luma))
    g = float(np.log(target / 255.0) / np.log(m / 255.0))
    return float(min(2.5, max(0.3, g)))


def enhance_bgr(frame_bgr: np.ndarray, *, clip_limit: float = 2.5, tiles: int = 8) -> np.ndarray:
    """Auto gamma (brighten, from original luma) then CLAHE on L (contrast).

    Gamma is applied first, using the ORIGINAL mean luma, so a dark frame is
    actually brightened before CLAHE equalises local contrast. (CLAHE alone can
    lower mean brightness.) Brightens/sharpens contrast for detection.
    """
    gray0 = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    g = auto_gamma(float(gray0.mean()))
    out = frame_bgr
    if abs(g - 1.0) > 1e-3:
        lut = np.array([((i / 255.0) ** g) * 255 for i in range(256)], dtype=np.uint8)
        out = cv2.LUT(out, lut)

    lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tiles, tiles))
    l2 = clahe.apply(l)
    return cv2.cvtColor(cv2.merge((l2, a, b)), cv2.COLOR_LAB2BGR)
