"""Tests for nunchi.vision.VisionEngine (behaviour against the FrameResult contract)."""
from __future__ import annotations

import pytest

from nunchi.contracts import FrameResult, Quality
from nunchi.vision import SessionState, VisionEngine

from .conftest import read_bgr, synthetic_frame


# -- normal 1: detects faces + reports low latency on >=10 public samples -----
def test_detects_faces_and_reports_latency(engine: VisionEngine, sample_images):
    face_imgs = [(n, p) for (n, p, has_face) in sample_images if has_face]
    if len(sample_images) < 10:
        pytest.skip(f"need >=10 public samples, got {len(sample_images)} (offline?)")
    assert face_imgs, "expected at least one face sample"

    detected = 0
    latencies = []
    state = engine.new_session("s-samples")
    for name, path in face_imgs:
        img = read_bgr(path)
        res = engine.analyze(state, img, t=0.0)
        assert isinstance(res, FrameResult)
        latencies.append(res.latency_ms)
        if res.face_present:
            detected += 1
    # at least one known face sample must be detected
    assert detected >= 1
    assert all(ms >= 0 for ms in latencies)


# -- normal 2: analyze fills the contract fields correctly --------------------
def test_analyze_fills_contract_fields(engine: VisionEngine, sample_images):
    # prefer a real face sample; fall back to synthetic (no face) but still valid contract
    face = next(((n, p) for (n, p, hf) in sample_images if hf), None)
    state = engine.new_session("s-contract")
    img = read_bgr(face[1]) if face else synthetic_frame()
    res = engine.analyze(state, img, t=1.5)

    assert res.session_id == "s-contract"
    assert res.t == 1.5
    assert res.cv_version.startswith("5.")
    assert res.backend in ("opencv", "cool")
    assert isinstance(res.quality, Quality)
    assert res.calibrated is False
    # face_scale must be None before calibration (V2), regardless of face presence
    assert res.metrics.face_scale is None
    assert isinstance(res.persons, int) and res.persons >= 0


# -- normal 3: quality on a flat frame flags no_face/blur and ok=False --------
def test_quality_on_flat_frame_flags_issues(engine: VisionEngine):
    q = engine.quality(synthetic_frame(value=127))
    assert isinstance(q, Quality)
    assert q.ok is False
    assert "no_face" in q.issues  # flat grey has no face
    assert q.face_px == 0


# -- exception 1: missing model dir -> FileNotFoundError ----------------------
def test_missing_model_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        VisionEngine(str(tmp_path))


# -- exception 2: empty/None frame to quality is handled, not crashing --------
def test_quality_handles_empty_frame(engine: VisionEngine):
    import numpy as np
    q = engine.quality(np.empty((0, 0, 3), dtype=np.uint8))
    assert q.ok is False
    assert "no_face" in q.issues


# -- error/edge: too-dark frame is flagged too_dark ---------------------------
def test_quality_flags_too_dark(engine: VisionEngine):
    q = engine.quality(synthetic_frame(value=5))
    assert "too_dark" in q.issues
    assert q.ok is False


# -- state: new_session returns independent SessionState ----------------------
def test_new_session_independent_state(engine: VisionEngine):
    a = engine.new_session("a")
    b = engine.new_session("b")
    assert isinstance(a, SessionState) and a.session_id == "a"
    assert a is not b and a.calibrated is False and a.baseline_face_px is None
