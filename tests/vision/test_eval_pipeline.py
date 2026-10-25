"""V4 eval pipeline — synthetic, no model/webcam/image.

Known labels + known predictions must yield known precision/recall/F1, the
label loader must raise ValueError with context on bad input, the per-frame
event stream must collapse to intervals, and the timeline PNG must be written
(bars only). Also checks record_clips --dry-run plan and the harness self-test.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# eval/ lives at the repo root; pytest only puts src/ on the path (pyproject,
# not ours to edit), so add the repo root here for the eval.vision_eval package.
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from eval.vision_eval.labels import LabelError, load_labelset, parse_labelset
from eval.vision_eval.metrics import (
    Interval,
    aggregate,
    events_to_intervals,
    iou,
    match_intervals,
    score_clip,
)
from eval.vision_eval.plot import timeline_png


def _good_label(clip="c01", light="bright"):
    return {
        "schema": "clip-labels/1",
        "clip": clip,
        "fps_hint": 2.0,
        "conditions": {"light": light, "angle": "frontal"},
        "labels": [
            {"behavior": "yawn", "start": 3.0, "end": 5.0},
            {"behavior": "head_tilt", "start": 8.0, "end": 11.0},
        ],
    }


# -- labels: normal + exceptions ----------------------------------------------

def test_load_labelset_ok(tmp_path: Path):
    p = tmp_path / "c01.labels.json"
    p.write_text(json.dumps(_good_label()), encoding="utf-8")
    ls = load_labelset(p)
    assert ls.clip == "c01" and ls.light == "bright" and ls.angle == "frontal"
    assert len(ls.labels) == 2 and ls.labels[0].behavior == "yawn"


def test_parse_labelset_dict_ok():
    ls = parse_labelset(_good_label(clip="c02"))
    assert ls.clip == "c02" and ls.labels[1].behavior == "head_tilt"


def test_label_bad_schema_raises(tmp_path: Path):
    d = _good_label(); d["schema"] = "wrong/9"
    p = tmp_path / "bad.labels.json"; p.write_text(json.dumps(d), encoding="utf-8")
    with pytest.raises(LabelError) as ei:
        load_labelset(p)
    assert "schema" in str(ei.value)


def test_label_bad_interval_end_before_start_raises():
    d = _good_label(); d["labels"][0] = {"behavior": "yawn", "start": 5.0, "end": 3.0}
    with pytest.raises(LabelError) as ei:
        parse_labelset(d)
    assert "end" in str(ei.value) and "start" in str(ei.value)


def test_label_unknown_behavior_raises():
    d = _good_label(); d["labels"][0]["behavior"] = "sneeze"   # not a scorable behaviour
    with pytest.raises(LabelError) as ei:
        parse_labelset(d)
    assert "sneeze" in str(ei.value)


def test_label_invalid_json_reports_line(tmp_path: Path):
    p = tmp_path / "broken.labels.json"
    p.write_text('{\n  "schema": "clip-labels/1",\n  "clip": "x",\n  bad\n}', encoding="utf-8")
    with pytest.raises(LabelError) as ei:
        load_labelset(p)
    assert "line" in str(ei.value)


# -- metrics: known labels -> known numbers -----------------------------------

def test_iou_basic():
    assert iou(Interval("a", 0, 10), Interval("a", 0, 10)) == pytest.approx(1.0)
    assert iou(Interval("a", 0, 10), Interval("a", 20, 30)) == 0.0
    assert iou(Interval("a", 0, 10), Interval("a", 5, 15)) == pytest.approx(5 / 15)


def test_match_perfect_recall_precision():
    """normal: predictions exactly matching labels -> P=R=F1=1."""
    gt = [Interval("yawn", 3, 5), Interval("head_tilt", 8, 11)]
    pred = [Interval("yawn", 3, 5), Interval("head_tilt", 8, 11)]
    scores, failures = match_intervals(pred, gt, iou_thr=0.3)
    assert scores["yawn"].f1 == 1.0 and scores["head_tilt"].f1 == 1.0
    assert failures == []


def test_match_false_positive_and_negative():
    """normal: one spurious pred (FP) + one missed label (FN) show up in failures."""
    gt = [Interval("yawn", 3, 5), Interval("away", 15, 20)]
    pred = [Interval("yawn", 3.1, 5.1), Interval("blink", 1.0, 1.4)]
    scores, failures = match_intervals(pred, gt, iou_thr=0.3)
    assert scores["yawn"].tp == 1
    assert scores["blink"].fp == 1
    assert scores["away"].fn == 1
    kinds = {(f.kind, f.behavior) for f in failures}
    assert ("FP", "blink") in kinds and ("FN", "away") in kinds


def test_low_overlap_below_threshold_is_miss():
    """exception: overlap under the IoU tolerance counts as FP+FN, not TP."""
    gt = [Interval("head_tilt", 8, 12)]
    pred = [Interval("head_tilt", 11.5, 12.5)]   # tiny overlap
    scores, _ = match_intervals(pred, gt, iou_thr=0.3)
    assert scores["head_tilt"].tp == 0
    assert scores["head_tilt"].fp == 1 and scores["head_tilt"].fn == 1


def test_events_to_intervals_collapse():
    """normal: per-frame ongoing events collapse to one interval; ended closes it."""
    stream = [
        (0.0, []),
        (0.5, [{"type": "yawn", "start": 0.5, "end": None, "confidence": 0.4}]),
        (1.0, [{"type": "yawn", "start": 0.5, "end": None, "confidence": 0.7}]),
        (1.5, [{"type": "yawn", "start": 0.5, "end": 1.5, "confidence": 0.7}]),
    ]
    ivs = events_to_intervals(stream)
    assert len(ivs) == 1
    assert ivs[0].behavior == "yawn" and ivs[0].start == 0.5 and ivs[0].end == 1.5
    assert ivs[0].confidence == pytest.approx(0.7)


def test_events_to_intervals_closes_on_vanish():
    """exception: an ongoing event that simply stops appearing is still closed."""
    stream = [
        (0.0, [{"type": "head_tilt", "start": 0.0, "end": None, "confidence": 0.5}]),
        (1.0, [{"type": "head_tilt", "start": 0.0, "end": None, "confidence": 0.5}]),
        (2.0, []),                      # vanished without an explicit end
    ]
    ivs = events_to_intervals(stream)
    assert len(ivs) == 1 and ivs[0].end >= 1.0


def test_aggregate_by_light():
    """normal: aggregate splits scores by lighting condition."""
    r1 = score_clip("a", {"light": "bright"}, [Interval("yawn", 3, 5)], [Interval("yawn", 3, 5)])
    r2 = score_clip("b", {"light": "dim"}, [], [Interval("yawn", 3, 5)])   # a miss in the dark
    agg = aggregate([r1, r2])
    assert agg["clips"] == 2
    assert agg["by_light"]["bright"]["yawn"]["tp"] == 1
    assert agg["by_light"]["dim"]["yawn"]["fn"] == 1


# -- plotting -----------------------------------------------------------------

def test_timeline_png_written(tmp_path: Path):
    """normal: timeline PNG is written and non-empty (bars only, no image frame)."""
    out = tmp_path / "timeline.png"
    gt = [Interval("yawn", 3, 5), Interval("away", 15, 20)]
    pred = [Interval("yawn", 3.1, 5.1), Interval("blink", 1, 1.4)]
    path = timeline_png(out, pred=pred, gt=gt, clip="t1")
    assert Path(path).exists() and Path(path).stat().st_size > 0


def test_timeline_png_empty_behaviors(tmp_path: Path):
    """error/edge: no predictions and no labels still produces a valid PNG."""
    out = tmp_path / "empty.png"
    path = timeline_png(out, pred=[], gt=[], clip="empty")
    assert Path(path).exists() and Path(path).stat().st_size > 0


# -- CLI smoke ----------------------------------------------------------------

def test_record_clips_dry_run():
    """normal: record tool --dry-run prints a plan and never touches the camera."""
    r = subprocess.run([sys.executable, "eval/record_clips.py", "--dry-run", "--light", "dim"],
                       check=False, cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0
    assert "DRY-RUN" in r.stdout and "dim" in r.stdout
    assert "away_dim" in r.stdout and "yawn_dim" in r.stdout


def test_record_clips_includes_v13_falsepositive_and_drink_shots():
    """V13: the record plan must include the drink shot and the negative
    (no-event) false-positive clips — typing / chin-rest / looking down — so the
    user can capture the exact situations that mislabelled (and the labels for the
    negatives stay empty = 'event: none')."""
    from eval.record_clips import SCRIPT, plan
    suffixes = {s.clip_suffix: s for s in SCRIPT}
    for name in ("drink", "typing", "chin_rest", "look_down_keyboard"):
        assert name in suffixes, f"missing shot {name}"
    # negatives carry no behaviour label (a real event here would be a false positive)
    assert suffixes["typing"].behavior is None
    assert suffixes["chin_rest"].behavior is None
    assert suffixes["look_down_keyboard"].behavior is None
    assert suffixes["drink"].behavior == "drink"
    # typing is the 30s soak the brief asked for
    assert suffixes["typing"].seconds >= 30
    # the plan reflects the same (negatives -> behavior None in the emitted plan)
    items = {it["clip"]: it for it in plan("bright")}
    assert items["typing_bright"]["behavior"] is None
    assert items["drink_bright"]["behavior"] == "drink"


def test_harness_self_test(tmp_path: Path):
    """normal: harness --self-test runs the full match+report+PNG path, no model."""
    out = tmp_path / "selftest"
    r = subprocess.run([sys.executable, "eval/run_vision_eval.py", "--self-test", "--out", str(out)],
                       check=False, cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (out / "vision_eval_selftest.json").exists()
    assert (out / "timeline_selftest.png").exists()
    data = json.loads((out / "vision_eval_selftest.json").read_text(encoding="utf-8"))
    assert data["clips"][0]["dataset"] == "synthetic"     # not real performance
