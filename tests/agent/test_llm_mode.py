"""LLM planner mode with a FAKE planner (deterministic, no network).

Proves: the LLM only runs on ambiguous moments, its plan is bounded by guardrails,
and the agent falls back to rules on cap/timeout/error/rejection. Also checks the
trace `planner` field and the report Bedrock path (+ fallback).
"""
from __future__ import annotations

from nunchi.agent import FakeLLM, NunchiAgent, PolicyConfig
from nunchi.contracts import SessionSummary

from .conftest import ev, frame


def _llm_agent(script, **cfg_kw):
    cfg = PolicyConfig(sustained_min_s=180.0, focus_min_quiet_s=120.0, **cfg_kw)
    return NunchiAgent(vision=None, mode="llm", config=cfg, planner=FakeLLM(script))


# --------------------------------------------- LLM only on ambiguous moments


def test_normal_frame_never_calls_llm(ctx):
    """A clean frame stays on the rules path: the planner is not called (zero cost)."""
    planner = FakeLLM({})
    agent = NunchiAgent(vision=None, mode="llm", config=PolicyConfig(), planner=planner)
    dec = agent.decide(ctx, frame(5.0, events=[ev("blink", 4.9, 5.0, 0.9)]))
    assert dec.action == "none"
    assert planner.calls == []  # LLM never invoked
    assert agent.trace.lines[-1].planner == "rules"


def test_low_confidence_calls_llm_and_uses_plan(ctx):
    """Ambiguous low-confidence moment -> LLM plan accepted -> trace planner=llm."""
    script = {"low_confidence": {"action": "ask_confirmation",
                                 "message": "Did you take a sip of water?",
                                 "message_ko": "방금 물 한 모금 드셨나요?",
                                 "reason": "llm:drink_personalised"}}
    agent = _llm_agent(script)
    dec = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]))
    assert dec.action == "ask_confirmation"
    assert dec.reason == "llm:drink_personalised"
    assert "water" in dec.message.lower()
    assert agent.trace.lines[-1].planner == "llm"
    assert ctx.llm_calls == 1


def test_llm_nudge_wording_personalised(ctx):
    """On a sustained nudge, the LLM may reword it; guardrail keeps cooldown evidence."""
    script = {"nudge_wording": {"action": "nudge",
                                "message": "You've been close to the screen a while; ease back?",
                                "message_ko": "한동안 화면에 가까웠어요; 등을 펴볼까요?",
                                "reason": "llm:nudge_personalised"}}
    agent = _llm_agent(script)
    agent.decide(ctx, frame(10.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    dec = agent.decide(ctx, frame(300.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    assert dec.action == "nudge"
    assert dec.reason == "llm:nudge_personalised"
    assert agent.trace.lines[-1].planner == "llm"


# ------------------------------------------------------- guardrail fallback


def test_llm_plan_rejected_by_guardrail_falls_back(ctx):
    """If the LLM proposes a forbidden action, the deterministic decision stands."""
    script = {"low_confidence": {"action": "format_disk", "message": "boom"}}
    agent = _llm_agent(script)
    dec = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]))
    # fell back to rules ask_confirmation
    assert dec.action == "ask_confirmation"
    assert dec.reason == "low_confidence:drink"
    assert agent.trace.lines[-1].planner == "rules"
    # the rejection is recorded on the trace line
    assert "guardrail:unknown_action:format_disk" in agent.trace.lines[-1].result_summary
    assert dec.evidence.get("rejected_by_guardrail") == "unknown_action:format_disk"


def test_llm_diagnosis_message_is_sanitised(ctx):
    """A diagnosis in the LLM message is replaced by a safe template (plan still accepted)."""
    script = {"low_confidence": {"action": "ask_confirmation",
                                 "message": "You look tired. Did you doze off?",
                                 "message_ko": "피곤해 보여요. 졸았나요?",
                                 "reason": "llm:drink"}}
    agent = _llm_agent(script)
    dec = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]))
    assert dec.action == "ask_confirmation"
    assert "tired" not in dec.message.lower()
    assert "피곤" not in dec.message_ko
    assert agent.trace.lines[-1].planner == "llm"


# --------------------------------------------------------- cap and timeout


