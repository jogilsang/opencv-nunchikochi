"""Vision evaluation core (V4): label schema, interval matching, metrics, plotting.

Pure logic shared by ``eval/run_vision_eval.py`` (clip/frame-folder runner) and
``tests/vision/test_eval_pipeline.py``. No image is read here except via the
runner; this package handles labels (JSON), interval-overlap matching with an
explicit IoU tolerance, per-behaviour precision/recall/F1, condition breakdowns,
failure (FP/FN) tables, and a timeline PNG (no face pixels — bars only).
"""
from __future__ import annotations

from eval.vision_eval.labels import LabelError, LabelSet, load_labelset
from eval.vision_eval.metrics import (
    BehaviorScore,
    EvalReport,
    Interval,
    match_intervals,
    score_clip,
)
from eval.vision_eval.plot import timeline_png

__all__ = [
    "BehaviorScore",
    "EvalReport",
    "Interval",
    "LabelError",
    "LabelSet",
    "load_labelset",
    "match_intervals",
    "score_clip",
    "timeline_png",
]
