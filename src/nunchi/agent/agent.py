"""NunchiAgent: the perceive->decide->act loop. OWNER: agent tab.

Deterministic mode (default, test baseline) applies rules in `policy.py` using the
seven tools. In `llm` mode the deterministic decision is computed first, and only
on AMBIGUOUS moments (low-confidence confirmation, repeated bad quality, nudge
wording) is an LLM planner asked to propose a plan. The proposal must pass the
same deterministic guardrails (cost/latency/safety); anything it cannot satisfy is
rejected and the deterministic decision stands. Normal frames never call the LLM
(zero latency, zero cost). The planner is a direct Bedrock Converse loop
(`planner.BedrockPlanner`); Strands is an optional adapter.
"""
from __future__ import annotations

from typing import Any

from ..contracts import Decision, FrameResult, SessionSummary, now_ms
from . import policy
from .context import AgentContext, PolicyConfig
from .trace import TraceLine, TraceRecorder

# moments where we allow the LLM to (try to) improve on the rules decision
_AMBIGUOUS_ACTIONS = ("ask_confirmation", "nudge")
_AMBIGUOUS_REASON_PREFIXES = ("low_confidence", "quality_repeated")


class NunchiAgent:
    def __init__(self, vision: Any | None = None, *, mode: str = "deterministic",
                 bedrock_model: str | None = None,
                 config: PolicyConfig | None = None,
                 recorder: TraceRecorder | None = None,
                 planner: Any = None) -> None:
        self.vision = vision
        self.mode = mode
        self.bedrock_model = bedrock_model
        self.config = config or PolicyConfig()
        self.trace = recorder or TraceRecorder()
        self._planner = planner      # injected (FakeLLM in tests, BedrockPlanner in prod)

    # ---- main loop -------------------------------------------------------
    def decide(self, ctx: AgentContext, result: FrameResult,
               frame_bgr: Any | None = None, *, vision_state: Any = None) -> Decision:
        """One frame -> one Decision. Records a trace line. Never raises on bad input.

        `frame_bgr` is a request-scoped memory reference (CONTRACTS §2): it is handed
        to the vision `second_look` tool and is NEVER stored, returned, or traced.
        `vision_state` is the per-session vision handle (cloud tab owns it); if omitted
        a throwaway one is created since `analyze_variant` must not mutate state.
        """
        try:
            result = self._coerce(result)
            state = vision_state if vision_state is not None else self._vision_state(ctx)
            # 1) deterministic decision first (test baseline, zero cost)
            decision, extra = policy.decide(
                result, ctx, self.config,
                vision=self.vision, state=state, frame_bgr=frame_bgr,
            )
            planner_tag = "rules"
            # 2) llm mode: on ambiguous moments, let the planner try to do better
            if self.mode == "llm" and self._is_ambiguous(decision):
                llm_dec, llm_extra = self._llm_refine(ctx, result, decision, extra)
                if llm_dec is not None:
                    decision, extra, planner_tag = llm_dec, llm_extra, "llm"
        except Exception as exc:  # noqa: BLE001 - robustness: any failure degrades to a safe action
            decision = Decision(
                action="request_recalibration",
                message="Something looked off with the camera input. Let's recalibrate.",
                message_ko="카메라 입력에 문제가 있었어요. 다시 보정해볼까요?",
                reason=f"error:{type(exc).__name__}",
                tool_calls=[{"tool": "request_recalibration",
                             "args": {"reason": "internal_error"},
                             "result_summary": "requested"}],
                evidence={"error": type(exc).__name__},
            )
            extra = {"tool": "request_recalibration", "result_summary": "error"}
            planner_tag = "rules"
            ctx.recalibrations += 1

        self.trace.add(TraceLine(
            ts=now_ms(),
            session_id=ctx.session_id or getattr(result, "session_id", ""),
            frame_t=float(getattr(result, "t", 0.0) or 0.0),
            decision=decision.action,
            reason=decision.reason,
            tool=extra.get("tool"),
            args={},
            result_summary=extra.get("result_summary", ""),
            evidence=decision.evidence,
            tool_calls=decision.tool_calls,
            planner=planner_tag,
        ))
        return decision

    # ---- llm planner (ambiguous moments only) ---------------------------
    @staticmethod
    def _is_ambiguous(decision: Decision) -> bool:
        if decision.action in _AMBIGUOUS_ACTIONS:
            return True
        return any(decision.reason.startswith(p) for p in _AMBIGUOUS_REASON_PREFIXES)

    def _llm_refine(self, ctx: AgentContext, result: FrameResult,
                    det_decision: Decision, det_extra: dict[str, Any],
                    ) -> tuple[Decision | None, dict[str, Any] | None]:
        """Ask the planner to propose a plan; return (decision, extra) or (None, None).

        Returns None on: no planner, over cap, timeout, planner error, or a
        guardrail rejection — in all cases the deterministic decision stands. A
        guardrail rejection is still traced (rejected_by_guardrail) via det_extra.
        """
        if self._planner is None:
            return None, None
        from . import planner as planner_mod

        # build a compact, image-free plan request for this ambiguous moment
        if det_decision.reason.startswith("quality_repeated"):
            purpose = "quality_repeated"
            options = ["ask_confirmation", "request_recalibration", "none"]
        elif det_decision.action == "nudge":
            purpose = "nudge_wording"
            options = ["nudge", "none"]
        else:
            purpose = "low_confidence"
            options = ["ask_confirmation", "none"]
        summary = planner_mod.summarise_frame(result, ctx)
        req = planner_mod.PlanRequest(purpose=purpose, summary=summary, options=options)

        plan, info = planner_mod.run_with_budget(
            self._planner, req, ctx=ctx, cfg=self.config,
            timeout_s=self.config.llm_timeout_s)
        if plan is None:
            # record WHY the LLM path did not win on the deterministic trace line
            if info.get("rejected_by_guardrail"):
                det_extra["result_summary"] = (det_extra.get("result_summary", "")
                                               + f"|guardrail:{info['rejected_by_guardrail']}")
                det_decision.evidence = {**det_decision.evidence,
                                         "rejected_by_guardrail": info["rejected_by_guardrail"]}
            elif info.get("timeout"):
                det_extra["result_summary"] = det_extra.get("result_summary", "") + "|llm_timeout"
            elif info.get("skipped") == "over_cap":
                det_extra["result_summary"] = det_extra.get("result_summary", "") + "|llm_over_cap"
            return None, None

        dec = info["decision"]
        # keep the behavior evidence from the rules decision so cooldown logic stays intact
        if det_decision.action == "nudge" and dec.action == "nudge":
            dec.evidence = {**det_decision.evidence, **dec.evidence}
            dec.cooldown_s = dec.cooldown_s or det_decision.cooldown_s
        extra = {"tool": "planner", "result_summary": f"llm:{dec.action}"}
        return dec, extra

    def resolve_confirmation(self, ctx: AgentContext, confirmed: bool) -> dict[str, Any]:
        """Apply a human yes/no to the pending confirmation (human-in-the-loop)."""
        return policy.apply_confirmation(ctx, self.config, confirmed)

    # ---- reporting (Bedrock path + guaranteed template fallback) --------
    def report(self, summary: SessionSummary,
               previous: SessionSummary | None = None) -> dict[str, Any]:
        """Session report (EN/KO, up to 3 highlights, observation tone).

        In `llm` mode with a planner, a Bedrock call writes the prose; it is passed
        through the no-diagnosis + length guardrail and, on any failure/timeout/
        guardrail hit, falls back to the deterministic template. In other modes the
        template is used directly. `comparison` (day-over-day) is always computed.
        """
        template = self._template_report(summary, previous)
        if self.mode != "llm" or self._planner is None:
            template["source"] = "template"
            return template

        from . import guardrails
        from . import planner as planner_mod

        # image-free summary for the report prompt
        req = planner_mod.PlanRequest(
            purpose="report",
            summary={"counts": dict(summary.counts or {}),
                     "seconds": {k: round(v, 1) for k, v in (summary.seconds or {}).items()},
                     "nudges_sent": summary.nudges_sent,
                     "nudges_suppressed": summary.nudges_suppressed,
                     "comparison": template["comparison"]["deltas"]},
            options=["report"],
        )
        # report is free-text generation, not an action decision: call the planner
        # directly (cost/latency bounded), then guardrail only the prose.
        import time as _time
        t0 = _time.perf_counter()
        try:
            plan = self._planner.plan(req)
        except Exception as exc:  # noqa: BLE001 - any planner failure -> template
            template["source"] = "template_fallback"
            template["fallback_reason"] = f"error:{type(exc).__name__}"
            return template
        latency_ms = (_time.perf_counter() - t0) * 1000.0
        if latency_ms > self.config.llm_report_timeout_s * 1000.0:
            template["source"] = "template_fallback"
            template["fallback_reason"] = "timeout"
            return template

        # guardrail the generated prose (no-diagnosis + length), EN/KO
        text_en = plan.get("message", "") or plan.get("text_en", "")
        text_ko = plan.get("message_ko", "") or plan.get("text_ko", "")
        text_en, text_ko, replaced = guardrails.sanitize_message("none", text_en, text_ko)
        if not text_en and not text_ko:  # empty after guardrail -> template
            template["source"] = "template_fallback"
            template["fallback_reason"] = "empty_after_guardrail"
            return template
        return {"text_en": text_en or template["text_en"],
                "text_ko": text_ko or template["text_ko"],
                "highlights": template["highlights"],
                "comparison": template["comparison"],
                "source": "llm", "message_replaced": replaced}

    def _template_report(self, summary: SessionSummary,
                         previous: SessionSummary | None) -> dict[str, Any]:
        """Deterministic template report (always available)."""
        from .summary import compare

        counts = summary.counts or {}
        secs = summary.seconds or {}
        cmp = compare(summary, previous)

        highlights: list[str] = []
        if cmp["has_previous"]:
            highlights.extend(cmp["lines_en"][:2])
        if secs.get("forward_head"):
            highlights.append(f"forward-head posture totalled {int(secs['forward_head'])}s")
        if len(highlights) < 3 and counts.get("blink"):
            highlights.append(f"{counts['blink']} blinks")
        if len(highlights) < 3 and (summary.nudges_sent or summary.nudges_suppressed):
            highlights.append(f"{summary.nudges_sent} nudges sent, "
                              f"{summary.nudges_suppressed} suppressed")
        highlights = highlights[:3]

        if highlights:
            text_en = "Session summary (observations only): " + "; ".join(highlights)
        else:
            text_en = "No notable signals this session."
        if cmp["has_previous"] and cmp["lines_ko"]:
            text_ko = "세션 요약(관찰 기록): " + "; ".join(cmp["lines_ko"][:3])
        elif highlights:
            text_ko = "세션 요약(관찰 기록): " + "; ".join(highlights)
        else:
            text_ko = "이번 세션에는 특이 신호가 없었어요."
        return {"text_en": text_en, "text_ko": text_ko, "highlights": highlights,
                "comparison": cmp}

    # ---- helpers ---------------------------------------------------------
    def _vision_state(self, ctx: AgentContext) -> Any:
        """Lazily obtain a vision session handle for second_look.

        `analyze_variant` must not mutate state (CONTRACTS §1), so a fresh handle
        per call is safe. Returns None if vision can't provide one.
        """
        v = self.vision
        if v is None:
            return None
        new_session = getattr(v, "new_session", None)
        if callable(new_session):
            try:
                return new_session(ctx.session_id or "second-look")
            except Exception:  # noqa: BLE001 - vision optional; skip on any failure
                return None
        return None

    @staticmethod
    def _coerce(result: Any) -> FrameResult:
        """Accept a FrameResult or a plain dict (e.g. from a fixture) robustly."""
        if isinstance(result, FrameResult):
            return result
        if isinstance(result, dict):
            return _frame_from_dict(result)
        raise TypeError(f"unsupported result type: {type(result).__name__}")


