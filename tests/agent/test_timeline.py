"""A11 parts 2-3: per-window bad-posture timeline + multi-session trend. Numbers only.

The user wants a report of how many bad-posture events happened per 5/10/30/60 min, and,
on the next run, to see whether they are getting better than their recent sessions.
"""
from __future__ import annotations

from nunchi.agent import SummaryAccumulator, compare, summary_dict
from nunchi.contracts import SessionSummary

from .conftest import ev, frame


def _acc_with(intervals: list[tuple[str, float, float]], *, end_t: float) -> SummaryAccumulator:
    """Build an accumulator from closed (type, start, end) bad-posture intervals.

    The accumulator is finalized (so `.timeline()` is valid); the finalized summary is
    stashed on `.summary` for convenience.
    """
    acc = SummaryAccumulator(session_id="s", date="2026-10-22")
    acc.add_frame(frame(0.0))  # session starts at t=0 (so the timeline buckets from 0)
    for typ, s, e in intervals:
        acc.add_frame(frame(e, events=[ev(typ, s, e, 0.9)]))
    acc.summary = acc.finalize(end_t=end_t)  # type: ignore[attr-defined]
    return acc


# ----------------------------------------------------------- normal

def test_timeline_buckets_counts_and_seconds_correctly():
    """Bad-posture events land in the right 5/10/30/60-minute windows with correct seconds."""
    # 3 events: at 0-41s, at 320-360s (inside 2nd 5m window), at 700-760s (2nd 10m window)
    acc = _acc_with(
        [("forward_head", 0.0, 41.0), ("head_tilt", 320.0, 360.0),
         ("forward_head", 700.0, 760.0)],
        end_t=1200.0,
    )
    tl = acc.timeline()
    bp = tl["bad_posture"]
    # 5-minute windows: window0 [0,300) has 1 event/41s; window1 [300,600) has 1 event/40s
    assert bp["5m"][0] == {"start_s": 0.0, "events": 1, "seconds": 41.0}
    assert bp["5m"][1] == {"start_s": 300.0, "events": 1, "seconds": 40.0}
    # 10-minute window0 [0,600) holds the first two events (2), window1 [600,1200) the third
    assert bp["10m"][0]["events"] == 2
    assert bp["10m"][1]["events"] == 1
    # deep_blink is excluded from bad posture
    acc2 = SummaryAccumulator(session_id="s", date="2026-10-22")
    acc2.add_frame(frame(0.0))
    acc2.add_frame(frame(10.0, events=[ev("forward_head", 0.0, 10.0, 0.9)]))
    acc2.add_frame(frame(20.0, events=[ev("deep_blink", 15.0, 20.0, 0.9)]))
    acc2.finalize(end_t=1200.0)
    assert acc2.timeline()["bad_posture"]["5m"][0]["events"] == 1  # deep_blink not counted


def test_trend_improving_over_five_sessions():
    """Today's per-hour rate below the 5-session average reads as improving."""
    # today: 2 bad-posture events in a 1-hour session -> 2.0/h
    today_acc = _acc_with([("forward_head", 0.0, 30.0), ("head_tilt", 1800.0, 1830.0)],
                          end_t=3600.0)
    today = SessionSummary(session_id="s", date="2026-10-22", duration_s=3600.0,
                           counts={**today_acc.counts})
    today_rate = today_acc.timeline()["per_hour_rate"]
    assert today_rate == 2.0
    # five prior sessions with higher rates (worse): 6,7,5,8,6 /h
    history = [{"timeline": {"per_hour_rate": r}} for r in (6.0, 7.0, 5.0, 8.0, 6.0)]
    out = compare(today, None, history=history, today_rate=today_rate)
    assert out["trend"]["direction"] == "improving"
    assert out["trend"]["n"] == 5
    assert out["trend"]["baseline_rate"] == 6.4
    assert "2.0/h" in out["trend"]["line_en"]
    assert out["trend"]["line_ko"]  # KO present


# ----------------------------------------------------------- exceptions

def test_empty_session_has_zero_events_and_null_rate():
    """A session with no events: empty buckets, per_hour_rate null even if long."""
    acc = SummaryAccumulator(session_id="s", date="2026-10-22")
    acc.add_frame(frame(0.0))
    acc.finalize(end_t=3600.0)
    tl = acc.timeline()
    assert tl["per_hour_rate"] == 0.0  # long session, zero events -> 0/h (a real number)
    assert all(row["events"] == 0 for row in tl["bad_posture"]["5m"])


def test_short_session_under_ten_minutes_has_null_rate():
    """Sessions under 10 minutes report per_hour_rate = None (too short to extrapolate)."""
    acc = _acc_with([("forward_head", 0.0, 30.0)], end_t=300.0)  # 5-minute session
    tl = acc.timeline()
    assert tl["per_hour_rate"] is None
    # and the trend is "na" when today's rate is unknown, even with history present
    today = SessionSummary(session_id="s", date="2026-10-22", duration_s=300.0,
                           counts={**acc.counts})
    out = compare(today, None, history=[{"timeline": {"per_hour_rate": 5.0}}],
                  today_rate=tl["per_hour_rate"])
    assert out["trend"]["direction"] == "na"
    assert "이전 기록" in out["trend"]["line_ko"]


# ----------------------------------------------------------- error / old summary

def test_old_summary_without_timeline_degrades_gracefully():
    """An old persisted summary (no timeline field) compares with trend 'na', no crash."""
    today = SessionSummary(session_id="s", date="2026-10-22", duration_s=1800.0,
                           counts={"forward_head": 3})
    # history entries are legacy dicts with NO 'timeline' key, and a legacy object
    legacy_dict = {"session_id": "old", "counts": {"forward_head": 10}}  # no timeline
    out = compare(today, None, history=[legacy_dict], today_rate=None)
    assert out["trend"]["direction"] == "na"
    assert out["has_previous"] is False
    # summary_dict with no accumulator omits timeline (backward compatible)
    d = summary_dict(today)
    assert "timeline" not in d
    # summary_dict WITH an accumulator adds a numbers-only timeline
    acc = _acc_with([("forward_head", 0.0, 30.0)], end_t=1800.0)
    d2 = summary_dict(acc.summary, acc)  # type: ignore[attr-defined]
    assert "timeline" in d2 and "bad_posture" in d2["timeline"]
