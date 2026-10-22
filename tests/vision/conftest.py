"""Fixtures for vision tests: public sample images + a ready VisionEngine.

Images are public OpenCV samples (face and non-face). They are allowed under the
no-persist rule (test/eval exception) and cached under tests/vision/_samples/.
If the network is unavailable, face tests are skipped (not failed) and synthetic
frames are used for logic/exception tests.
"""
from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "_samples"
REPO = HERE.parents[1]  # opencv_nunchikochi/
MODELS = REPO / "models"

# (name, url, has_face). Public OpenCV sample data + YuNet demo selfie.
_SAMPLE_SPECS = [
    ("lena.jpg", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/lena.jpg", True),
    ("messi5.jpg", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/messi5.jpg", True),
    ("largest_selfie.jpg", "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/example_outputs/largest_selfie.jpg", True),
    ("basketball1.png", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/basketball1.png", True),
    ("graf1.png", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/graf1.png", False),
    ("fruits.jpg", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/fruits.jpg", False),
    ("baboon.jpg", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/baboon.jpg", False),
    ("box.png", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/box.png", False),
    ("building.jpg", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/building.jpg", False),
    ("butterfly.jpg", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/butterfly.jpg", False),
    ("apple.jpg", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/apple.jpg", False),
    ("board.jpg", "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/board.jpg", False),
]


def _fetch(name: str, url: str) -> Path | None:
    dest = SAMPLES / name
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    SAMPLES.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "nunchikochi-test/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if not data:
            return None
        dest.write_bytes(data)
        return dest
    except (urllib.error.URLError, OSError):
        return None


@pytest.fixture(scope="session")
def sample_images() -> list[tuple[str, Path, bool]]:
    """Returns [(name, path, has_face)] for successfully fetched samples."""
    out = []
    for name, url, has_face in _SAMPLE_SPECS:
        p = _fetch(name, url)
        if p is not None:
            out.append((name, p, has_face))
    return out


@pytest.fixture(scope="session")
def model_available() -> bool:
    return ((MODELS / "face_detection_yunet_2023mar.onnx").exists()
            and (MODELS / "face_landmarks_mediapipe_2023.onnx").exists())


@pytest.fixture()
def engine(model_available):
    if not model_available:
        pytest.skip("models not downloaded (run models/download_models.py)")
    from nunchi.vision import VisionEngine
    return VisionEngine(str(MODELS))


def synthetic_frame(w: int = 320, h: int = 240, value: int = 127) -> np.ndarray:
    """A flat BGR frame with no face — for logic/exception tests without network."""
    return np.full((h, w, 3), value, dtype=np.uint8)


def read_bgr(path: Path) -> np.ndarray:
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert img is not None, f"failed to read sample {path}"
    return img


def rotate(img: np.ndarray, deg: float) -> np.ndarray:
    """Rotate about centre (for roll synthetic tests)."""
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, m, (w, h), borderValue=(127, 127, 127))


def scale(img: np.ndarray, factor: float) -> np.ndarray:
    """Uniformly scale the whole image (for face_scale synthetic tests)."""
    return cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
