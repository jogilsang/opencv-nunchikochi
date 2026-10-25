"""Deterministic decision policy. OWNER: agent tab.

Turns one FrameResult (OpenCV output) plus the running AgentContext into a
Decision, calling tools along the way. This is the *perceive -> decide -> act*
core of Agentic Vision: the visual evidence here directly changes which tools
fire and what action is taken.

Priority order (first match wins), chosen so safety/robustness beats nagging:
  0. away            -> stay silent (suppress), remember departure
  1. quality bad     -> get_quality; second_look(enhance) first (active perception);
                        if the re-analysis clears it -> none (no human needed),
                        else request_recalibration; repeated -> ask_confirmation
  2. do-not-disturb  -> suppress
  3. low confidence  -> second_look(zoom_face/strict) first; if confidence moves
                        out of band -> auto confirm/reject (no human); else ask_confirmation
  4. focus window    -> suppress_focus
  5. sustained signal-> send_nudge (respect per-type cooldown + daily cap)
  6. otherwise       -> none

Active perception (`second_look`) calls OpenCV again (`vision.analyze_variant`)
BEFORE escalating to a human, so a re-analysis can stand in for the user. If
vision is absent or lacks `analyze_variant`, it is skipped (trace: no_variant)
and the classic behaviour is used.

All numeric knobs live in PolicyConfig (context.py); this module holds only logic.
"""
from __future__ import annotations

from typing import Any

from ..contracts import Decision, FrameResult, now_ms
from . import tools
from .context import SUSTAINED_BEHAVIORS, AgentContext, PolicyConfig


def _issue_guidance(issues: list[str], lang_ko: bool = False) -> tuple[str, str]:
    """Observation-based guidance for a quality issue (no diagnosis)."""
    first = issues[0] if issues else "no_face"
    table = {
        "too_dark": ("The camera looks dark. More light on your face would help.",
                     "화면이 어두워요. 얼굴 쪽에 빛을 더 주면 좋아요."),
        "too_bright": ("The camera looks washed out. Try reducing backlight.",
                       "화면이 너무 밝아요. 뒤쪽 빛을 줄여볼까요?"),
        "blurry": ("The image is blurry. A steadier camera would help.",
                   "화면이 흐릿해요. 카메라를 고정하면 좋아요."),
        "face_too_small": ("Your face looks small. Sitting a bit closer would help.",
                           "얼굴이 작게 보여요. 조금 더 가까이 앉아볼까요?"),
        "face_cut_off": ("Your face is partly out of frame. Re-centering would help.",
                         "얼굴이 화면에서 잘렸어요. 가운데로 맞춰볼까요?"),
        "no_face": ("I can't see a face right now.",
                    "지금은 얼굴이 보이지 않아요."),
        "multiple_faces": ("More than one face is in view.",
                           "화면에 얼굴이 여러 개 보여요."),
    }
    en, ko = table.get(first, table["no_face"])
    return en, ko


def _nudge_text(behavior: str) -> tuple[str, str]:
    """Observation-based nudge wording, never a diagnosis."""
    table = {
        "forward_head": (
            ("You have been leaning toward the screen for a while. "
             "Easing back might feel better."),
            "한동안 화면 쪽으로 기울어 있었어요. 등을 조금 펴볼까요?",
        ),
        "head_tilt": (
            "Your head has been tilted for a while. Straightening up might help.",
            "고개가 한참 기울어 있었어요. 바로 세워볼까요?",
        ),
        "deep_blink": (
            ("Your blinks have been longer than usual for a while. "
             "A short look away might help."),
            "한동안 눈 감는 시간이 평소보다 길었어요. 잠깐 먼 곳을 봐볼까요?",
        ),
    }
    return table.get(behavior, ("Time for a small posture check?",
                                "잠깐 자세를 점검해볼까요?"))


def _confirm_text(behavior: str) -> tuple[str, str, str]:
    """(about-tag, question_en, question_ko) for a low-confidence event."""
    table = {
        "drink": ("drink", "Did you just take a drink?", "방금 물을 마셨나요?"),
        "yawn": ("yawn", "Did you just yawn?", "방금 하품을 했나요?"),
        "forward_head": ("forward_head", "Are you leaning toward the screen?",
                         "지금 화면 쪽으로 기울이고 있나요?"),
        "head_tilt": ("head_tilt", "Is your head tilted right now?", "지금 고개를 기울이고 있나요?"),
    }
    return table.get(behavior, (behavior, f"Did a '{behavior}' just happen?",
                                f"방금 '{behavior}' 동작이 있었나요?"))


