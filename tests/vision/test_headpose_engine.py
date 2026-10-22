"""V10 head-pose end-to-end through VisionEngine (uses a public face sample).

Verifies overlay.pose appears with the contract keys, that a frame rotation moves
``roll_deg`` and scaling moves ``depth`` in the right direction, that the pose is
reported RELATIVE to the calibrated frontal, that variants still produce a pose
without mutating state, and that the serialised state stays <= 8 KB.
"""
from __future__ import annotations

import json

import pytest

from nunchi.vision import SessionState, VisionEngine

from .conftest import read_bgr, rotate, scale, synthetic_frame

_POSE_KEYS = {"yaw_deg", "pitch_deg", "roll_deg", "depth", "conf"}


def _face_sample(sample_images):
    face = next(((n, p) for (n, p, hf) in sample_images if hf), None)
    if face is None:
        pytest.skip("no public face sample available (offline?)")
    return read_bgr(face[1])


def _calibrate(engine, st, img, n=20):
    res = None
    for i in range(n):
        res = engine.calibrate(st, img, t=i * 0.3)
    return res


# -- normal 1: analyze fills overlay.pose with the contract keys --------------
def test_overlay_has_pose(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("pose-1")
    _calibrate(engine, st, img)
    r = engine.analyze(st, img, t=6.0)
    assert r.overlay is not None and "pose" in r.overlay
    pose = r.overlay["pose"]
    assert set(pose) == _POSE_KEYS
    assert all(isinstance(pose[k], float) for k in _POSE_KEYS)
    assert 0.0 <= pose["conf"] <= 1.0
    # same frame as calibration -> near-frontal relative pose and depth ~1
    assert abs(pose["yaw_deg"]) < 12 and abs(pose["pitch_deg"]) < 12 and abs(pose["roll_deg"]) < 12
    assert 0.8 <= pose["depth"] <= 1.2


# -- normal 2: rotating the frame moves roll_deg (eye-line roll) --------------
def test_rotation_moves_pose_roll(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    s0 = engine.new_session("pose-r0")
    _calibrate(engine, s0, img)
    r0 = engine.analyze(s0, img, t=6.0)
    s1 = engine.new_session("pose-r1")
    _calibrate(engine, s1, img)
    r1 = engine.analyze(s1, rotate(img, 12), t=6.0)
    assert r0.overlay and r1.overlay and "pose" in r0.overlay and "pose" in r1.overlay
    assert abs(r1.overlay["pose"]["roll_deg"] - r0.overlay["pose"]["roll_deg"]) > 4.0


# -- normal 3: bringing the face closer raises depth --------------------------
def test_scale_raises_depth(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("pose-depth")
    _calibrate(engine, st, img)                 # baseline at full size
    near = engine.analyze(st, scale(img, 1.3), t=6.0)   # bigger face = closer
    assert near.overlay and "pose" in near.overlay
    assert near.overlay["pose"]["depth"] > 1.05


# -- normal 4: pose is relative to the calibrated frontal ---------------------
def test_pose_is_relative_to_baseline(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    # calibrate on a TILTED frame so the frontal baseline roll is non-zero;
    # analysing the SAME tilted frame must read ~0 relative roll.
    tilted = rotate(img, 10)
    st = engine.new_session("pose-rel")
    _calibrate(engine, st, tilted)
    assert st.baseline is not None
    r = engine.analyze(st, tilted, t=6.0)
    assert r.overlay and "pose" in r.overlay
    # relative roll near zero even though the absolute head is tilted 10deg
    assert abs(r.overlay["pose"]["roll_deg"]) < 6.0


# -- exception 1: no face -> no pose (web freezes the doll) --------------------
def test_no_face_no_pose(engine: VisionEngine):
    st = engine.new_session("pose-noface")
    r = engine.analyze(st, synthetic_frame(), t=0.0)
    assert r.face_present is False
    assert r.overlay is None  # no overlay at all without a face


# -- exception 2: a variant produces a pose but does not mutate state ---------
def test_variant_pose_no_mutation(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("pose-var")
    _calibrate(engine, st, img)
    before = json.dumps(st.to_dict(), sort_keys=True)
    rv = engine.analyze_variant(st, img, t=6.0, variant="enhance")
    after = json.dumps(st.to_dict(), sort_keys=True)
    assert before == after  # variant must not change session state
    # the variant still offers a pose for the agent/web to compare (may be absent
    # if the enhanced solve fails, but keys must be correct when present)
    if rv.overlay and "pose" in rv.overlay:
        assert set(rv.overlay["pose"]) == _POSE_KEYS


# -- error/edge: serialised state with pose filters stays <= 8 KB -------------
def test_state_blob_within_budget(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("pose-size")
    _calibrate(engine, st, img)
    for i in range(40):
        engine.analyze(st, img, t=6.0 + i * 0.3)
    blob = json.dumps(st.to_dict())
    assert len(blob.encode("utf-8")) <= 8192, f"state blob {len(blob)} bytes > 8KB"
    # round-trips to an identical dict (pose baseline + filters restore)
    st2 = SessionState.from_dict(json.loads(blob))
    assert st2.to_dict() == st.to_dict()
    assert st2.baseline is not None
    assert hasattr(st2.baseline, "pose_yaw0")
