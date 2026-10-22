"""Tests for 5-second frontal calibration (synthetic landmarks, no model/image)."""
from __future__ import annotations

from nunchi.vision.calibration import Calibrator

from .test_metrics import _base_pts


# -- normal 1: completes after the window with enough good frames -------------
def test_calibration_completes():
    cal = Calibrator(seconds=5.0, min_samples=5)
    pts = _base_pts()
    res = None
    for i in range(20):
        res = cal.feed(pts, quality_ok=True, quality_reason="", t=i * 0.3)
    assert res.done is True
    assert res.baseline is not None
    assert res.baseline.samples >= 5
    assert res.baseline.ear_open > 0
    assert res.baseline.face_px > 0


# -- normal 2: progress grows monotonically before completion -----------------
def test_calibration_progress_grows():
    cal = Calibrator(seconds=5.0, min_samples=5)
    pts = _base_pts()
    p0 = cal.feed(pts, True, "", t=0.0).progress
    p1 = cal.feed(pts, True, "", t=1.0).progress
    p2 = cal.feed(pts, True, "", t=2.0).progress
    assert 0.0 <= p0 <= p1 <= p2 < 1.0


# -- exception 1: no-face frames are rejected (retryable), no completion ------
def test_calibration_rejects_no_face():
    cal = Calibrator(seconds=5.0, min_samples=5)
    for i in range(20):
        res = cal.feed(None, quality_ok=False, quality_reason="no_face", t=i * 0.3)
    assert res.done is False
    assert res.ok_frame is False
    assert res.reason == "no_face"


# -- exception 2: low-quality frames rejected even with landmarks -------------
def test_calibration_rejects_low_quality():
    cal = Calibrator(seconds=5.0, min_samples=5)
    pts = _base_pts()
    res = cal.feed(pts, quality_ok=False, quality_reason="too_dark", t=0.0)
    assert res.ok_frame is False
    assert res.reason == "too_dark"


# -- error/edge: not enough samples in-window -> not done yet -----------------
def test_calibration_insufficient_samples():
    cal = Calibrator(seconds=5.0, min_samples=50)  # require many
    pts = _base_pts()
    res = None
    for i in range(10):
        res = cal.feed(pts, True, "", t=i * 0.6)  # passes 5 s but only 10 samples
    assert res.done is False


# -- edge: reset clears accumulation ------------------------------------------
def test_calibration_reset():
    cal = Calibrator(seconds=5.0, min_samples=5)
    pts = _base_pts()
    for i in range(10):
        cal.feed(pts, True, "", t=i * 0.3)
    cal.reset()
    res = cal.feed(pts, True, "", t=0.0)
    assert res.progress == 0.0 and res.done is False
