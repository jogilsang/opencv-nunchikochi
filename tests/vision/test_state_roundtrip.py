"""Lambda-restore equivalence: save SessionState mid-stream, restore in a fresh
engine, and verify the continued output is identical to uninterrupted processing.
Also checks JSON size <= 8KB and schema version.
"""
from __future__ import annotations

import json

import pytest

from nunchi.vision import SessionState, VisionEngine

from .conftest import read_bgr, rotate, scale


def _frames(sample_images):
    face = next(((n, p) for (n, p, hf) in sample_images if hf), None)
    if face is None:
        pytest.skip("no public face sample available (offline?)")
    img = read_bgr(face[1])
    # a short deterministic sequence that exercises filters: tilt + scale changes
    return [img, rotate(img, 5), rotate(img, -5), scale(img, 0.8), img, rotate(img, 8)]


def _result_tuple(r):
    m = r.metrics
    return (r.face_present, r.calibrated,
            m.ear, m.mar, m.head_roll_deg, m.head_pitch_proxy, m.face_scale)


# -- normal 1: save after calibration + a few frames, restore, continue same --
def test_state_roundtrip_identical_output(engine: VisionEngine, sample_images):
    frames = _frames(sample_images)

    # A) uninterrupted
    stA = engine.new_session("rt")
    for i in range(20):
        engine.calibrate(stA, frames[0], t=i * 0.3)
    outA = [_result_tuple(engine.analyze(stA, f, t=10 + i)) for i, f in enumerate(frames)]

    # B) interrupt midway: process first 3 frames, serialise, restore, continue
    stB = engine.new_session("rt")
    for i in range(20):
        engine.calibrate(stB, frames[0], t=i * 0.3)
    outB = []
    for i, f in enumerate(frames[:3]):
        outB.append(_result_tuple(engine.analyze(stB, f, t=10 + i)))
    blob = json.dumps(stB.to_dict())
    engine2 = VisionEngine("models")                # a different engine instance
    stB2 = SessionState.from_dict(json.loads(blob))
    for i, f in enumerate(frames[3:], start=3):
        outB.append(_result_tuple(engine2.analyze(stB2, f, t=10 + i)))

    assert outB == outA  # restored stream is identical to the uninterrupted one


# -- normal 2: serialised state is <= 8KB and carries a schema version --------
def test_state_blob_small_and_versioned(engine: VisionEngine, sample_images):
    frames = _frames(sample_images)
    st = engine.new_session("sz")
    for i in range(20):
        engine.calibrate(st, frames[0], t=i * 0.3)
    for i, f in enumerate(frames):
        engine.analyze(st, f, t=10 + i)
    d = st.to_dict()
    assert d["schema"]  # version present
    assert len(json.dumps(d).encode("utf-8")) <= 8192


# -- normal 3: round-trip preserves calibration/baseline ----------------------
def test_roundtrip_preserves_baseline(engine: VisionEngine, sample_images):
    frames = _frames(sample_images)
    st = engine.new_session("bl")
    for i in range(20):
        engine.calibrate(st, frames[0], t=i * 0.3)
    assert st.calibrated
    st2 = SessionState.from_dict(json.loads(json.dumps(st.to_dict())))
    assert st2.calibrated is True
    assert st2.baseline is not None
    assert st2.baseline.face_px == st.baseline.face_px
    assert st2.baseline_face_px == st.baseline_face_px


# -- exception 1: mid-calibration save/restore continues calibration ----------
def test_roundtrip_mid_calibration(engine: VisionEngine, sample_images):
    frames = _frames(sample_images)
    st = engine.new_session("midcal")
    # feed only part of the calibration window
    for i in range(5):
        engine.calibrate(st, frames[0], t=i * 0.3)
    assert st.calibrated is False
    st2 = SessionState.from_dict(json.loads(json.dumps(st.to_dict())))
    engine2 = VisionEngine("models")
    res = None
    for i in range(5, 25):
        res = engine2.calibrate(st2, frames[0], t=i * 0.3)
    assert res.done is True and st2.calibrated is True  # calibration resumed and finished


# -- exception 2: from_dict on minimal/new-session blob is valid --------------
def test_from_dict_new_session_blob(engine: VisionEngine):
    st = engine.new_session("fresh")
    st2 = SessionState.from_dict(json.loads(json.dumps(st.to_dict())))
    assert st2.session_id == "fresh"
    assert st2.calibrated is False and st2.baseline is None


# -- error/edge: corrupt/partial dict missing optional keys doesn't crash -----
def test_from_dict_tolerates_missing_optional(engine: VisionEngine):
    minimal = {"session_id": "x", "calibrator": None, "filters": {}}
    st = SessionState.from_dict(minimal)
    assert st.session_id == "x"
    assert st.baseline is None and st.calibrated is False


# -- error: pre-V10 blobs (schema 1.0 / 2.0) are rejected ---------------------
# V6 bumped schema to 2.0 (roll-aligned EAR); V10 bumped to 3.0 (head-pose
# baseline). An older persisted blob lacks the current reference, so from_dict
# must reject it (the session re-calibrates).
def test_from_dict_rejects_old_schema(engine: VisionEngine, sample_images):
    import pytest
    frames = _frames(sample_images)
    st = engine.new_session("oldv")
    for i in range(20):
        engine.calibrate(st, frames[0], t=i * 0.3)
    d = st.to_dict()
    assert d["schema"] == "3.0"                 # V10 current schema
    for old in ("1.0", "2.0"):                  # every pre-V10 schema is rejected
        stale = dict(d)
        stale["schema"] = old
        with pytest.raises(ValueError):
            SessionState.from_dict(stale)
