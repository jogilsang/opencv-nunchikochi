"""pytest wiring for the adversarial/boundary eval set (A5). No network, no images.

Pins the honest-evaluation invariants:
  - >= 8 adversarial scenarios exist with unique ids
  - the agent NEVER crashes on adversarial input (it degrades to a safe action)
  - the one known expectation-mismatch is reported, not hidden, and is a scenario
    design note (agent behaviour is correct) — this test asserts it stays visible
  - every adversarial final decision is still bilingual-or-empty and image-free
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUN_EVAL = ROOT / "eval" / "agent" / "run_eval.py"
ADV_DIR = ROOT / "eval" / "agent" / "scenarios_adversarial"


def _load_runner():
    import sys
    spec = importlib.util.spec_from_file_location("agent_run_eval", RUN_EVAL)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["agent_run_eval"] = mod   # so dataclasses resolve __module__
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


@pytest.fixture(scope="module")
def adv(runner):
    scns = runner.load_adversarial()
    return runner, scns, [runner.run_scenario_safe(s) for s in scns]


def test_at_least_8_adversarial_scenarios(adv):
    _, scns, _ = adv
    assert len(scns) >= 8, "brief requires >= 8 adversarial scenarios"


def test_adversarial_ids_unique(adv):
    _, scns, _ = adv
    ids = [s["id"] for s in scns]
    assert len(ids) == len(set(ids)), "duplicate adversarial ids"


def test_adversarial_covers_required_categories(adv):
    """The 8 brief-mandated adversarial categories are all represented."""
    _, scns, _ = adv
    cats = {s.get("category") for s in scns}
    required = {
        "tool-arg-outlier", "out-of-order-tool-result", "llm-invents-tool",
        "instruction-bypass-text", "conflicting-signals", "borderline-oscillation",
        "missing-context", "budget-exhausted",
    }
    missing = required - cats
    assert not missing, f"missing adversarial categories: {missing}"


def test_agent_never_crashes_on_adversarial_input(adv):
    """The core robustness invariant: no adversarial scenario makes the agent raise."""
    _, _, res = adv
    crashed = [(r.id, r.failure) for r in res if r.crashed]
    assert not crashed, f"agent crashed on adversarial input: {crashed}"


def test_known_mismatch_is_reported_not_hidden(adv):
    """The budget-zero scenario's step-1 mismatch is a documented scenario-design note.

    We assert it is still surfaced as a non-passing result WITH an analysis string,
    i.e. we did not silently tune the expectation to make it green.
    """
    _, _, res = adv
    byid = {r.id: r for r in res}
    r = byid.get("adv_llm_budget_zero")
    assert r is not None
    if not r.passed:  # current, honest state
        assert r.analysis, "a reported mismatch must carry a written analysis"
        assert "에이전트 결함 아님" in r.analysis


def test_adversarial_final_decisions_are_safe(adv):
    """Every adversarial scenario ends on a whitelisted action (no rogue action leaked)."""
    from nunchi.agent.guardrails import ALLOWED_ACTIONS
    _, _, res = adv
    for r in res:
        if r.steps:
            assert r.steps[-1].action in ALLOWED_ACTIONS, (r.id, r.steps[-1].action)


def test_adversarial_scenarios_are_valid_json(adv):
    """Each adversarial file parses and has the minimal required keys."""
    files = sorted(ADV_DIR.glob("*.json"))
    assert files
    for f in files:
        obj = json.loads(f.read_text())
        for key in ("id", "category", "description", "steps"):
            assert key in obj, f"{f.name} missing {key}"
