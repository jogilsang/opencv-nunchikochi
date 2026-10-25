"""V7 palm detection + drink wiring.

Pure/anchor tests need no model. Model-dependent tests (real palm ONNX) skip if
absent — mirroring the engine's optional-model behaviour. Includes a
false-positive sanity check (a far hand must not read as near-mouth).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nunchi.vision.hands import (
    Palm,
    PalmDetector,
    _anchors,
    hand_mouth_distance,
    hand_mouth_signal,
)

MODELS = Path(__file__).resolve().parents[2] / "models"
PALM = MODELS / "palm_detection_mediapipe_2023feb.onnx"


# -- anchors (pure) -----------------------------------------------------------

def test_anchor_count_and_range():
    """normal: exactly 2016 anchors, all centres in 0..1 (matches the model)."""
    a = _anchors()
    assert a.shape == (2016, 2)
    assert float(a.min()) >= 0.0 and float(a.max()) <= 1.0


def test_anchor_grid_structure():
    """normal: first grid is 24x24x2 (=1152), second 12x12x6 (=864)."""
    a = _anchors()
    # first anchor is cell (0,0) of the 24-grid -> 0.5/24
    assert a[0][0] == pytest.approx(0.5 / 24, abs=1e-5)
    # the 1153rd anchor starts the 12-grid -> 0.5/12
    assert a[1152][0] == pytest.approx(0.5 / 12, abs=1e-5)


# -- hand_mouth_distance (pure) ----------------------------------------------

def test_hand_mouth_distance_near_vs_far():
    """normal: a palm near the mouth gives a small normalised distance; far large."""
    mouth = (100.0, 100.0)
    near = [Palm(cx=110, cy=110, w=40, h=40, score=0.9)]
    far = [Palm(cx=400, cy=400, w=40, h=40, score=0.9)]
    dn = hand_mouth_distance(near, mouth, face_px=100.0)
    df = hand_mouth_distance(far, mouth, face_px=100.0)
    assert dn is not None and df is not None and dn < df
    assert dn < 0.3   # ~14px / 100px


def test_hand_mouth_distance_none_without_palm():
    """exception: no palm or no face scale -> None (contract stays None)."""
    assert hand_mouth_distance([], (0, 0), face_px=100.0) is None
    assert hand_mouth_distance([Palm(0, 0, 10, 10, 0.9)], (0, 0), face_px=0.0) is None


def test_hand_mouth_distance_picks_closest():
    """normal: with several palms, the closest one wins."""
    mouth = (100.0, 100.0)
    palms = [Palm(300, 300, 40, 40, 0.9), Palm(120, 100, 40, 40, 0.9)]
    d = hand_mouth_distance(palms, mouth, face_px=100.0)
    assert d == pytest.approx(20.0 / 100.0, abs=1e-6)


# -- hand_mouth_signal (pure, V12: distance + signed vertical offset) ---------

def test_hand_mouth_signal_sign_above_vs_below():
    """normal: dy is negative when the palm is ABOVE the mouth (drink) and
    positive when BELOW (keyboard/chin-rest)."""
    mouth = (100.0, 100.0)
    above = hand_mouth_signal([Palm(100, 80, 40, 40, 0.9)], mouth, face_px=100.0)
    below = hand_mouth_signal([Palm(100, 150, 40, 40, 0.9)], mouth, face_px=100.0)
    assert above is not None and below is not None
    assert above.dy == pytest.approx(-0.20, abs=1e-6)   # 20px above / 100px
    assert below.dy == pytest.approx(0.50, abs=1e-6)    # 50px below / 100px
    assert above.dist > 0 and below.dist > 0


def test_hand_mouth_signal_dist_matches_distance_helper():
    """normal: the signal's dist equals the standalone distance helper (same palm
    choice), so the contract field is unchanged."""
    mouth = (100.0, 100.0)
    palms = [Palm(300, 300, 40, 40, 0.9), Palm(120, 100, 40, 40, 0.9)]
    sig = hand_mouth_signal(palms, mouth, face_px=100.0)
    assert sig is not None
    assert sig.dist == pytest.approx(hand_mouth_distance(palms, mouth, 100.0), abs=1e-9)


def test_hand_mouth_signal_none_without_palm():
    """exception: no palm or no face scale -> None (same as the distance helper)."""
    assert hand_mouth_signal([], (0, 0), face_px=100.0) is None
    assert hand_mouth_signal([Palm(0, 0, 10, 10, 0.9)], (0, 0), face_px=0.0) is None


# -- detector availability ----------------------------------------------------

def test_detector_missing_model_is_unavailable(tmp_path: Path):
    """error: pointing at a dir with no palm model -> available False, detect []."""
    det = PalmDetector(tmp_path)
    assert det.available is False
    assert det.detect(np.full((240, 320, 3), 127, np.uint8)) == []


# -- model-dependent ----------------------------------------------------------

@pytest.mark.skipif(not PALM.exists(), reason="palm model not downloaded")
def test_detector_loads_and_runs_on_blank():
    """normal: real model loads via cv2.dnn and returns a (possibly empty) list
    without crashing on a blank frame (no hand -> likely [])."""
    det = PalmDetector(MODELS)
    assert det.available is True
    out = det.detect(np.full((240, 320, 3), 127, np.uint8))
    assert isinstance(out, list)
    for p in out:
        assert isinstance(p, Palm) and p.w > 0 and p.h > 0


@pytest.mark.skipif(not PALM.exists(), reason="palm model not downloaded")
def test_engine_drink_supported_and_metric_type(sample_images):
    """normal (engine): with the palm model present, drink is supported and
    analyze fills hand_mouth_dist as None-or-float without crashing."""
    import cv2

    from nunchi.vision import VisionEngine
    face = next(((n, p) for (n, p, hf) in sample_images if hf), None)
    if face is None:
        pytest.skip("no public face sample (offline?)")
    eng = VisionEngine(str(MODELS))
    assert eng.drink_supported is True
    img = cv2.imread(str(face[1]))
    st = eng.new_session("drink")
    for i in range(20):
        eng.calibrate(st, img, t=i * 0.3)
    r = eng.analyze(st, img, t=6.0)
    assert r.metrics.hand_mouth_dist is None or isinstance(r.metrics.hand_mouth_dist, float)
    # variants must never fabricate drink events
    rv = eng.analyze_variant(st, img, t=6.0, variant="zoom_face")
    assert all(e.type != "drink" for e in rv.events)
