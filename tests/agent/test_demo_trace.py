"""pytest wiring for the Agentic Vision demo traces (A6). No network, no images.

Pins that the 5 representative demo scenarios run deterministically, each writes
an image-free timeline + JSONL, and the key narrative of each still holds (so the
submission evidence cannot silently rot). Runs run_one() in memory only — it does
NOT overwrite docs/submission/traces (that is demo_trace.py's job).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEMO = ROOT / "eval" / "agent" / "demo_trace.py"


def _load():
    import sys
    spec = importlib.util.spec_from_file_location("agent_demo_trace", DEMO)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["agent_demo_trace"] = mod   # so dataclasses resolve __module__
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def demo():
    return _load()


@pytest.fixture(scope="module")
def runs(demo):
    out = {}
    for scn in demo._scenarios():
        md, rec, _used_live = demo.run_one(scn, live_planner=None)  # deterministic
        out[scn["id"]] = (scn, md, rec)
    return demo, out


def test_five_representative_scenarios(runs):
    _, out = runs
    assert len(out) == 5
    assert set(out) == {
        "second_look_quality_cleared", "low_conf_ask_confirmation",
        "guardrail_blocks_action", "llm_timeout_fallback",
        "denied_confirmation_raises_threshold",
    }


def test_every_timeline_and_jsonl_is_image_free(runs):
    _, out = runs
    banned = ("jpeg", "frame_bgr", "pixels", "landmark", "bbox", "<object",
              "head_roll", "image/")
    for sid, (_scn, md, rec) in out.items():
        blob = (md + "\n" + rec.to_jsonl()).lower()
        for b in banned:
            assert b not in blob, f"{sid} leaked {b!r}"


def test_timelines_reference_a_real_test(runs):
    """Each scenario cites a pytest; the file part must exist on disk."""
    _, out = runs
    for sid, (scn, _md, _rec) in out.items():
        pytest_ref = scn["pytest"].split("::")[0]
        assert (ROOT / pytest_ref).exists(), f"{sid}: missing {pytest_ref}"


def test_key_narratives_hold(runs):
    """The decisive outcome of each representative scenario is what we claim."""
    _, out = runs

    # 1 second_look cleared quality -> final decision none, reason mentions second_look
    rec = out["second_look_quality_cleared"][2]
    last = rec.lines[-1]
    assert last.decision == "none" and last.reason.startswith("second_look:")

    # 2 low confidence -> ask the human
    rec = out["low_conf_ask_confirmation"][2]
    assert rec.lines[-1].decision == "ask_confirmation"

    # 3 guardrail blocks a forbidden action -> rules, with guardrail rejection noted
    rec = out["guardrail_blocks_action"][2]
    last = rec.lines[-1]
    assert last.planner == "rules"
    assert "guardrail:" in last.result_summary

    # 4 timeout -> rules fallback, timeout noted (deterministic FakeLLM sleep path)
    rec = out["llm_timeout_fallback"][2]
    last = rec.lines[-1]
    assert last.planner == "rules"
    assert "llm_timeout" in last.result_summary

    # 5 denial raises threshold: first ask, then NOT asked again at same confidence
    rec = out["denied_confirmation_raises_threshold"][2]
    assert rec.lines[0].decision == "ask_confirmation"
    assert rec.lines[-1].decision != "ask_confirmation"


def test_jsonl_lines_parse(runs):
    """Every emitted JSONL line is valid JSON (reproducible machine trace)."""
    _, out = runs
    for _scn, _md, rec in out.values():
        for line in rec.to_jsonl().splitlines():
            if line.strip():
                json.loads(line)  # raises on malformed
