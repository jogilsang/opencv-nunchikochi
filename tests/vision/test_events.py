"""V3 behaviour state machine — synthetic, deterministic, no model/image.

Drives BehaviorStateMachine with scripted metric sequences and asserts the
emitted Events (start/ongoing/end, type, confidence, count). One place per
behaviour: normal paths, exceptions (held-too-short, untrusted frames), and
error (corrupt restore). Also covers drink-unsupported and PERCLOS aggregate.
"""
from __future__ import annotations

import json

import pytest

from nunchi.vision.calibration import Baseline
from nunchi.vision.events import (
    SUPPORTED_BEHAVIORS,
    UNSUPPORTED_BEHAVIORS,
    BehaviorStateMachine,
    BehaviorThresholds,
)


def _baseline() -> Baseline:
    # open-eye EAR 0.30, resting MAR 0.10, face 100px, frontal pitch 0.50, roll 0.
    return Baseline(ear_open=0.30, ear_p10=0.24, mar_rest=0.10, face_px=100.0,
                    pitch_frontal=0.50, roll_zero=0.0, samples=30)


def _feed(sm: BehaviorStateMachine, bl, *, ear=None, mar=None, roll=None, pitch=None,
          face_scale=None, face_present=True, quality_ok=True, t=0.0):
    return sm.update(face_present=face_present, quality_ok=quality_ok, ear=ear, mar=mar,
                     roll=roll, pitch=pitch, face_scale=face_scale, baseline=bl, t=t)


# -- away ---------------------------------------------------------------------

def test_away_normal_start_and_end():
    """normal: face gone >= away_seconds -> away starts; return -> away ends."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, ear=0.30, t=0.0)                       # face present
    evs = _feed(sm, bl, face_present=False, quality_ok=False, t=1.0)
    assert evs == []                                     # only 1s gone < 3s
    evs = _feed(sm, bl, face_present=False, quality_ok=False, t=4.0)
    assert any(e.type == "away" and e.end is None for e in evs)   # away ongoing
    evs = _feed(sm, bl, ear=0.30, t=5.0)                 # face back
    ended = [e for e in evs if e.type == "away" and e.end is not None]
    assert ended and ended[0].count == 1 and ended[0].end == 5.0


def test_away_brief_drop_not_event():
    """exception: a single short face drop (< away_seconds) is not 'away'."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, ear=0.30, t=0.0)
    evs = _feed(sm, bl, face_present=False, quality_ok=False, t=1.0)
    evs += _feed(sm, bl, ear=0.30, t=1.6)
    assert all(e.type != "away" for e in evs)


# -- head_tilt ----------------------------------------------------------------

def test_head_tilt_normal_held():
    """normal: roll beyond enter for >= hold_s -> head_tilt ongoing with confidence."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, roll=20.0, t=0.0)                      # crosses enter(12) but not held
    evs = _feed(sm, bl, roll=20.0, t=1.2)                # held >= 1.0s
    tilt = [e for e in evs if e.type == "head_tilt"]
    assert tilt and tilt[0].end is None
    assert 0.0 < tilt[0].confidence <= 1.0


def test_head_tilt_exception_not_held_long_enough():
    """exception: roll crosses enter but releases before hold_s -> no event."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, roll=20.0, t=0.0)
    evs = _feed(sm, bl, roll=2.0, t=0.4)                 # back under exit quickly
    assert all(e.type != "head_tilt" for e in evs)


def test_head_tilt_hysteresis_exit_ends_interval():
    """normal: once held, dropping below exit ends the interval (count increments)."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, roll=20.0, t=0.0)
    _feed(sm, bl, roll=20.0, t=1.2)                      # ongoing
    evs = _feed(sm, bl, roll=1.0, t=2.0)                 # below exit(8) -> end
    ended = [e for e in evs if e.type == "head_tilt" and e.end is not None]
    assert ended and ended[0].count == 1


# -- forward_head -------------------------------------------------------------

def test_forward_head_normal_scale():
    """normal: face_scale past enter, held -> forward_head ongoing."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, face_scale=1.25, pitch=0.50, t=0.0)
    evs = _feed(sm, bl, face_scale=1.25, pitch=0.50, t=1.6)  # held >= 1.5s
    fwd = [e for e in evs if e.type == "forward_head"]
    assert fwd and fwd[0].end is None and fwd[0].confidence > 0.0


