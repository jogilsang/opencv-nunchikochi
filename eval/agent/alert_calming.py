"""A12: measure the alert-calming effect. OWNER: agent tab.

Runs ONE deterministic, synthetic 1-hour desk session (the A11 mix: a mostly-constant
forward-head lean, periodic head tilt, intermittent low-confidence yawn/drink events, and
a stretch of face-present marginal quality) through the real NunchiAgent twice:

  - "before"  = the pre-A11 defaults (commit 1897ea7): 10/10/5-min cooldowns, no hourly
                nudge/confirm caps, no same-kind confirm guard, no quality debounce.
  - "after"   = the current calm defaults (20-min cooldown, <=3 nudges/h, <=2 confirms/h,
                no same-kind in a row, 30-s face-present quality debounce).

Both runs execute the SAME current policy.py; "before" is reproduced by setting the new
knobs to no-op values (so the new code paths are inert) plus the old cooldowns. This is a
synthetic scenario, NOT a real-use measurement.

Outputs a dict of per-run counts (nudge / ask_confirmation / quality warnings /
suppressed-digest) plus the cost of calming (how much later the first repeat alert lands,
and how many "genuinely wanted" repeats were held). Deterministic: no network, no images,
fixed event schedule (no RNG).

Reproduce:
    uv run python eval/agent/alert_calming.py             # prints the table + writes JSON
    uv run python eval/agent/alert_calming.py --json-only  # just rewrite the sample JSON
"""
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from nunchi.agent import (
    AgentContext,
    NunchiAgent,
    PolicyConfig,
    SummaryAccumulator,
    compare,
)
from nunchi.contracts import Event, FrameResult, Metrics, Quality

HERE = pathlib.Path(__file__).resolve().parent
EVAL_DOCS = HERE.parents[1] / "docs" / "eval"

# ---- the synthetic 1-hour session -----------------------------------------
# Deterministic schedule. Frames every 30 s for 3600 s (121 frames). Numbers only.
STEP_S = 30.0
SESSION_S = 3600.0

# A face-present marginal-quality stretch (blurry) from 1200 s to 1260 s (just over the
# 30-s debounce) so "before" warns on it and "after" waits out the transient part.
_QUALITY_BAD_FROM, _QUALITY_BAD_TO = 1200.0, 1265.0

# Low-confidence discrete events (for ask_confirmation): alternate yawn/drink every 300 s.
_LOWCONF_EVERY = 300.0
_LOWCONF_KINDS = ("yawn", "drink")


