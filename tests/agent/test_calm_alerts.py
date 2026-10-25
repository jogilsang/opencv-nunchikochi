"""A11 part 1: alert calming — hourly nudge/confirm caps, no same-kind confirm in a
row, transient-quality debounce, and the suppressed-signal digest. No images anywhere.

The user feedback was "alerts feel too real-time". These tests pin the quiet defaults
to numbers a reviewer can read: over a one-hour simulated session a never-easing posture
problem produces at most `max_nudges_per_hour` nudges, and borderline events produce at
most `max_confirms_per_hour` confirm toasts.
"""
from __future__ import annotations

from nunchi.agent import AgentContext, NunchiAgent, PolicyConfig

from .conftest import ev, frame

FRAME = object()


def _agent(**cfg_kw):
    cfg = PolicyConfig(**cfg_kw)
    return NunchiAgent(vision=None, mode="deterministic", config=cfg), cfg


# ----------------------------------------------------------- normal (2 nudge caps)

def test_one_hour_sustained_posture_yields_at_most_three_nudges():
    """A posture problem held for a full hour nudges <= max_nudges_per_hour (default 3)."""
    agent, cfg = _agent(sustained_min_s=180.0, focus_min_quiet_s=1e9)  # disable focus suppression
    ctx = AgentContext(session_id="h")
    nudges = 0
    # one ongoing forward_head for the whole hour; sample every 60 s
    for t in range(0, 3600, 60):
        fr = frame(float(t), events=[ev("forward_head", 0.0, None, 0.9)])
        dec = agent.decide(ctx, fr, None)
        if dec.action == "nudge":
            nudges += 1
    assert nudges <= cfg.max_nudges_per_hour
    assert nudges >= 1  # it should still speak up at least once
    # suppressed posture signals were counted, not lost (digest keeps the record)
    assert sum(v for k, v in ctx.suppressed_digest.items() if "forward_head" in k) > 0


def test_low_confidence_confirms_capped_per_hour_and_no_same_kind_in_a_row():
    """Borderline events ask at most max_confirms_per_hour and never the same kind twice
    back to back."""
    agent, cfg = _agent(second_look_enabled=False, sustained_min_s=1e9, focus_min_quiet_s=1e9)
    ctx = AgentContext(session_id="h")
    asks = 0
    last_about = None
    repeated_same_kind = 0
    # alternate drink/yawn borderline events every 120 s for an hour; resolve each ask as
    # "yes" so thresholds are not raised (isolates the rate cap, not the deny path)
    behaviours = ["drink", "yawn"]
    for i, t in enumerate(range(100, 3700, 120)):
        b = behaviours[i % 2]
        fr = frame(float(t), events=[ev(b, float(t) - 1, float(t), 0.5)])
        dec = agent.decide(ctx, fr, None)
        if dec.action == "ask_confirmation":
            asks += 1
            about = ctx.pending_confirmation["about"] if ctx.pending_confirmation else None
            if about is not None and about == last_about:
                repeated_same_kind += 1
            last_about = about
            agent.resolve_confirmation(ctx, True)
    assert asks <= cfg.max_confirms_per_hour
    assert repeated_same_kind == 0


# ----------------------------------------------------------- exceptions

def test_transient_marginal_quality_stays_silent():
    """A brief marginal-quality frame WITH a face present does not warn (anti-nag)."""
    agent, _ = _agent(quality_warn_min_sustained_s=30.0)
    ctx = AgentContext(session_id="q")
    # face still visible but the frame is a bit dark/blurry -> transient, stay quiet
    dec = agent.decide(ctx, frame(5.0, face=True, ok=False, issues=["blurry"]), None)
    assert dec.action == "none"
    assert dec.reason == "quality_transient_suppressed"
    assert ctx.suppressed_digest.get("quality_transient", 0) == 1


def test_no_face_frame_still_requests_recalibration_immediately():
    """An unusable (no-face) frame is actionable and gets a single recalibration request,
    not the transient-silence path (that would hide a fixable setup problem)."""
    agent, _ = _agent(quality_warn_min_sustained_s=30.0)
    ctx = AgentContext(session_id="q")
    # face absent but with a quality issue -> NOT the 'away' path; a real quality problem
    dec = agent.decide(ctx, frame(5.0, face=False, ok=False,
                                  issues=["too_dark", "no_face"]), None)
    assert dec.action == "request_recalibration"


def test_sustained_marginal_quality_warns_after_debounce():
    """Marginal quality that persists past the debounce does surface a recalibration."""
    agent, _ = _agent(quality_warn_min_sustained_s=30.0)
    ctx = AgentContext(session_id="q")
    bad = {"face": True, "ok": False, "issues": ["blurry"]}
    agent.decide(ctx, frame(0.0, **bad), None)      # starts the bad-quality run (silent)
    dec = agent.decide(ctx, frame(31.0, **bad), None)  # 31 s later, past the 30 s debounce
    assert dec.action == "request_recalibration"


# ----------------------------------------------------------- error / old field

def test_hour_window_counts_only_recent_nudges():
    """_within_hour is a rolling window: a nudge older than 3600 s no longer counts."""
    ctx = AgentContext(session_id="w")
    ctx.nudge_ts = [10.0, 20.0, 4000.0]
    assert ctx._within_hour(ctx.nudge_ts, now_t=4000.0) == 1   # only the 4000 one is "now"
    assert ctx._within_hour(ctx.nudge_ts, now_t=25.0) == 2