def _frame_from_dict(d: dict[str, Any]) -> FrameResult:
    """Build a FrameResult from a JSON dict, tolerating missing/None fields."""
    from ..contracts import Event, Metrics, Quality

    m = d.get("metrics") or {}
    q = d.get("quality") or {}
    evs = []
    for e in (d.get("events") or []):
        if not isinstance(e, dict):
            continue
        evs.append(Event(
            type=e.get("type", "blink"),
            start=float(e.get("start", 0.0) or 0.0),
            end=(None if e.get("end") is None else float(e.get("end"))),
            confidence=float(e.get("confidence", 0.0) or 0.0),
            count=int(e.get("count", 1) or 1),
        ))
    return FrameResult(
        schema=d.get("schema", "1.0"),
        session_id=d.get("session_id", ""),
        t=float(d.get("t", 0.0) or 0.0),
        face_present=bool(d.get("face_present", False)),
        persons=int(d.get("persons", 0) or 0),
        metrics=Metrics(
            ear=m.get("ear"), mar=m.get("mar"), head_roll_deg=m.get("head_roll_deg"),
            head_pitch_proxy=m.get("head_pitch_proxy"), face_scale=m.get("face_scale"),
            shoulder_ear_ratio=m.get("shoulder_ear_ratio"),
            hand_mouth_dist=m.get("hand_mouth_dist"),
        ),
        quality=Quality(
            ok=bool(q.get("ok", True)), brightness=float(q.get("brightness", 0.0) or 0.0),
            sharpness=float(q.get("sharpness", 0.0) or 0.0),
            face_px=int(q.get("face_px", 0) or 0), issues=list(q.get("issues") or []),
        ),
        events=evs,
        calibrated=bool(d.get("calibrated", False)),
        latency_ms=float(d.get("latency_ms", 0.0) or 0.0),
        backend=d.get("backend", "opencv"),
        cv_version=d.get("cv_version", ""),
    )
