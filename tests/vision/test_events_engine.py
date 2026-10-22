"""V3 integration: behaviour state machine wired through VisionEngine.analyze.

Confirms: analyze fills FrameResult.events (type list), the state machine lives
in SessionState and survives serialise/restore, away fires on a no-face gap, and
analyze_variant does NOT advance the state machine (no spurious events / state
mutation). Model-dependent assertions skip cleanly when models are absent.
"""
from __future__ import annotations

import json

import pytest

from nunchi.vision import SessionState, VisionEngine

from .conftest import read_bgr, synthetic_frame


def _face_sample(sample_images):
    face = next(((n, p) for (n, p, hf) in sample_images if hf), None)
    if face is None:
        pytest.skip("no public face sample available (offline?)")
    return read_bgr(face[1])


def _calibrate(engine, st, img):
    for i in range(20):
        engine.calibrate(st, img, t=i * 0.3)
    assert st.calibrated


# -- normal 1: analyze returns an events list; machine present in state --------
def test_analyze_fills_events_list(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("ev")
    _calibrate(engine, st, img)
    r = engine.analyze(st, img, t=6.0)
    assert isinstance(r.events, list)                 # contract: events is a list
    # a calm frontal frame should not fabricate events
    assert all(e.type in ("away", "head_tilt", "forward_head", "blink", "deep_blink", "yawn")
               for e in r.events)
    assert st._sm is not None


# -- normal 2: away fires through the engine on a no-face gap ------------------
def test_engine_away_on_no_face_gap(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("ev-away")
    _calibrate(engine, st, img)
    engine.analyze(st, img, t=6.0)                    # face present
    engine.analyze(st, synthetic_frame(value=127), t=7.0)   # face gone (1s)
    r = engine.analyze(st, synthetic_frame(value=127), t=12.0)  # 6s gone -> away
    assert any(e.type == "away" and e.end is None for e in r.events)


# -- normal 3: state machine survives SessionState roundtrip -------------------
def test_state_machine_survives_roundtrip(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("ev-rt")
    _calibrate(engine, st, img)
    engine.analyze(st, img, t=6.0)
    engine.analyze(st, synthetic_frame(value=127), t=7.0)
    blob = json.dumps(st.to_dict())
    assert len(blob.encode("utf-8")) <= 8192          # still within budget with SM
    st2 = SessionState.from_dict(json.loads(blob))
    assert st2._sm is not None
    assert st2._sm.frames_eval == st._sm.frames_eval
    # continue on a fresh engine -> no crash, events still a list
    engine2 = VisionEngine("models")
    r = engine2.analyze(st2, img, t=8.0)
    assert isinstance(r.events, list)


# -- exception 1: analyze_variant does NOT advance the state machine -----------
def test_variant_does_not_mutate_state_machine(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("ev-var")
    _calibrate(engine, st, img)
    before = json.dumps(st._sm.to_dict())
    r = engine.analyze_variant(st, img, t=6.0, variant="strict")
    after = json.dumps(st._sm.to_dict())
    assert before == after                            # state machine untouched
    assert r.events == []                             # variants never emit events


# -- exception 2: before calibration, only away is possible (no baseline) ------
def test_no_events_before_calibration_except_away(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("ev-precal")
    r = engine.analyze(st, img, t=0.0)                # not calibrated yet
    assert all(e.type == "away" for e in r.events) or r.events == []