def test_forward_head_pitch_path():
    """normal: chin-down pitch delta past enter, held -> forward_head."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    # pitch 0.50 baseline, +0.07 delta > fwd_pitch_enter 0.06
    _feed(sm, bl, face_scale=1.0, pitch=0.57, t=0.0)
    evs = _feed(sm, bl, face_scale=1.0, pitch=0.57, t=1.6)
    assert any(e.type == "forward_head" for e in evs)


# -- blink / deep_blink -------------------------------------------------------

def test_blink_normal_single_frame_closure():
    """normal: EAR drops below blink_frac*ear_open then reopens -> a blink interval."""
    sm = BehaviorStateMachine()
    bl = _baseline()                                     # ear_open 0.30, frac 0.70 -> 0.21
    _feed(sm, bl, ear=0.30, t=0.0)                       # open
    _feed(sm, bl, ear=0.12, t=0.4)                       # closed (ongoing)
    evs = _feed(sm, bl, ear=0.30, t=0.8)                 # reopen -> close interval
    ended = [e for e in evs if e.type in ("blink", "deep_blink") and e.end is not None]
    assert ended and ended[0].count == 1
    assert 0.0 < ended[0].confidence <= 1.0


def test_deep_blink_sustained_closure():
    """normal: a long/deep closure classifies as deep_blink (drowsiness)."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, ear=0.30, t=0.0)
    _feed(sm, bl, ear=0.08, t=0.5)                       # deep (< 0.45*0.30=0.135)
    evs = _feed(sm, bl, ear=0.08, t=1.4)                 # held > 0.7s -> deep ongoing
    deep = [e for e in evs if e.type == "deep_blink"]
    assert deep and deep[0].end is None


def test_blink_exception_eyes_open_no_event():
    """exception: EAR stays open -> no blink events, PERCLOS fraction 0."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    for i in range(5):
        evs = _feed(sm, bl, ear=0.30, t=i * 0.4)
        assert all(e.type not in ("blink", "deep_blink") for e in evs)
    assert sm.eyes_closed_fraction() == 0.0


def test_perclos_fraction_counts_closed_frames():
    """normal: eyes_closed_fraction reflects closed/evaluated ratio (PERCLOS-like)."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, ear=0.30, t=0.0)                       # open
    _feed(sm, bl, ear=0.10, t=0.4)                       # closed
    _feed(sm, bl, ear=0.10, t=0.8)                       # closed
    _feed(sm, bl, ear=0.30, t=1.2)                       # open
    assert sm.frames_eval == 4
    assert abs(sm.eyes_closed_fraction() - 0.5) < 1e-6


# -- yawn ---------------------------------------------------------------------

def test_yawn_normal_held():
    """normal: MAR above yawn_mult*mar_rest, held -> yawn ongoing."""
    sm = BehaviorStateMachine()
    bl = _baseline()                                     # mar_rest 0.10, mult 1.8 -> 0.18
    _feed(sm, bl, mar=0.25, t=0.0)
    evs = _feed(sm, bl, mar=0.25, t=1.3)                 # held >= 1.2s
    yawn = [e for e in evs if e.type == "yawn"]
    assert yawn and yawn[0].end is None and yawn[0].confidence > 0.0


