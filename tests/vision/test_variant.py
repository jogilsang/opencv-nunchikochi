"""Tests for analyze_variant (active perception) and overlay."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from nunchi.vision import VisionEngine
from nunchi.vision.overlay import MAX_OVERLAY_POINTS

from .conftest import read_bgr, synthetic_frame


def _face_sample(sample_images):
    face = next(((n, p) for (n, p, hf) in sample_images if hf), None)
    if face is None:
        pytest.skip("no public face sample available (offline?)")
    return read_bgr(face[1])


def _darken(img: np.ndarray, factor: float = 0.3) -> np.ndarray:
    return (img.astype(np.float32) * factor).astype(np.uint8)


# -- normal 1: enhance improves quality on a darkened face frame --------------
def test_enhance_improves_quality(engine: VisionEngine, sample_images):
    img = _darken(_face_sample(sample_images), 0.3)
    st = engine.new_session("s-enh")
    before = engine.analyze(st, img, t=0.0)
    after = engine.analyze_variant(st, img, t=0.0, variant="enhance")
    # brightness must rise; enhance should not make it darker
    assert after.quality.brightness > before.quality.brightness
    # darkened original likely flags too_dark; enhanced should clear or reduce issues
    assert "too_dark" not in after.quality.issues or len(after.quality.issues) <= len(before.quality.issues)


# -- normal 2: zoom_face still detects the face (same-shape result) -----------
def test_zoom_face_returns_frameresult(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("s-zoom")
    r = engine.analyze_variant(st, img, t=1.0, variant="zoom_face")
    assert r.t == 1.0 and r.cv_version.startswith("5.")
    assert r.face_present is True  # a clear face should survive the zoom


# -- normal 3: strict uses tighter gates (issues can only grow or equal) ------
def test_strict_is_not_more_lenient(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("s-strict")
    normal = engine.analyze(st, img, t=0.0)
    strict = engine.analyze_variant(st, img, t=0.0, variant="strict")
    # strict blur/face thresholds are tighter -> never fewer issues than normal
    assert len(strict.quality.issues) >= len(normal.quality.issues)


# -- normal 4: variant does NOT mutate session state --------------------------
def test_variant_does_not_mutate_state(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("s-nomut")
    for i in range(20):
        engine.calibrate(st, img, t=i * 0.3)
    snap = copy.deepcopy(st.to_dict())
    frames_before = st.frames_seen
    engine.analyze_variant(st, img, t=6.0, variant="enhance")
    engine.analyze_variant(st, img, t=6.0, variant="zoom_face")
    engine.analyze_variant(st, img, t=6.0, variant="strict")
    assert st.frames_seen == frames_before          # no frame counted
    assert st.to_dict() == snap                      # filters/baseline unchanged


# -- exception 1: unknown variant raises ValueError ---------------------------
def test_unknown_variant_raises(engine: VisionEngine):
    st = engine.new_session("s-bad")
    with pytest.raises(ValueError):
        engine.analyze_variant(st, synthetic_frame(), t=0.0, variant="nope")


# -- exception 2: variant on a no-face frame returns valid empty result -------
def test_variant_no_face(engine: VisionEngine):
    st = engine.new_session("s-vnf")
    r = engine.analyze_variant(st, synthetic_frame(value=127), t=0.0, variant="enhance")
    assert r.face_present is False
    assert r.overlay is None


# -- overlay 1: overlay is normalised 0..1, small, pixel-free -----------------
def test_overlay_normalised_and_small(engine: VisionEngine, sample_images):
    img = _face_sample(sample_images)
    st = engine.new_session("s-ov")
    r = engine.analyze(st, img, t=0.0)
    assert r.overlay is not None
    face = r.overlay["face"]
    assert len(face) == 4 and all(0.0 <= v <= 1.0 for v in face)
    pts = r.overlay["points"]
    for name in ("eye_l", "eye_r", "nose", "mouth_l", "mouth_r"):
        x, y = pts[name]
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
    # count all emitted points <= cap; no raw 478 mesh
    n = len(pts) + sum(len(v) for v in r.overlay["contour"].values())
    assert n <= MAX_OVERLAY_POINTS
    # overlay holds only numbers/lists (no ndarray/bytes)
    import json
    json.dumps(r.overlay)  # must be JSON-serialisable


# -- overlay 2 / error-edge: no face -> overlay None --------------------------
def test_overlay_none_without_face(engine: VisionEngine):
    st = engine.new_session("s-ov2")
    r = engine.analyze(st, synthetic_frame(value=127), t=0.0)
    assert r.overlay is None
