"""Deterministic guardrails: the LLM plan must pass these or be rejected.

Covers >=6 guardrail violations plus message sanitisation. No network.
"""
from __future__ import annotations

from nunchi.agent import PolicyConfig, guardrails
from nunchi.agent.context import AgentContext
from nunchi.contracts import now_ms


def _ctx(**kw):
    return AgentContext(session_id="t", **kw)


# ----------------------------------------------------------- plan rejection


def test_reject_unknown_action():
    """VIOLATION 1: an action outside the whitelist is rejected."""
    r = guardrails.check_plan({"action": "shutdown_computer"}, ctx=_ctx(), cfg=PolicyConfig())
    assert r == "unknown_action:shutdown_computer"


def test_reject_unknown_tool():
    """VIOLATION 2: a tool call outside the 7-tool whitelist is rejected."""
    plan = {"action": "none", "tool_calls": [{"tool": "delete_logs", "args": {}}]}
    r = guardrails.check_plan(plan, ctx=_ctx(), cfg=PolicyConfig())
    assert r == "unknown_tool:delete_logs"


def test_reject_bad_tool_arg_type():
    """VIOLATION 3: a tool arg of the wrong type is rejected by the schema."""
    plan = {"action": "none",
            "tool_calls": [{"tool": "get_metrics_window", "args": {"window_s": "sixty"}}]}
    r = guardrails.check_plan(plan, ctx=_ctx(), cfg=PolicyConfig())
    assert r == "bad_arg_type:get_metrics_window.window_s"


def test_reject_nudge_when_do_not_disturb():
    """VIOLATION 4: the planner cannot nudge while do_not_disturb is on."""
    plan = {"action": "nudge", "behavior": "forward_head", "message": "sit back"}
    r = guardrails.check_plan(plan, ctx=_ctx(do_not_disturb=True), cfg=PolicyConfig())
    assert r == "violates_do_not_disturb"


def test_reject_nudge_over_daily_cap():
    """VIOLATION 5: the planner cannot exceed the daily nudge cap."""
    cfg = PolicyConfig(daily_nudge_cap=2)
    plan = {"action": "nudge", "behavior": "forward_head"}
    r = guardrails.check_plan(plan, ctx=_ctx(nudges_sent=2), cfg=cfg)
    assert r == "violates_daily_cap"


def test_reject_nudge_within_cooldown():
    """VIOLATION 6: the planner cannot nudge a behaviour still on cooldown."""
    cfg = PolicyConfig()
    ctx = _ctx()
    ctx.last_nudge_ms_by_type["forward_head"] = now_ms()  # just nudged
    plan = {"action": "nudge", "behavior": "forward_head"}
    r = guardrails.check_plan(plan, ctx=ctx, cfg=cfg)
    assert r == "violates_cooldown"


def test_valid_plan_passes():
    """A clean plan passes the guardrail and yields a Decision."""
    plan = {"action": "ask_confirmation", "message": "Did you just take a drink?",
            "message_ko": "방금 물을 마셨나요?", "reason": "llm:drink"}
    dec, info = guardrails.apply_guardrails(plan, ctx=_ctx(), cfg=PolicyConfig())
    assert info["rejected"] is False
    assert dec.action == "ask_confirmation"
    assert dec.needs_human is True


# --------------------------------------------------- message sanitisation


def test_banned_phrase_english_replaced():
    """No-diagnosis: an English diagnosis is replaced with a safe template."""
    msg, msg_ko, replaced = guardrails.sanitize_message(
        "nudge", "You look tired, take a break.", "피곤해 보여요. 쉬세요.")
    assert replaced is True
    assert "tired" not in msg.lower()
    assert "피곤" not in msg_ko


def test_banned_phrase_korean_replaced():
    """No-diagnosis: a Korean diagnosis also triggers replacement."""
    _, _, replaced = guardrails.sanitize_message(
        "nudge", "Straighten up.", "졸려 보이네요.")
    assert replaced is True


def test_message_length_clamped():
    """Over-length messages are clamped to <= 200 chars."""
    long_en = "x" * 500
    msg, _, replaced = guardrails.sanitize_message("nudge", long_en, "짧음")
    assert len(msg) <= guardrails.MAX_MESSAGE_CHARS
    assert replaced is True


def test_clean_message_untouched():
    """A clean, short, observation-based message is not altered."""
    en = "Your head has been tilted for a while. Straightening up might help."
    ko = "고개가 한참 기울어 있었어요. 바로 세워볼까요?"
    msg, msg_ko, replaced = guardrails.sanitize_message("nudge", en, ko)
    assert replaced is False
    assert msg == en and msg_ko == ko


def test_tool_call_validation_direct():
    """validate_tool_call accepts known tools and flags unknown/shape errors."""
    assert guardrails.validate_tool_call({"tool": "get_quality", "args": {}}) is None
    assert guardrails.validate_tool_call({"tool": "nope", "args": {}}) == "unknown_tool:nope"
    assert guardrails.validate_tool_call({"tool": "second_look", "args": []}) == "args_not_dict"
    assert guardrails.validate_tool_call("not-a-dict") == "tool_call_not_dict"