def test_yawn_exception_brief_open_not_yawn():
    """exception: brief mouth open that closes fast is not a yawn."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, mar=0.25, t=0.0)
    evs = _feed(sm, bl, mar=0.10, t=0.3)                 # closed before hold
    assert all(e.type != "yawn" for e in evs)


# -- quality / boludo gating --------------------------------------------------

def test_untrusted_frame_does_not_start_new_event():
    """exception: low-quality / no-baseline frame holds but does not confirm new events."""
    sm = BehaviorStateMachine()
    # no baseline -> shape behaviours suspended, only away can fire
    evs = sm.update(face_present=True, quality_ok=True, ear=0.05, mar=0.30, roll=30.0,
                    pitch=0.9, face_scale=1.5, baseline=None, t=0.0)
    assert all(e.type in ("away",) for e in evs) or evs == []


def test_untrusted_reemits_ongoing_without_confirm():
    """normal: an ongoing tilt is re-surfaced (held) on a bad-quality frame."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, roll=20.0, t=0.0)
    _feed(sm, bl, roll=20.0, t=1.2)                      # tilt ongoing
    evs = sm.update(face_present=True, quality_ok=False, ear=None, mar=None, roll=None,
                    pitch=None, face_scale=None, baseline=bl, t=2.0)
    assert any(e.type == "head_tilt" and e.end is None for e in evs)


# -- drink unsupported --------------------------------------------------------

# -- drink: supported from V7 but needs the palm signal ----------------------

def test_drink_not_emitted_without_hand_signal():
    """V7: drink is supported, but with no palm signal (hand_mouth_dist None) it
    never fires — so sessions without the palm model behave as before."""
    assert "drink" in SUPPORTED_BEHAVIORS
    assert UNSUPPORTED_BEHAVIORS == ()
    sm = BehaviorStateMachine()
    bl = _baseline()
    seen = []
    for i in range(6):
        seen += _feed(sm, bl, ear=0.30, mar=0.30, t=i * 0.4)   # no hand_mouth_dist
    assert all(e.type != "drink" for e in seen)


def test_drink_normal_hand_held_near_mouth():
    """normal: palm held near the mouth past the hold time -> drink ongoing."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    sm.update(face_present=True, quality_ok=True, ear=0.30, mar=0.10, roll=0.0,
              pitch=0.5, face_scale=1.0, baseline=bl, t=0.0, hand_mouth_dist=0.6)
    evs = sm.update(face_present=True, quality_ok=True, ear=0.30, mar=0.10, roll=0.0,
                    pitch=0.5, face_scale=1.0, baseline=bl, t=1.4, hand_mouth_dist=0.6)
    drink = [e for e in evs if e.type == "drink"]
    assert drink and drink[0].end is None and 0.0 < drink[0].confidence <= 1.0


def test_drink_exception_brief_pass_not_drink():
    """exception: a hand passing the mouth briefly (< hold) is not a drink."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    sm.update(face_present=True, quality_ok=True, ear=0.30, mar=0.10, roll=0.0,
              pitch=0.5, face_scale=1.0, baseline=bl, t=0.0, hand_mouth_dist=0.6)
    evs = sm.update(face_present=True, quality_ok=True, ear=0.30, mar=0.10, roll=0.0,
                    pitch=0.5, face_scale=1.0, baseline=bl, t=0.3, hand_mouth_dist=2.0)
    assert all(e.type != "drink" for e in evs)


# -- serialisation / error ----------------------------------------------------

def test_state_machine_roundtrip_identical():
    """normal: to_dict/from_dict preserves tracks, latches, aggregates."""
    sm = BehaviorStateMachine()
    bl = _baseline()
    _feed(sm, bl, roll=20.0, t=0.0)
    _feed(sm, bl, roll=20.0, t=1.2)
    _feed(sm, bl, ear=0.10, t=1.6)
    blob = json.dumps(sm.to_dict())
    sm2 = BehaviorStateMachine.from_dict(json.loads(blob))
    assert sm2.to_dict() == json.loads(blob)
    assert sm2.frames_eval == sm.frames_eval


def test_from_dict_corrupt_raises_value_error():
    """error: a corrupt / missing-schema blob raises ValueError (not KeyError)."""
    with pytest.raises(ValueError):
        BehaviorStateMachine.from_dict({"schema": "1.0"})      # missing 'th'
    with pytest.raises(ValueError):
        BehaviorStateMachine.from_dict("not-a-dict")           # type: ignore[arg-type]


def test_thresholds_from_dict_ignores_unknown_keys():
    """error-tolerance: unknown keys in a thresholds blob are ignored, not fatal."""
    th = BehaviorThresholds.from_dict({"away_seconds": 2.0, "bogus": 99})
    assert th.away_seconds == 2.0