def _primary_event(result: FrameResult):
    """Pick the most salient ongoing event (highest confidence, ongoing preferred)."""
    if not result.events:
        return None
    ongoing = [e for e in result.events if e.end is None]
    pool = ongoing or result.events
    return max(pool, key=lambda e: (e.confidence or 0.0))


def _try_second_look(vision: Any, state: Any, frame_bgr: Any, result: FrameResult,
                     cfg: PolicyConfig, ctx: AgentContext, tcalls: list[dict[str, Any]],
                     variant: str, *, behavior: str | None = None) -> dict[str, Any] | None:
    """Call the second_look tool if active perception is possible; record a trace entry.

    Returns the tool dict, or None if skipped (disabled / no vision / no frame).
    Any tool exception is contained here (trace: error) and returns None so the
    caller falls back to the classic path.
    """
    if not cfg.second_look_enabled or vision is None or frame_bgr is None:
        tcalls.append({"tool": "second_look", "args": {"variant": variant},
                       "result_summary": "skipped:no_variant"})
        return None
    try:
        out = tools.second_look(vision, state, frame_bgr, result.t, variant,
                                before=result, behavior=behavior,
                                conf_lo=cfg.low_conf_lo, conf_hi=cfg.low_conf_hi)
    except Exception as exc:  # noqa: BLE001 - contain tool errors, fall back
        tcalls.append({"tool": "second_look", "args": {"variant": variant},
                       "result_summary": f"error:{type(exc).__name__}"})
        return None
    if not out.get("available"):
        tcalls.append({"tool": "second_look", "args": {"variant": variant},
                       "result_summary": "skipped:no_variant"})
        return None
    ctx.second_looks += 1
    summary = out.get("reason", out.get("verdict", ""))
    tcalls.append({"tool": "second_look", "args": {"variant": variant},
                   "result_summary": summary})
    if out.get("resolved"):
        ctx.second_look_resolved += 1
    return out


def _decide_quality(result: FrameResult, ctx: AgentContext, cfg: PolicyConfig,
                    tcalls: list[dict[str, Any]], *, vision: Any = None,
                    state: Any = None, frame_bgr: Any = None) -> Decision | None:
    q = result.quality
    quality_bad = (not q.ok) or bool(q.issues) or (not result.face_present)
    if not quality_bad:
        ctx.bad_quality_streak = 0
        ctx.bad_quality_since_t = None
        return None

    # A11: a transient *marginal* bad frame should stay quiet — but only when a face is
    # still present (e.g. briefly dark/blurry). A frame with no usable face is actionable
    # (the user can fix lighting/position) and still gets a single recalibration request;
    # repeats are rate-limited by the existing streak/confirm logic, so it does not nag.
    face_usable = result.face_present and "no_face" not in (q.issues or [])
    if ctx.bad_quality_since_t is None:
        ctx.bad_quality_since_t = result.t
    bad_for = result.t - ctx.bad_quality_since_t
    ctx.bad_quality_streak += 1
    if face_usable and bad_for < cfg.quality_warn_min_sustained_s:
        ctx.note_suppressed("quality_transient")
        tcalls.append({"tool": "suppress", "args": {"kind": "quality_transient"},
                       "result_summary": f"suppressed:bad_for={bad_for:.0f}s"})
        return Decision(action="none", reason="quality_transient_suppressed",
                        tool_calls=tcalls,
                        evidence={"bad_for_s": round(bad_for, 1),
                                  "min_s": cfg.quality_warn_min_sustained_s})

    qinfo = tools.get_quality(result)
    tcalls.append({"tool": "get_quality", "args": {}, "result_summary":
                   ("ok" if qinfo["ok"] else ",".join(qinfo["issues"]) or "no_face")})
    issues = list(q.issues) or (["no_face"] if not result.face_present else [])

    # repeated bad quality -> escalate to a human confirmation
    if ctx.bad_quality_streak >= cfg.quality_repeat_for_confirm:
        res = tools.ask_confirmation(
            "The camera quality has been poor for a bit. Is your setup OK?",
            "카메라 상태가 잠깐 좋지 않았어요. 자리 세팅이 괜찮은가요?",
            about="quality_repeated",
        )
        tcalls.append({"tool": "ask_confirmation", "args": {"about": "quality_repeated"},
                       "result_summary": "asked"})
        ctx.confirmations_asked += 1
        ctx.pending_confirmation = {"about": "quality_repeated", "behavior": None, "frame_t": result.t}
        return Decision(
            action="ask_confirmation", message=res["question_en"], message_ko=res["question_ko"],
            reason=f"quality_repeated:{ctx.bad_quality_streak}", needs_human=True,
            tool_calls=tcalls, evidence={"issues": issues, "streak": ctx.bad_quality_streak},
        )

    # active perception: re-analyse with OpenCV (enhance) BEFORE asking for recalibration
    sl = _try_second_look(vision, state, frame_bgr, result, cfg, ctx, tcalls, "enhance")
    if sl is not None and sl.get("resolved"):
        # OpenCV re-analysis stood in for the user: the cleaned frame is fine.
        ctx.bad_quality_streak = 0
        return Decision(
            action="none", reason="second_look:quality_cleared",
            tool_calls=tcalls,
            evidence={"issues_before": issues, "variant": "enhance",
                      "after": sl.get("after", {}),
                      "note": "OpenCV re-analysis replaced human/recalibration"},
        )

    # first/second bad frame (or re-analysis did not clear it) -> request recalibration
    res = tools.request_recalibration(reason="quality:" + (issues[0] if issues else "no_face"))
    tcalls.append({"tool": "request_recalibration", "args": {"reason": res["reason"]},
                   "result_summary": "requested"})
    ctx.recalibrations += 1
    en, ko = _issue_guidance(issues)
    return Decision(
        action="request_recalibration", message=en, message_ko=ko,
        reason="quality:" + (issues[0] if issues else "no_face"),
        tool_calls=tcalls, evidence={"issues": issues, "brightness": q.brightness,
                                     "sharpness": q.sharpness, "face_px": q.face_px},
    )


