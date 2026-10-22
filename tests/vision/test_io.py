"""Tests for nunchi.vision.io.decode_jpeg (behaviour, not implementation)."""
from __future__ import annotations

import cv2
import numpy as np
import pytest

from nunchi.vision.io import DecodeError, decode_jpeg


def _encode(img: np.ndarray, ext: str = ".jpg") -> bytes:
    ok, buf = cv2.imencode(ext, img)
    assert ok
    return buf.tobytes()


# -- normal 1: decodes a valid JPEG to a BGR ndarray --------------------------
def test_decode_jpeg_returns_bgr_ndarray():
    img = np.full((100, 120, 3), 90, np.uint8)
    out = decode_jpeg(_encode(img))
    assert isinstance(out, np.ndarray)
    assert out.ndim == 3 and out.shape[2] == 3


# -- normal 2: downscales so the longest side <= max_side ---------------------
def test_decode_jpeg_downscales_to_max_side():
    big = np.full((900, 1600, 3), 120, np.uint8)
    out = decode_jpeg(_encode(big, ".png"), max_side=640)
    assert max(out.shape[:2]) == 640
    # aspect ratio roughly preserved (1600:900 -> 640:360)
    assert out.shape[0] == 360


# -- normal 3: small image is left untouched (no upscaling) -------------------
def test_decode_jpeg_small_image_not_upscaled():
    small = np.full((48, 64, 3), 200, np.uint8)
    out = decode_jpeg(_encode(small), max_side=640)
    assert out.shape[:2] == (48, 64)


# -- exception 1: empty payload -> DecodeError --------------------------------
def test_decode_jpeg_empty_raises():
    with pytest.raises(DecodeError):
        decode_jpeg(b"")


# -- exception 2: garbage bytes -> DecodeError --------------------------------
def test_decode_jpeg_garbage_raises():
    with pytest.raises(DecodeError):
        decode_jpeg(b"not-an-image-\x00\x01\x02")


# -- error/edge: max_side <= 0 disables downscaling (no crash) ----------------
def test_decode_jpeg_max_side_zero_keeps_original():
    img = np.full((500, 800, 3), 10, np.uint8)
    out = decode_jpeg(_encode(img), max_side=0)
    assert out.shape[:2] == (500, 800)
