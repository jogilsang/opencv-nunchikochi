"""Time-ordered agent scenarios. Each asserts that OpenCV evidence changes the action.

Coverage: normal (>=2), exception/edge (>=2), error handling (>=1), plus the five
required policy scenarios and the Agentic-Vision trace proof.
"""
from __future__ import annotations

from .conftest import ev, frame, load_fixture

# ---------------------------------------------------------------- normal paths


def test_normal_good_frame_does_nothing(agent, ctx):
    """NORMAL 1: a clean frame with a brief event and no sustained signal -> action none."""
    dec = agent.decide(ctx, frame(5.0, events=[ev("blink", 4.9, 5.0, 0.9)]))
    assert dec.action == "none"
    assert dec.reason == "normal"
    assert not dec.needs_human


def test_normal_ok_fixture_from_dict(agent, ctx):
    """NORMAL 2: the shipped ok fixture (as a dict) decodes and yields a valid Decision."""
    dec = agent.decide(ctx, load_fixture("frame_result_ok"))
    # head_tilt event present but only ~2.5s -> not yet sustained -> no nudge
    assert dec.action in ("none",)
    assert dec.tool_calls  # at least the window tool was consulted


# --------------------------------------------- (1) sustained signal -> nudge


def test_sustained_forward_head_triggers_nudge(agent, ctx):
    """POLICY 1: forward_head ongoing past sustained_min_s -> a nudge fires (vision changed action)."""
    # ongoing forward_head starting at t=0
    agent.decide(ctx, frame(10.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    dec = agent.decide(ctx, frame(200.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    assert dec.action == "nudge"
    assert dec.reason == "sustained:forward_head"
    assert any(tc["tool"] == "send_nudge" for tc in dec.tool_calls)
    assert dec.evidence["duration_s"] >= 180.0
    assert dec.message and dec.message_ko  # EN + KO
    # observation-based wording, not a diagnosis
    assert "tired" not in dec.message.lower()


def test_nudge_cooldown_suppresses_second(agent, ctx):
    """POLICY 1b: a second qualifying frame within cooldown is suppressed, not re-nudged."""
    agent.decide(ctx, frame(10.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    first = agent.decide(ctx, frame(200.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    assert first.action == "nudge"
    second = agent.decide(ctx, frame(260.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    assert second.action == "suppress_focus"
    assert second.reason.startswith("cooldown")
    assert ctx.nudges_sent == 1


def test_daily_cap_blocks_nudges(agent, ctx):
    """POLICY 1c: once the daily cap is hit, sustained signals are suppressed."""
    agent.config.daily_nudge_cap = 1
    agent.decide(ctx, frame(10.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    agent.decide(ctx, frame(200.0, events=[ev("forward_head", 0.0, None, 0.9)]))  # nudge #1
    # a different sustained behaviour, past cooldown by type but over the cap
    agent.decide(ctx, frame(205.0, events=[ev("head_tilt", 5.0, None, 0.9)]))
    dec = agent.decide(ctx, frame(400.0, events=[ev("head_tilt", 5.0, None, 0.9)]))
    assert dec.action == "suppress_focus"
    assert dec.reason.startswith("daily_cap")


# ----------------------------------------------- (2) focus window -> suppress


def test_focus_window_suppresses(agent, ctx):
    """POLICY 2: a long quiet stretch (steady roll, low blink) -> suppress_focus."""
    # feed quiet frames so the window sees low spread + low blink rate
    for t in (10.0, 40.0, 70.0, 100.0, 130.0):
        agent.decide(ctx, frame(t, roll=1.0))
    dec = agent.decide(ctx, frame(160.0, roll=1.2))
    assert dec.action == "suppress_focus"
    assert dec.reason == "focus_window"
    assert any(tc["tool"] == "get_metrics_window" for tc in dec.tool_calls)


# ------------------------------- (3) quality bad -> recalibration / confirm


def test_quality_dark_requests_recalibration(agent, ctx):
    """POLICY 3: a dark/no-face frame changes the action to request_recalibration."""
    dec = agent.decide(ctx, load_fixture("frame_result_dark"))
    assert dec.action == "request_recalibration"
    assert dec.reason.startswith("quality:")
    assert any(tc["tool"] == "get_quality" for tc in dec.tool_calls)
    assert any(tc["tool"] == "request_recalibration" for tc in dec.tool_calls)
    assert "light" in dec.message.lower() or "face" in dec.message.lower()


def test_repeated_bad_quality_escalates_to_confirmation(agent, ctx):
    """POLICY 3b: repeated bad-quality frames -> ask_confirmation (human-in-the-loop)."""
    for _ in range(2):
        agent.decide(ctx, frame(1.0, face=False, ok=False, issues=["too_dark", "no_face"]))
    dec = agent.decide(ctx, frame(2.0, face=False, ok=False, issues=["too_dark", "no_face"]))
    assert dec.action == "ask_confirmation"
    assert dec.needs_human
    assert ctx.pending_confirmation is not None


# ------------------------------- (4) low confidence -> ask + human resolution


def test_low_confidence_asks_confirmation(agent, ctx):
    """POLICY 4: a borderline-confidence event asks the user to confirm."""
    dec = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]))
    assert dec.action == "ask_confirmation"
    assert dec.needs_human
    assert "drink" in dec.message.lower()
    assert ctx.pending_confirmation["behavior"] == "drink"


def test_denied_confirmation_raises_threshold_and_cancels(agent, ctx):
    """POLICY 4b: if the human denies, raise the threshold and cancel the event."""
    agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]))
    out = agent.resolve_confirmation(ctx, confirmed=False)
    assert out["confirmed"] is False
    assert out["event_cancelled"] is True
    assert ctx.conf_threshold["drink"] > 0.5  # raised
    # the same borderline reading no longer asks (below raised threshold band)
    dec = agent.decide(ctx, frame(90.0, events=[ev("drink", 89.0, 90.0, 0.5)]))
    assert dec.action != "ask_confirmation"


def test_confirmed_confirmation_keeps_threshold(agent, ctx):
    """POLICY 4c: if the human confirms, the threshold is unchanged."""
    agent.decide(ctx, frame(30.0, events=[ev("yawn", 29.0, 30.0, 0.55)]))
    out = agent.resolve_confirmation(ctx, confirmed=True)
    assert out["confirmed"] is True
    assert "yawn" not in ctx.conf_threshold


# --------------------------------------------------- (5) away -> stay silent


def test_away_stays_silent(agent, ctx):
    """POLICY 5: user away (no face, otherwise fine) -> silent suppress, remembers departure."""
    dec = agent.decide(ctx, frame(50.0, face=False, persons=0, ok=True, issues=[]))
    assert dec.action == "suppress_focus"
    assert dec.reason == "away"
    assert dec.message == ""  # nothing shown
    assert ctx.away_since_t == 50.0


def test_return_from_away_clears_marker(agent, ctx):
    """POLICY 5b: returning clears the away marker so normal flow resumes."""
    agent.decide(ctx, frame(50.0, face=False, persons=0, ok=True, issues=[]))
    agent.decide(ctx, frame(55.0, events=[ev("blink", 54.9, 55.0, 0.9)]))
    assert ctx.away_since_t is None


# ------------------------------------------------- do-not-disturb suppresses


def test_do_not_disturb_suppresses_nudges(agent, ctx):
    """DND: even a sustained signal is suppressed when do-not-disturb is on."""
    ctx.do_not_disturb = True
    agent.decide(ctx, frame(10.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    dec = agent.decide(ctx, frame(300.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    assert dec.action == "suppress_focus"
    assert dec.reason == "do_not_disturb"
    assert ctx.nudges_sent == 0
