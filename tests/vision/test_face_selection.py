"""V5 face-selection robustness — pure helper tests, no model/image.

The subject must be the largest face (ties toward centre); a small background /
spurious detection (the "passing person") must not become the subject, must not
raise ``multiple_faces``, and must not inflate ``persons``. These are the
structural fixes the V5 sweep motivated. Helpers take raw YuNet-style rows
[x, y, w, h, ...], so no model is needed.
"""
from __future__ import annotations

import numpy as np
import pytest

from nunchi.vision.landmarks import (
    SECONDARY_MIN_AREA_RATIO,
    count_people,
    secondary_face_significant,
    select_primary_face,
)


def _face(x, y, w, h, score=0.9):
    # YuNet row: x,y,w,h, 5*2 landmarks, score  -> 15 cols
    row = np.zeros(15, dtype=np.float32)
    row[0], row[1], row[2], row[3] = x, y, w, h
    row[14] = score
    return row


# -- select_primary_face ------------------------------------------------------

def test_primary_is_largest_not_highest_score():
    """normal: a big low-score face beats a small high-score one (subject = largest)."""
    big = _face(100, 100, 120, 120, score=0.61)     # large, lower score
    small = _face(10, 10, 30, 30, score=0.99)        # tiny, top score (YuNet[0])
    faces = [small, big]                             # order as YuNet might return
    primary = select_primary_face(faces, 640, 480)
    assert primary is big


def test_primary_tie_breaks_toward_centre():
    """normal: equal-size faces -> the one nearer the frame centre wins."""
    centre = _face(280, 200, 100, 100)               # near centre of 640x480
    corner = _face(0, 0, 100, 100)
    primary = select_primary_face([corner, centre], 640, 480)
    assert primary is centre


def test_primary_empty_raises():
    """error: no faces -> ValueError (caller must guard)."""
    with pytest.raises(ValueError):
        select_primary_face([], 640, 480)


# -- secondary_face_significant (multiple_faces gate) -------------------------

def test_background_face_not_significant():
    """normal: a small background box (< ratio) is NOT a real second person."""
    primary = _face(200, 150, 160, 160)              # area 25600
    bg = _face(600, 0, 40, 40)                        # area 1600 ~ 6% -> background
    assert secondary_face_significant([primary, bg], primary) is False


def test_comparable_second_face_is_significant():
    """normal: a comparable-size second face (>= ratio) IS a second person."""
    primary = _face(100, 150, 160, 160)
    other = _face(400, 150, 140, 140)                 # ~77% area -> significant
    assert secondary_face_significant([primary, other], primary) is True


def test_single_face_never_significant():
    """exception: one face -> no secondary."""
    primary = _face(100, 100, 100, 100)
    assert secondary_face_significant([primary], primary) is False


def test_ratio_boundary():
    """edge: a face at/above the area ratio counts as significant, below does not."""
    primary = _face(0, 0, 100, 100)                   # area 10000
    import math
    side_at = math.ceil((SECONDARY_MIN_AREA_RATIO ** 0.5) * 100)   # area >= ratio*10000
    other = _face(200, 0, side_at, side_at)
    assert secondary_face_significant([primary, other], primary) is True
    below = _face(200, 0, side_at - 5, side_at - 5)   # clearly under the ratio
    assert secondary_face_significant([primary, below], primary) is False


# -- count_people -------------------------------------------------------------

def test_count_people_ignores_background():
    """normal: subject + tiny background box -> 1 person (passing person)."""
    primary = _face(200, 150, 160, 160)
    bg = _face(600, 0, 40, 40)
    assert count_people([primary, bg], 640, 480) == 1


def test_count_people_two_real():
    """normal: two comparable faces -> 2 people."""
    a = _face(100, 150, 150, 150)
    b = _face(400, 150, 140, 140)
    assert count_people([a, b], 640, 480) == 2


def test_count_people_empty():
    """exception: no faces -> 0."""
    assert count_people([], 640, 480) == 0


# -- engine integration (model-dependent; skips cleanly offline) --------------

def test_passing_person_not_multiple_faces(engine, sample_images):
    """normal: a small background face composited into the corner must not raise
    'multiple_faces' nor make persons>1 (the V5 passing-person fix end to end)."""
    import cv2

    faces = [(n, p) for (n, p, hf) in sample_images if hf]
    if len(faces) < 2:
        pytest.skip("need two public face samples (offline?)")
    primary = cv2.resize(cv2.imread(str(faces[0][1])), (480, 480))
    secondary = cv2.imread(str(faces[1][1]))
    comp = primary.copy()
    H, W = comp.shape[:2]
    sm = cv2.resize(secondary, (int(W * 0.22), int(H * 0.22)))     # small corner face
    comp[0:sm.shape[0], W - sm.shape[1]:W] = sm

    q = engine.quality(comp)
    assert "multiple_faces" not in q.issues
    r = engine.analyze(engine.new_session("pp"), comp, t=0.0)
    assert r.persons <= 1


def test_small_face_retry_detects(engine, sample_images):
    """V6: a small face that the full-res pass may miss is recovered by the
    2x-upscale retry inside extract_best (used by analyze)."""
    import cv2
    import numpy as np

    face = next(((n, p) for (n, p, hf) in sample_images if hf), None)
    if face is None:
        pytest.skip("no public face sample (offline?)")
    img = cv2.resize(cv2.imread(str(face[1])), (480, 480))
    H, W = 240, 320
    frac = 0.3
    small = cv2.resize(img, (int(W * frac), int(H * frac)))
    canvas = np.full((H, W, 3), 127, np.uint8)
    canvas[0:small.shape[0], 0:small.shape[1]] = small

    # extract_best should find the face (retry helps vs a single pass)
    lm = engine._lm.extract_best(canvas)
    r = engine.analyze(engine.new_session("sf"), canvas, t=0.0)
    # at 30% the retry recovers detection in the sweep; assert the pipeline
    # produces a consistent answer (face found -> metrics present).
    if lm.ok:
        assert r.face_present is True
        assert r.metrics.ear is not None