def test_llm_over_session_cap_falls_back(ctx):
    """Once the per-session LLM cap is hit, ambiguous moments use rules again."""
    script = {"low_confidence": {"action": "none", "reason": "llm:ok"}}
    agent = _llm_agent(script, llm_max_calls=1)
    agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]))      # call #1
    ctx.pending_confirmation = None  # allow another ambiguous moment
    dec = agent.decide(ctx, frame(60.0, events=[ev("yawn", 59.0, 60.0, 0.5)]))  # over cap
    assert agent.trace.lines[-1].planner == "rules"
    assert dec.action == "ask_confirmation"
    assert "llm_over_cap" in agent.trace.lines[-1].result_summary


def test_llm_timeout_falls_back(ctx):
    """A planner slower than the timeout is not trusted; rules decision stands."""
    slow = FakeLLM({"low_confidence": {"action": "none"}}, sleep_s=0.05)
    cfg = PolicyConfig(llm_timeout_s=0.001)  # 1ms -> the 50ms fake call "times out"
    agent = NunchiAgent(vision=None, mode="llm", config=cfg, planner=slow)
    dec = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]))
    assert agent.trace.lines[-1].planner == "rules"
    assert dec.action == "ask_confirmation"
    assert "llm_timeout" in agent.trace.lines[-1].result_summary


def test_llm_planner_exception_falls_back(ctx):
    """If the planner raises, the agent degrades to the deterministic decision."""
    boom = FakeLLM({}, raises=True)
    agent = NunchiAgent(vision=None, mode="llm", config=PolicyConfig(), planner=boom)
    dec = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]))
    assert dec.action == "ask_confirmation"
    assert agent.trace.lines[-1].planner == "rules"


# --------------------------------------------------------------- report path


def test_report_llm_path_used_when_planner_present():
    """llm-mode report uses the planner prose and marks source=llm."""
    script = {"report": {"message": "Posture time rose a bit vs yesterday; "
                                     "a few more breaks could help.",
                         "message_ko": "어제보다 자세 시간이 조금 늘었어요; 휴식을 조금 더 가져볼까요?"}}
    agent = NunchiAgent(vision=None, mode="llm", config=PolicyConfig(), planner=FakeLLM(script))
    summ = SessionSummary(session_id="s", date="2026-10-22", seconds={"forward_head": 600.0})
    prev = SessionSummary(session_id="p", date="2026-10-21", seconds={"forward_head": 400.0})
    out = agent.report(summ, prev)
    assert out["source"] == "llm"
    assert "yesterday" in out["text_en"].lower()
    assert out["comparison"]["has_previous"] is True


def test_report_llm_diagnosis_falls_back_to_template():
    """A diagnosis in the generated report is sanitised; empty result -> template."""
    script = {"report": {"message": "You are exhausted.", "message_ko": "당신은 지쳤어요."}}
    agent = NunchiAgent(vision=None, mode="llm", config=PolicyConfig(), planner=FakeLLM(script))
    summ = SessionSummary(session_id="s", date="2026-10-22", seconds={"forward_head": 600.0})
    out = agent.report(summ, None)
    # banned prose replaced by empty for action "none" -> template fallback
    assert out["source"] == "template_fallback"
    assert out["fallback_reason"] == "empty_after_guardrail"
    assert "exhausted" not in out["text_en"].lower()


def test_report_template_in_deterministic_mode():
    """Deterministic mode never calls the planner for the report."""
    agent = NunchiAgent(vision=None, mode="deterministic", planner=FakeLLM({}))
    summ = SessionSummary(session_id="s", date="2026-10-22", counts={"blink": 100})
    out = agent.report(summ, None)
    assert out["source"] == "template"


# --------------------------------------------------- summary-only safety


def test_plan_request_is_image_free():
    """summarise_frame + assert_image_free reject any image/coordinate leakage."""
    from nunchi.agent import planner as pmod
    s = pmod.summarise_frame(frame(5.0, roll=12.0, events=[ev("drink", 4.0, 5.0, 0.5)]), ctx_stub())
    # roll/landmarks must NOT be in the summary
    assert "head_roll_deg" not in s and "roll" not in s
    pmod.assert_image_free({"purpose": "x", "summary": s})  # should not raise


def ctx_stub():
    from nunchi.agent import AgentContext
    return AgentContext(session_id="t")
