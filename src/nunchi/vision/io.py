"""Frame decode helpers for the vision tab.

Privacy rule (docs/RULES.md): image bytes must never be persisted. ``decode_jpeg``
decodes into an ndarray, optionally downscales so the longest side <= ``max_side``,
and the caller is expected to let the decoded array go out of scope after use. The
input ``bytes`` object is not retained by this module.
"""
from __future__ import annotations

import cv2
import numpy as np


class DecodeError(ValueError):
    """Raised when JPEG/image bytes cannot be decoded into an image."""


def decode_jpeg(data: bytes, max_side: int = 640) -> np.ndarray:
    """Decode encoded image ``bytes`` (JPEG/PNG) to a BGR ndarray, longest side <= ``max_side``.

    The original ``data`` bytes are only read here and never stored. Raises
    ``DecodeError`` on empty/invalid input so the service can convert it to a
    user-facing quality issue rather than a 500.
    """
    if not data:
        raise DecodeError("empty image payload")
    buf = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise DecodeError("could not decode image bytes (not a valid JPEG/PNG)")
    img = _downscale(img, max_side)
    return img


def _downscale(img: np.ndarray, max_side: int) -> np.ndarray:
    if max_side <= 0:
        return img
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return img
    scale = max_side / float(longest)
    new_w = max(1, round(w * scale))
    new_h = max(1, round(h * scale))
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