def _frame(t: float) -> FrameResult:
    """Build one synthetic frame at session-time t (numbers only, no image)."""
    events: list[Event] = []
    quality = Quality(ok=True, brightness=118.0, sharpness=210.0, face_px=96, issues=[])
    face_present = True

    # a nearly-constant forward-head lean for the whole session (the thing worth nudging)
    events.append(Event(type="forward_head", start=0.0, end=None, confidence=0.9))
    # periodic head tilt, ongoing in alternating 600-s blocks
    if int(t // 600) % 2 == 1:
        events.append(Event(type="head_tilt", start=(t // 600) * 600.0, end=None,
                            confidence=0.88))
    # intermittent low-confidence discrete event -> borderline -> confirm candidate
    if t > 0 and abs(t % _LOWCONF_EVERY) < 1e-6:
        kind = _LOWCONF_KINDS[int(t // _LOWCONF_EVERY) % 2]
        events.append(Event(type=kind, start=t - 1.0, end=t, confidence=0.5))
    # a marginal (face-present) bad-quality stretch
    if _QUALITY_BAD_FROM <= t <= _QUALITY_BAD_TO:
        quality = Quality(ok=False, brightness=70.0, sharpness=40.0, face_px=96,
                          issues=["blurry"])

    return FrameResult(
        session_id="calming", t=t, face_present=face_present, persons=1, calibrated=True,
        metrics=Metrics(head_roll_deg=2.0), quality=quality, events=events,
        backend="opencv", cv_version="5.0.0",
    )


def _frames() -> list[FrameResult]:
    n = int(SESSION_S // STEP_S) + 1
    return [_frame(round(i * STEP_S, 3)) for i in range(n)]


# ---- configs ---------------------------------------------------------------

def _before_config() -> PolicyConfig:
    """Pre-A11 defaults (commit 1897ea7), expressed through the current policy by making
    the A11 knobs inert."""
    return PolicyConfig(
        nudge_cooldown_s={"forward_head": 600.0, "head_tilt": 600.0,
                          "deep_blink": 300.0, "default": 600.0},
        max_nudges_per_hour=10**9,        # no hourly cap before A11
        max_confirms_per_hour=10**9,      # no hourly confirm cap before A11
        confirm_no_repeat_kind=False,     # no same-kind guard before A11
        quality_warn_min_sustained_s=0.0,  # no quality debounce before A11
        second_look_enabled=False,        # isolate rate behaviour (no variant auto-resolve)
        focus_min_quiet_s=1e9,            # disable focus suppression so counts are comparable
    )


def _after_config() -> PolicyConfig:
    """Current calm defaults; only the two measurement-isolating knobs match 'before'."""
    return PolicyConfig(second_look_enabled=False, focus_min_quiet_s=1e9)


# ---- one run ---------------------------------------------------------------

def _run(cfg: PolicyConfig) -> dict[str, Any]:
    agent = NunchiAgent(vision=None, mode="deterministic", config=cfg)
    ctx = AgentContext(session_id="calming")
    acc = SummaryAccumulator(session_id="calming", date="2026-10-22")
    counts = {"nudge": 0, "ask_confirmation": 0, "request_recalibration": 0,
              "suppress_focus": 0, "none": 0}
    nudge_ts: list[float] = []
    confirm_ts: list[float] = []
    quality_warn_ts: list[float] = []
    # Cooldown bookkeeping in policy uses now_ms() (wall clock). To replay a full hour
    # deterministically we drive that clock from session time: now_ms() == t*1000. This
    # does not change policy behaviour; it only lets a 1-hour session elapse in the test.
    import nunchi.agent.policy as _policy
    orig_now_ms = _policy.now_ms
    cur_t = {"t": 0.0}
    _policy.now_ms = lambda: int(cur_t["t"] * 1000)  # type: ignore[assignment]
    try:
        for fr in _frames():
            cur_t["t"] = fr.t
            acc.add_frame(fr)
            dec = agent.decide(ctx, fr, None)
            counts[dec.action] = counts.get(dec.action, 0) + 1
            if dec.action == "nudge":
                nudge_ts.append(fr.t)
            elif dec.action == "ask_confirmation":
                confirm_ts.append(fr.t)
                # resolve as "yes" so denial-threshold logic doesn't skew the rate comparison
                agent.resolve_confirmation(ctx, True)
            elif dec.action == "request_recalibration":
                quality_warn_ts.append(fr.t)
    finally:
        _policy.now_ms = orig_now_ms  # type: ignore[assignment]
    acc.finalize(end_t=SESSION_S)
    return {
        "nudges_sent": counts["nudge"],
        "confirms_asked": counts["ask_confirmation"],
        "quality_warnings": counts["request_recalibration"],
        "suppress_decisions": counts["suppress_focus"],
        "silent_frames": counts["none"],
        "suppressed_digest": dict(ctx.suppressed_digest),
        "nudge_ts": nudge_ts,
        "confirm_ts": confirm_ts,
        "quality_warn_ts": quality_warn_ts,
        "total_alerts": counts["nudge"] + counts["ask_confirmation"]
        + counts["request_recalibration"],
        "timeline": acc.timeline(),
    }


# ---- cost of calming -------------------------------------------------------

def _cost_of_calming(before: dict, after: dict) -> dict[str, Any]:
    """What we paid to be quieter: later first-repeat nudge, and held 'wanted' alerts."""
    b_nudge, a_nudge = before["nudge_ts"], after["nudge_ts"]
    # the first nudge should be identical (both fire as soon as sustained); the COST is how
    # much later the SECOND nudge (first repeat) lands under the calmer cooldown.
    def second(ts: list[float]) -> float | None:
        return ts[1] if len(ts) > 1 else None
    b2, a2 = second(b_nudge), second(a_nudge)
    repeat_delay_s = (a2 - b2) if (b2 is not None and a2 is not None) else None
    held_nudges = before["nudges_sent"] - after["nudges_sent"]
    held_confirms = before["confirms_asked"] - after["confirms_asked"]
    held_quality = before["quality_warnings"] - after["quality_warnings"]
    return {
        "first_nudge_same_s": (b_nudge[0] if b_nudge else None,
                               a_nudge[0] if a_nudge else None),
        "first_repeat_nudge_delayed_by_s": repeat_delay_s,
        "held_nudges": held_nudges,
        "held_confirms": held_confirms,
        "held_quality_warnings": held_quality,
        "note": ("Held alerts are not lost: they are counted in suppressed_digest and "
                 "surface in the end-of-session report. 'Genuinely wanted' repeats = the "
                 "held nudges above, i.e. the same posture problem re-announced less often."),
    }


def measure() -> dict[str, Any]:
    before = _run(_before_config())
    after = _run(_after_config())
    return {
        "scenario": {
            "kind": "synthetic (NOT a real-use measurement)",
            "duration_s": SESSION_S, "frame_interval_s": STEP_S,
            "frames": int(SESSION_S // STEP_S) + 1,
            "seed": "none (fixed deterministic schedule)",
            "source": "eval/agent/alert_calming.py::_frames",
            "mix": ("constant forward_head lean; alternating head_tilt 600-s blocks; "
                    "low-confidence yawn/drink every 300 s; face-present marginal quality "
                    f"{_QUALITY_BAD_FROM:.0f}-{_QUALITY_BAD_TO:.0f}s"),
        },
        "before": before,
        "after": after,
        "cost_of_calming": _cost_of_calming(before, after),
    }


# ---- sample timeline / multi-session JSON for web & docs -------------------

def _sample_timeline_json() -> dict[str, Any]:
    """A synthetic end-of-session payload web/docs can quote verbatim: today's per-window
    bad-posture timeline + a 5-session improving trend. Numbers only, no images."""
    today = _run(_after_config())
    tl = today["timeline"]
    today_rate = tl["per_hour_rate"]
    # five synthetic prior sessions, bad-posture per-hour rate trending down (improving)
    history = [{"session": f"s{i}", "timeline": {"per_hour_rate": r}}
               for i, r in enumerate((9.0, 8.0, 7.5, 6.0, 5.5), 1)]
    # today compares as "improving" vs the ~7.2/h baseline
    from nunchi.contracts import SessionSummary
    today_summary = SessionSummary(session_id="today", date="2026-10-22",
                                   duration_s=SESSION_S)
    trend = compare(today_summary, None, history=history, today_rate=today_rate)["trend"]
    return {
        "_note": "synthetic sample for web/docs; numbers only, no images",
        "today": {"session": "today", "timeline": tl},
        "history": history,
        "trend": trend,
    }


# ---- rendering -------------------------------------------------------------

def _table(m: dict[str, Any]) -> str:
    b, a = m["before"], m["after"]
    c = m["cost_of_calming"]
    rows = [
        ("Nudges sent", b["nudges_sent"], a["nudges_sent"]),
        ("Confirm toasts asked", b["confirms_asked"], a["confirms_asked"]),
        ("Quality warnings", b["quality_warnings"], a["quality_warnings"]),
        ("Total alerts", b["total_alerts"], a["total_alerts"]),
        ("Silent frames", b["silent_frames"], a["silent_frames"]),
    ]
    out = ["| Metric | Before (pre-A11) | After (calm) |", "|---|---|---|"]
    for name, bv, av in rows:
        out.append(f"| {name} | {bv} | {av} |")
    out.append("")
    out.append(f"- First nudge fires at the same time in both: {c['first_nudge_same_s']} s.")
    out.append(f"- First repeat nudge is delayed by **{c['first_repeat_nudge_delayed_by_s']} s** "
               "under the calmer cooldown (the cost of being quiet).")
    out.append(f"- Held (not lost) vs before: {c['held_nudges']} nudges, "
               f"{c['held_confirms']} confirms, {c['held_quality_warnings']} quality warnings "
               "— all counted in the suppressed digest and shown in the report.")
    out.append(f"- After-run suppressed digest: `{a['suppressed_digest']}`")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()
    EVAL_DOCS.mkdir(parents=True, exist_ok=True)
    sample = _sample_timeline_json()
    (EVAL_DOCS / "timeline_sample.json").write_text(
        json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json_only:
        print(f"wrote {EVAL_DOCS / 'timeline_sample.json'}")
        return 0
    m = measure()
    (EVAL_DOCS / "alert_calming_result.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(_table(m))
    print(f"\nwrote {EVAL_DOCS / 'alert_calming_result.json'} and "
          f"{EVAL_DOCS / 'timeline_sample.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
