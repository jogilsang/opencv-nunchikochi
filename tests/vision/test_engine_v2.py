"""V2 integration tests: calibrate -> analyze, metrics via real FaceMesh model.

Uses a public face sample. Synthetic transforms (rotate -> roll, scale ->
face_scale) verify metric direction end-to-end through the engine.
"""
from __future__ import annotations

import pytest

from nunchi.vision import VisionEngine

from .conftest import read_bgr, rotate, scale, synthetic_frame


def _face_sample(sample_images):
    face = next(((n, p) for (n, p, hf) in sample_images if hf), None)
    if face is None:
        pytest.skip("no public face sample available (offline?)")
    return read_bgr(face[1])


# -- normal 1: calibration completes and analyze then fills all metrics -------
def test_calibrate_then_analyze_fills_metrics(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("s-cal")
    res = None
    for i in range(20):
        res = engine.calibrate(st, img, t=i * 0.3)
    assert res.done is True and st.calibrated is True
    assert st.baseline is not None and st.baseline.face_px > 0

    r = engine.analyze(st, img, t=6.0)
    assert r.face_present is True
    assert r.calibrated is True
    assert r.metrics.ear is not None and r.metrics.ear > 0
    assert r.metrics.mar is not None
    assert r.metrics.head_roll_deg is not None
    assert r.metrics.head_pitch_proxy is not None
    # same frame as calibration -> scale ~1
    assert r.metrics.face_scale is not None
    assert 0.8 <= r.metrics.face_scale <= 1.2


# -- normal 2: rotating the frame changes head_roll_deg -----------------------
def test_rotation_changes_roll(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    s0 = engine.new_session("r0")
    r0 = engine.analyze(s0, img, t=0.0)
    s1 = engine.new_session("r1")
    r1 = engine.analyze(s1, rotate(img, 12), t=0.0)
    assert r0.metrics.head_roll_deg is not None and r1.metrics.head_roll_deg is not None
    # a 12-degree image rotation must move roll by a clear margin
    assert abs(r1.metrics.head_roll_deg - r0.metrics.head_roll_deg) > 5.0


# -- normal 3: scaling the frame changes face_scale in the right direction ----
def test_scale_changes_face_scale(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("s-scale")
    for i in range(20):
        engine.calibrate(st, img, t=i * 0.3)       # baseline at full size
    assert st.calibrated
    r_small = engine.analyze(st, scale(img, 0.6), t=6.0)
    assert r_small.metrics.face_scale is not None
    assert r_small.metrics.face_scale < 0.9        # smaller face -> <1


# -- exception 1: analyze on a no-face frame returns a valid empty result -----
def test_analyze_no_face(engine: VisionEngine):
    st = engine.new_session("s-noface")
    r = engine.analyze(st, synthetic_frame(value=127), t=0.0)
    assert r.face_present is False
    assert r.persons == 0
    assert r.metrics.ear is None          # no landmarks -> no metrics
    assert r.quality.ok is False


# -- exception 2: calibrate on a no-face frame is rejected, stays uncalibrated-
def test_calibrate_no_face_rejected(engine: VisionEngine):
    st = engine.new_session("s-calnoface")
    res = None
    for i in range(20):
        res = engine.calibrate(st, synthetic_frame(value=127), t=i * 0.3)
    assert st.calibrated is False
    assert res.done is False
    assert res.ok_frame is False


# -- error/edge: face_scale stays None before calibration ---------------------
def test_face_scale_none_before_calibration(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("s-precal")
    r = engine.analyze(st, img, t=0.0)
    assert r.face_present is True
    assert r.metrics.face_scale is None   # no baseline yet
    assert r.metrics.ear is not None      # but EAR/roll still measured
