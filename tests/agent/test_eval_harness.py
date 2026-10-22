"""pytest wiring for the agent eval harness (deterministic mode).

Guarantees the scenario suite exists (>=20), every scenario passes in deterministic
mode, and the aggregate metrics are well-formed. No network (FakeLLM/StubVision).
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUN_EVAL = ROOT / "eval" / "agent" / "run_eval.py"


def _load_runner():
    import sys
    spec = importlib.util.spec_from_file_location("agent_run_eval", RUN_EVAL)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["agent_run_eval"] = mod   # so dataclasses can resolve __module__
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


@pytest.fixture(scope="module")
def results(runner):
    scns = runner.load_scenarios()
    return runner, scns, [runner.run_scenario(s) for s in scns]


def test_at_least_20_scenarios(results):
    _, scns, _ = results
    assert len(scns) >= 20


def test_scenario_ids_unique(results):
    _, scns, _ = results
    ids = [s["id"] for s in scns]
    assert len(ids) == len(set(ids)), "duplicate scenario ids"


def test_all_scenarios_pass_deterministic(results):
    _, _, res = results
    failures = [(r.id, r.failure) for r in res if not r.passed]
    assert not failures, f"failing scenarios: {failures}"


def test_metrics_wellformed(results):
    runner, _, res = results
    agg = runner.aggregate(res)
    assert agg["scenarios"] >= 20
    assert agg["passed"] == agg["scenarios"]
    assert 0.0 <= agg["success_rate"] <= 1.0
    assert agg["avg_tool_calls"] >= 0
    # the harness must actually exercise active perception and human-in-the-loop
    assert agg["second_look_used"] >= 1
    assert agg["asked_human"] >= 1
    assert agg["fallbacks"] >= 1


def test_second_look_changes_some_decisions(results):
    """At least one scenario proves OpenCV re-analysis changed the decision."""
    _, _, res = results
    assert any(r.second_look_changed for r in res)


def test_traces_are_image_free(results):
    """Any trace written by the harness must contain no image/coordinate payload."""
    import json
    _, _, _ = results  # ensure scenarios ran so traces exist
    trace_dir = ROOT / "eval" / "agent" / "traces"
    files = list(trace_dir.glob("*.jsonl")) if trace_dir.exists() else []
    assert files, "expected representative traces to be written"
    banned = ("jpeg", "frame_bgr", "pixels", "image/", "landmark", "bbox", "head_roll")
    for f in files:
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            blob = json.dumps(json.loads(line)).lower()
            for b in banned:
                assert b not in blob, f"{f.name} contains {b}"
