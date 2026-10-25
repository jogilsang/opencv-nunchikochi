"""A12: pin the before/after calming measurement so the Devpost claim stays true.

Runs the synthetic 1-hour harness and asserts the direction (calm < before) and the key
invariant (the FIRST nudge is never delayed). Values are exact so a regression that
re-loudens the agent fails here. No network, no images.
"""
from __future__ import annotations

import importlib.util
import pathlib

_SRC = pathlib.Path(__file__).resolve().parents[2] / "eval" / "agent" / "alert_calming.py"
_spec = importlib.util.spec_from_file_location("agent_alert_calming", _SRC)
alert_calming = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(alert_calming)  # type: ignore[union-attr]
measure = alert_calming.measure


def test_calming_reduces_total_alerts_without_delaying_first_nudge():
    m = measure()
    b, a = m["before"], m["after"]
    # fewer interruptions overall and fewer repeat nudges
    assert a["total_alerts"] < b["total_alerts"]
    assert a["nudges_sent"] < b["nudges_sent"]
    assert a["quality_warnings"] <= b["quality_warnings"]
    # the FIRST nudge must not be delayed by calming (same moment in both)
    c = m["cost_of_calming"]
    assert c["first_nudge_same_s"][0] == c["first_nudge_same_s"][1]
    # held alerts are accounted for, not lost (digest is non-empty after calming)
    assert a["suppressed_digest"], "suppressed signals must be counted in the digest"


def test_exact_measured_counts_are_stable():
    """Exact numbers quoted in docs/eval/ALERT_CALMING.md — update both together."""
    m = measure()
    assert (m["before"]["nudges_sent"], m["after"]["nudges_sent"]) == (6, 3)
    assert (m["before"]["confirms_asked"], m["after"]["confirms_asked"]) == (1, 1)
    assert (m["before"]["quality_warnings"], m["after"]["quality_warnings"]) == (2, 1)
    assert (m["before"]["total_alerts"], m["after"]["total_alerts"]) == (9, 5)
    assert m["cost_of_calming"]["first_repeat_nudge_delayed_by_s"] == 600.0


def test_short_vs_full_sample_trend_is_improving():
    """The sample JSON the web/docs quote reads as an improving trend."""
    s = alert_calming._sample_timeline_json()
    assert s["trend"]["direction"] == "improving"
    assert s["trend"]["today_rate"] < s["trend"]["baseline_rate"]
