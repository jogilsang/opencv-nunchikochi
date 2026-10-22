"""SessionSummary aggregation, day-over-day compare, and template report."""
from __future__ import annotations

from nunchi.agent import NunchiAgent, SummaryAccumulator, compare
from nunchi.contracts import SessionSummary

from .conftest import ev, frame

# ----------------------------------------------------------- aggregation


def test_accumulator_counts_distinct_events_once():
    """An ongoing event seen across many frames is counted once, not per frame."""
    acc = SummaryAccumulator(session_id="s", date="2026-10-22")
    for t in (10.0, 11.0, 12.0):
        acc.add_frame(frame(t, events=[ev("forward_head", 10.0, None, 0.9)]))  # same start
    summ = acc.finalize(end_t=13.0)
    assert summ.counts["forward_head"] == 1
    # seconds accrued from start(10) to end(13)
    assert summ.seconds["forward_head"] == 3.0
    assert summ.longest_s["forward_head"] == 3.0


def test_accumulator_closed_events_accumulate_seconds_and_longest():
    """Two closed intervals accumulate total seconds and track the longest."""
    acc = SummaryAccumulator(session_id="s", date="2026-10-22")
    acc.add_frame(frame(5.0, events=[ev("head_tilt", 2.0, 5.0, 0.8)]))   # 3s
    acc.add_frame(frame(20.0, events=[ev("head_tilt", 12.0, 20.0, 0.8)]))  # 8s
    summ = acc.finalize(end_t=20.0)
    assert summ.counts["head_tilt"] == 2
    assert summ.seconds["head_tilt"] == 11.0
    assert summ.longest_s["head_tilt"] == 8.0


def test_accumulator_notes_agent_decisions():
    """note_decision folds the agent's own actions into the summary tallies."""
    acc = SummaryAccumulator(session_id="s", date="2026-10-22")
    acc.add_frame(frame(1.0))
    for a in ("nudge", "suppress_focus", "ask_confirmation", "request_recalibration", "none"):
        acc.note_decision(a)
    summ = acc.finalize(end_t=2.0)
    assert summ.nudges_sent == 1 and summ.nudges_suppressed == 1
    assert summ.confirmations_asked == 1 and summ.recalibrations == 1


# --------------------------------------------------------------- compare


def test_compare_no_previous_marks_na():
    """With no previous day, every behaviour reports 'no comparable value'."""
    today = SessionSummary(session_id="s", date="2026-10-22",
                           seconds={"forward_head": 300.0}, counts={"blink": 500})
    out = compare(today, None)
    assert out["has_previous"] is False
    assert all(d["pct_change"] is None for d in out["deltas"].values())
    assert any("no comparable value" in ln for ln in out["lines_en"])


def test_compare_reports_increase_and_decrease():
    """Percent deltas and directions are computed per behaviour (observation wording)."""
    prev = SessionSummary(session_id="a", date="2026-10-21",
                          seconds={"forward_head": 200.0}, counts={"blink": 1000})
    today = SessionSummary(session_id="b", date="2026-10-22",
                           seconds={"forward_head": 300.0}, counts={"blink": 500})
    out = compare(today, prev)
    assert out["has_previous"] is True
    assert out["deltas"]["forward_head"]["pct_change"] == 50.0
    assert out["deltas"]["forward_head"]["direction"] == "up"
    assert out["deltas"]["blink"]["pct_change"] == -50.0
    assert out["deltas"]["blink"]["direction"] == "down"
    # no diagnosis language
    blob = " ".join(out["lines_en"] + out["lines_ko"]).lower()
    assert "tired" not in blob and "unhealthy" not in blob


def test_compare_same_within_band():
    """A small change (<= same_band_pct) reports 'about the same'."""
    prev = SessionSummary(session_id="a", date="2026-10-21", counts={"yawn": 10})
    today = SessionSummary(session_id="b", date="2026-10-22", counts={"yawn": 10})
    out = compare(today, prev)
    assert out["deltas"]["yawn"]["direction"] == "same"


def test_compare_zero_previous_is_na_not_crash():
    """Previous value 0 -> pct undefined (None), not a divide-by-zero crash."""
    prev = SessionSummary(session_id="a", date="2026-10-21", counts={"drink": 0})
    today = SessionSummary(session_id="b", date="2026-10-22", counts={"drink": 3})
    out = compare(today, prev)
    assert out["deltas"]["drink"]["pct_change"] is None


# ---------------------------------------------------------------- report


def test_report_template_has_bilingual_highlights():
    """report() returns EN+KO text and up to 3 observation-based highlights."""
    agent = NunchiAgent(vision=None)
    summ = SessionSummary(session_id="s", date="2026-10-22",
                          seconds={"forward_head": 840.0}, counts={"blink": 950},
                          nudges_sent=4, nudges_suppressed=7)
    out = agent.report(summ, None)
    assert out["text_en"] and out["text_ko"]
    assert 1 <= len(out["highlights"]) <= 3
    assert "observations only" in out["text_en"].lower()


def test_report_uses_day_over_day_when_previous_exists():
    """With a previous day, the report leads with comparison lines."""
    agent = NunchiAgent(vision=None)
    prev = SessionSummary(session_id="a", date="2026-10-21", seconds={"forward_head": 400.0})
    today = SessionSummary(session_id="b", date="2026-10-22", seconds={"forward_head": 600.0})
    out = agent.report(today, prev)
    assert out["comparison"]["has_previous"] is True
    assert any("vs yesterday" in h for h in out["highlights"])