def _update_sustained(result: FrameResult, ctx: AgentContext) -> dict[str, float]:
    """Track how long each sustained behaviour has been ongoing; return durations."""
    ongoing_types = {e.type for e in result.events if e.end is None}
    # start timers for newly-ongoing sustained behaviours
    for b in SUSTAINED_BEHAVIORS:
        if b in ongoing_types and b not in ctx.sustained_since:
            # use the event start if available, else now
            evs = [e for e in result.events if e.type == b and e.end is None]
            ctx.sustained_since[b] = evs[0].start if evs else result.t
    # clear timers for behaviours no longer ongoing
    for b in list(ctx.sustained_since):
        if b not in ongoing_types:
            del ctx.sustained_since[b]
    return {b: result.t - start for b, start in ctx.sustained_since.items()}


def _cooldown_for(behavior: str, cfg: PolicyConfig) -> float:
    return cfg.nudge_cooldown_s.get(behavior, cfg.nudge_cooldown_s.get("default", 600.0))


def decide(result: FrameResult, ctx: AgentContext, cfg: PolicyConfig,
           *, vision: Any = None, state: Any = None,
           frame_bgr: Any = None) -> tuple[Decision, dict[str, Any]]:
    """Run the deterministic decision loop for one frame.

    `vision`/`state`/`frame_bgr` enable active perception (second_look). `frame_bgr`
    is a request-scoped memory reference passed only to vision; it is never stored,
    returned, or traced. Returns (Decision, trace_fields). Mutates ctx.
    """
    tcalls: list[dict[str, Any]] = []

    # ---- 0. away: user not present -> stay silent, remember departure ----
    if not result.face_present and not result.quality.issues and result.persons == 0 \
            and result.quality.ok:
        # face absent but frame otherwise fine -> treat as away (not a quality problem)
        if ctx.away_since_t is None:
            ctx.away_since_t = result.t
        tools.suppress(reason="user_away", kind="away")
        tcalls.append({"tool": "suppress", "args": {"kind": "away"}, "result_summary": "suppressed"})
        ctx.nudges_suppressed += 1
        dec = Decision(action="suppress_focus", message="", message_ko="", reason="away",
                       tool_calls=tcalls, evidence={"away_since_t": ctx.away_since_t})
        return dec, {"tool": "suppress", "result_summary": "away"}
    # returned from away
    if result.face_present and ctx.away_since_t is not None:
        ctx.away_since_t = None

    # ---- 1. quality bad ----
    qdec = _decide_quality(result, ctx, cfg, tcalls,
                           vision=vision, state=state, frame_bgr=frame_bgr)
    if qdec is not None:
        # record event summary for the window
        ctx.record_recent({"t": result.t, "type": "quality_bad",
                           "confidence": 0.0})
        return qdec, {"tool": tcalls[-1]["tool"], "result_summary": qdec.reason}

    # keep a rolling summary of this frame's primary event for the window tool
    prim = _primary_event(result)
    if prim is not None:
        ctx.record_recent({"t": result.t, "type": prim.type,
                           "confidence": prim.confidence,
                           "head_roll_deg": result.metrics.head_roll_deg})

    # ---- 2. do-not-disturb ----
    if ctx.do_not_disturb:
        tools.suppress(reason="do_not_disturb", kind="dnd")
        tcalls.append({"tool": "suppress", "args": {"kind": "dnd"}, "result_summary": "suppressed"})
        ctx.nudges_suppressed += 1
        return (Decision(action="suppress_focus", reason="do_not_disturb",
                         tool_calls=tcalls, evidence={}),
                {"tool": "suppress", "result_summary": "dnd"})

    # ---- 3. low confidence -> second_look first, then ask_confirmation ----
    if prim is not None:
        thr_lo = ctx.conf_threshold.get(prim.type, cfg.low_conf_lo)
        conf = prim.confidence or 0.0
        if thr_lo <= conf <= cfg.low_conf_hi and ctx.pending_confirmation is None:
            # active perception: look again with OpenCV before asking the human
            sl = _try_second_look(vision, state, frame_bgr, result, cfg, ctx, tcalls,
                                  cfg.low_conf_variant, behavior=prim.type)
            if sl is not None and sl.get("resolved"):
                verdict = sl.get("verdict", "")
                # OpenCV re-analysis settled it: no human needed
                return (Decision(
                    action="none",
                    reason=f"second_look:confidence_{verdict}:{prim.type}",
                    tool_calls=tcalls,
                    evidence={"behavior": prim.type, "confidence_before": conf,
                              "confidence_after": sl.get("after", {}).get("confidence"),
                              "verdict": verdict, "variant": cfg.low_conf_variant,
                              "note": "OpenCV re-analysis replaced human confirmation"}),
                        {"tool": "second_look", "result_summary": f"{verdict}:{prim.type}"})
            # unchanged (or no variant) -> consider asking the human, but keep it rare (A11)
            about, qen, qko = _confirm_text(prim.type)
            confirms_this_hour = ctx._within_hour(ctx.confirm_ts, result.t)
            over_confirm_cap = confirms_this_hour >= cfg.max_confirms_per_hour
            same_kind_in_a_row = (cfg.confirm_no_repeat_kind
                                   and ctx.last_confirm_about == about)
            if over_confirm_cap or same_kind_in_a_row:
                reason = "confirm_hourly_cap" if over_confirm_cap else "confirm_same_kind"
                ctx.note_suppressed(f"{reason}:{prim.type}")
                tools.suppress(reason=f"{reason}:{prim.type}", kind="confirm_rate")
                tcalls.append({"tool": "suppress",
                               "args": {"kind": "confirm_rate", "reason": reason},
                               "result_summary": "suppressed"})
                ctx.nudges_suppressed += 1
                return (Decision(action="suppress_focus",
                                 reason=f"{reason}:{prim.type}", tool_calls=tcalls,
                                 evidence={"behavior": prim.type,
                                           "confirms_this_hour": confirms_this_hour}),
                        {"tool": "suppress", "result_summary": reason})
            tools.ask_confirmation(qen, qko, about=about, behavior=prim.type)
            tcalls.append({"tool": "ask_confirmation", "args": {"about": about},
                           "result_summary": "asked"})
            ctx.confirmations_asked += 1
            ctx.confirm_ts.append(result.t)
            ctx.last_confirm_about = about
            ctx.pending_confirmation = {"about": about, "behavior": prim.type,
                                        "frame_t": result.t}
            return (Decision(action="ask_confirmation", message=qen, message_ko=qko,
                             reason=f"low_confidence:{prim.type}", needs_human=True,
                             tool_calls=tcalls,
                             evidence={"behavior": prim.type, "confidence": conf,
                                       "band": [thr_lo, cfg.low_conf_hi]}),
                    {"tool": "ask_confirmation", "result_summary": f"low_conf:{prim.type}"})

    # ---- 4. focus window -> suppress ----
    win = tools.get_metrics_window(ctx.recent, window_s=cfg.focus_min_quiet_s, now_t=result.t)
    tcalls.append({"tool": "get_metrics_window",
                   "args": {"window_s": cfg.focus_min_quiet_s},
                   "result_summary": f"count={win['count']},roll_spread={win['roll_spread_deg']:.1f}"})
    blink_win = tools.get_metrics_window(ctx.recent, behavior="blink",
                                         window_s=cfg.focus_min_quiet_s, now_t=result.t)
    quiet = (win["roll_spread_deg"] <= cfg.focus_posture_change_max
             and blink_win["rate_per_s"] <= cfg.focus_blink_rate_max
             and result.t >= cfg.focus_min_quiet_s)
    # only treat as focus if there is no sustained posture problem right now
    durations = _update_sustained(result, ctx)
    sustained_now = any(d >= cfg.sustained_min_s for d in durations.values())
    if quiet and not sustained_now:
        tools.suppress(reason="focus_window", kind="focus")
        tcalls.append({"tool": "suppress", "args": {"kind": "focus"}, "result_summary": "suppressed"})
        ctx.in_focus = True
        ctx.nudges_suppressed += 1
        return (Decision(action="suppress_focus", reason="focus_window",
                         tool_calls=tcalls,
                         evidence={"roll_spread_deg": win["roll_spread_deg"],
                                   "blink_rate_per_s": blink_win["rate_per_s"]}),
                {"tool": "suppress", "result_summary": "focus"})
    ctx.in_focus = False

    # ---- 5. sustained signal -> nudge (cooldown + daily cap) ----
    ready: list[tuple[str, float]] = [
        (b, d) for b, d in durations.items() if d >= cfg.sustained_min_s
    ]
    if ready:
        ready.sort(key=lambda bd: bd[1], reverse=True)   # longest-running first
        behavior, dur = ready[0]
        now = now_ms()
        cooldown = _cooldown_for(behavior, cfg)
        last = ctx.last_nudge_ms_by_type.get(behavior, 0)
        under_cap = ctx.nudges_sent < cfg.daily_nudge_cap
        nudges_this_hour = ctx._within_hour(ctx.nudge_ts, result.t)
        under_hour_cap = nudges_this_hour < cfg.max_nudges_per_hour
        cooled = (now - last) >= cooldown * 1000 if last else True
        if under_cap and under_hour_cap and cooled:
            en, ko = _nudge_text(behavior)
            tools.send_nudge(behavior, en, ko, cooldown_s=cooldown)
            tcalls.append({"tool": "send_nudge", "args": {"behavior": behavior},
                           "result_summary": "sent"})
            ctx.last_nudge_ms_by_type[behavior] = now
            ctx.nudges_sent += 1
            ctx.nudge_ts.append(result.t)
            return (Decision(action="nudge", message=en, message_ko=ko,
                             reason=f"sustained:{behavior}", tool_calls=tcalls,
                             evidence={"behavior": behavior, "duration_s": round(dur, 1)},
                             cooldown_s=cooldown),
                    {"tool": "send_nudge", "result_summary": f"nudge:{behavior}"})
        # sustained but on cooldown / over daily cap / over hourly cap -> suppress quietly
        if not under_cap:
            reason = "daily_cap"
        elif not under_hour_cap:
            reason = "hourly_cap"
        else:
            reason = "cooldown"
        ctx.note_suppressed(f"{reason}:{behavior}")
        tools.suppress(reason=f"{reason}:{behavior}", kind="rate")
        tcalls.append({"tool": "suppress", "args": {"kind": "rate", "reason": reason},
                       "result_summary": "suppressed"})
        ctx.nudges_suppressed += 1
        return (Decision(action="suppress_focus", reason=f"{reason}:{behavior}",
                         tool_calls=tcalls, evidence={"behavior": behavior,
                                                      "duration_s": round(dur, 1),
                                                      "nudges_this_hour": nudges_this_hour}),
                {"tool": "suppress", "result_summary": reason})

    # ---- 6. nothing to do ----
    return (Decision(action="none", reason="normal", tool_calls=tcalls,
                     evidence={"events": [e.type for e in result.events]}),
            {"tool": tcalls[-1]["tool"] if tcalls else None, "result_summary": "none"})


def apply_confirmation(ctx: AgentContext, cfg: PolicyConfig, confirmed: bool) -> dict[str, Any]:
    """Resolve the pending human confirmation.

    If the user denies the event, raise that behaviour's confidence threshold so
    the same borderline reading won't ask again, and report the event cancelled.
    """
    pending = ctx.pending_confirmation
    ctx.pending_confirmation = None
    if pending is None:
        return {"resolved": False, "reason": "no_pending"}
    behavior = pending.get("behavior")
    if confirmed:
        return {"resolved": True, "confirmed": True, "behavior": behavior}
    # denied -> raise threshold (cancel this kind of borderline event going forward)
    if behavior:
        cur = ctx.conf_threshold.get(behavior, cfg.low_conf_lo)
        ctx.conf_threshold[behavior] = min(0.95, max(cur, cfg.low_conf_hi) + 0.05)
    return {"resolved": True, "confirmed": False, "behavior": behavior,
            "event_cancelled": True,
            "new_threshold": ctx.conf_threshold.get(behavior) if behavior else None}
