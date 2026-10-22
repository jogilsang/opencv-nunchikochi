"""V11 head-pose runtime switch — NUNCHI_DISABLE_POSE.

Operators (and the cloud A/B) can turn head pose off at runtime without a redeploy
by setting NUNCHI_DISABLE_POSE=1. Default = pose ON. The switch only removes the
``overlay.pose`` block; the rest of analyze (quality/metrics/events/overlay points)
is unchanged. These tests pin the env parsing and the engine behaviour.
"""
from __future__ import annotations

import pytest

from nunchi.vision import VisionEngine
from nunchi.vision.engine import pose_disabled

from .conftest import read_bgr, synthetic_frame

_POSE_KEYS = {"yaw_deg", "pitch_deg", "roll_deg", "depth", "conf"}


def _face_sample(sample_images):
    face = next(((n, p) for (n, p, hf) in sample_images if hf), None)
    if face is None:
        pytest.skip("no public face sample available (offline?)")
    return read_bgr(face[1])


def _calibrate(engine, st, img, n=20):
    for i in range(n):
        engine.calibrate(st, img, t=i * 0.3)


# -- normal 1: default (env unset) -> pose present ----------------------------
def test_default_pose_on(engine: VisionEngine, sample_images, monkeypatch):
    monkeypatch.delenv("NUNCHI_DISABLE_POSE", raising=False)
    assert pose_disabled() is False
    img = _face_sample(sample_images)
    st = engine.new_session("sw-on")
    _calibrate(engine, st, img)
    r = engine.analyze(st, img, t=6.0)
    assert r.overlay is not None and "pose" in r.overlay
    assert set(r.overlay["pose"]) == _POSE_KEYS


# -- normal 2: NUNCHI_DISABLE_POSE=1 -> pose absent, rest intact ---------------
def test_disable_pose_removes_pose_only(engine: VisionEngine, sample_images, monkeypatch):
    monkeypatch.setenv("NUNCHI_DISABLE_POSE", "1")
    assert pose_disabled() is True
    img = _face_sample(sample_images)
    st = engine.new_session("sw-off")
    _calibrate(engine, st, img)
    r = engine.analyze(st, img, t=6.0)
    assert r.overlay is not None            # overlay still built
    assert "pose" not in r.overlay          # only pose is dropped
    assert "face" in r.overlay and "points" in r.overlay
    assert r.metrics.ear is not None        # metrics unaffected


# -- exception 1: assorted truthy spellings parse as disabled -----------------
def test_truthy_spellings(monkeypatch):
    for val in ("1", "true", "True", "yes"):
        monkeypatch.setenv("NUNCHI_DISABLE_POSE", val)
        assert pose_disabled() is True


# -- exception 2: falsy / unknown values keep pose ON -------------------------
def test_falsy_values_keep_pose_on(monkeypatch):
    for val in ("", "0", "no", "off", "false", "  "):
        monkeypatch.setenv("NUNCHI_DISABLE_POSE", val)
        assert pose_disabled() is False


# -- error/edge: switch only affects pose, not no-face / state machine --------
def test_switch_no_face_unaffected(engine: VisionEngine, monkeypatch):
    monkeypatch.setenv("NUNCHI_DISABLE_POSE", "1")
    st = engine.new_session("sw-noface")
    r = engine.analyze(st, synthetic_frame(), t=0.0)
    assert r.face_present is False
    assert r.overlay is None  # no face -> no overlay regardless of switch
