"""Deterministic guardrails the LLM planner cannot override. OWNER: agent tab.

The LLM may *plan and choose* among allowed tools, but these rules bound safety,
cost, and latency and are enforced in plain Python AFTER the LLM speaks:

  - action whitelist (only known ActionTypes)
  - tool whitelist (only the 7 known tools) + per-tool arg schema
  - nudge cooldown + daily cap are unchanged (checked in policy; here we also
    refuse a nudge the planner invents that violates them)
  - do_not_disturb honoured
  - no-diagnosis post-filter: banned phrases -> replaced with a template line
  - message length <= 200 chars, language EN/KO only
  - prompts never contain images/coordinates (checked when building context)

A rejected plan is recorded as ``rejected_by_guardrail`` and the agent falls
back to the deterministic decision.
"""
from __future__ import annotations

from typing import Any

from ..contracts import Decision
from .tools import TOOL_NAMES

MAX_MESSAGE_CHARS = 200

ALLOWED_ACTIONS = ("none", "nudge", "request_recalibration",
                   "ask_confirmation", "suppress_focus")
ALLOWED_TOOLS = set(TOOL_NAMES)

# No-diagnosis: the product reports observations, never states/feelings/health.
# Case-insensitive substring match on the user-facing message (EN + KO).
# NOTE: patterns must catch diagnosis phrasings WITHOUT flagging observation
# wording ("You have been leaning..." is fine; "you have a disorder" is not).
BANNED_PHRASES = (
    # English — "you are/look/seem <state>"
    "you are tired", "you're tired", "you look tired", "you seem tired",
    "you are exhausted", "you look exhausted", "you seem exhausted",
    "you are sick", "you look sick", "you seem sick",
    "you are unhealthy", "you have a ", "you are depressed", "you are stressed",
    "you are drowsy", "you look drowsy", "you seem drowsy", "diagnos", "disorder", "fatigue",
    "you are sleepy", "you look sleepy", "you seem sleepy", "burnout", "burned out",
    # Korean
    "피곤", "졸려", "졸음", "지쳐", "지친", "아파", "아프", "우울",
    "스트레스", "병", "질환", "진단", "건강이", "피로",
)

# Fallback templates when the LLM wording is rejected (observation-based, EN/KO).
_FALLBACK_BY_ACTION = {
    "nudge": ("Time for a small posture check?", "잠깐 자세를 점검해볼까요?"),
    "ask_confirmation": ("Can you confirm what just happened?", "방금 무슨 일이 있었는지 확인해줄래요?"),
    "request_recalibration": ("Let's recalibrate the camera.", "카메라를 다시 보정해볼까요?"),
    "none": ("", ""),
    "suppress_focus": ("", ""),
}

# minimal per-tool arg schema: key -> accepted type(s) for isinstance check
_TOOL_ARG_SCHEMA: dict[str, dict[str, Any]] = {
    "get_quality": {},
    "get_metrics_window": {"window_s": (int, float)},
    "second_look": {"variant": str},
    "request_recalibration": {"reason": str},
    "ask_confirmation": {"about": str},
    "send_nudge": {"behavior": str},
    "suppress": {"kind": str},
}


def contains_banned(text: str) -> str | None:
    """Return the first banned phrase found (lowercased), else None."""
    if not text:
        return None
    low = text.lower()
    for p in BANNED_PHRASES:
        if p in low:
            return p
    return None


def sanitize_message(action: str, message: str, message_ko: str) -> tuple[str, str, bool]:
    """Enforce no-diagnosis + length. Returns (message, message_ko, was_replaced)."""
    replaced = False
    hit_en = contains_banned(message)
    hit_ko = contains_banned(message_ko)
    if hit_en or hit_ko:
        fb_en, fb_ko = _FALLBACK_BY_ACTION.get(action, ("", ""))
        message, message_ko = fb_en, fb_ko
        replaced = True
    # length clamp (never silently truncate mid-word into garbage: hard cut + ellipsis)
    if len(message) > MAX_MESSAGE_CHARS:
        message = message[:MAX_MESSAGE_CHARS - 1].rstrip() + "…"
        replaced = True
    if len(message_ko) > MAX_MESSAGE_CHARS:
        message_ko = message_ko[:MAX_MESSAGE_CHARS - 1].rstrip() + "…"
        replaced = True
    return message, message_ko, replaced


def validate_tool_call(tc: dict[str, Any]) -> str | None:
    """Validate one planned tool call against the whitelist + arg schema.

    Returns an error reason string if invalid, else None.
    """
    if not isinstance(tc, dict):
        return "tool_call_not_dict"
    name = tc.get("tool")
    if name not in ALLOWED_TOOLS:
        return f"unknown_tool:{name}"
    args = tc.get("args", {})
    if not isinstance(args, dict):
        return "args_not_dict"
    schema = _TOOL_ARG_SCHEMA.get(name, {})
    for key, typ in schema.items():
        if key in args and not isinstance(args[key], typ):
            return f"bad_arg_type:{name}.{key}"
    return None


def check_plan(plan: dict[str, Any], *, ctx: Any, cfg: Any) -> str | None:
    """Validate a planner's proposed plan before it becomes a Decision.

    `plan`: {"action","message","message_ko","reason","tool_calls":[...],
             "evidence":{...},"behavior":optional}
    Returns a rejection reason (-> rejected_by_guardrail) or None if acceptable.
    Cooldown/daily-cap/DND checks mirror the deterministic policy so the LLM
    cannot invent a nudge that violates them.
    """
    if not isinstance(plan, dict):
        return "plan_not_dict"
    action = plan.get("action")
    if action not in ALLOWED_ACTIONS:
        return f"unknown_action:{action}"

    # tool-call whitelist + schema
    for tc in plan.get("tool_calls", []) or []:
        err = validate_tool_call(tc)
        if err:
            return err

    # do_not_disturb: the planner may not nudge/ask
    if getattr(ctx, "do_not_disturb", False) and action in ("nudge", "ask_confirmation"):
        return "violates_do_not_disturb"

    # nudge cooldown + daily cap are inviolable
    if action == "nudge":
        behavior = plan.get("behavior") or (plan.get("evidence", {}) or {}).get("behavior")
        if getattr(ctx, "nudges_sent", 0) >= getattr(cfg, "daily_nudge_cap", 20):
            return "violates_daily_cap"
        if behavior:
            from ..contracts import now_ms
            from .policy import _cooldown_for
            cooldown = _cooldown_for(behavior, cfg)
            last = ctx.last_nudge_ms_by_type.get(behavior, 0)
            if last and (now_ms() - last) < cooldown * 1000:
                return "violates_cooldown"
    return None


def apply_guardrails(plan: dict[str, Any], *, ctx: Any, cfg: Any) -> tuple[Decision | None, dict[str, Any]]:
    """Turn a validated plan into a Decision, or reject it.

    Returns (Decision or None, info). If info['rejected'] is set, the caller must
    fall back to the deterministic decision. On accept, the message has already
    passed the no-diagnosis + length filter.
    """
    reason = check_plan(plan, ctx=ctx, cfg=cfg)
    if reason is not None:
        return None, {"rejected": True, "reason": reason}

    action = plan["action"]
    msg, msg_ko, replaced = sanitize_message(
        action, plan.get("message", "") or "", plan.get("message_ko", "") or "")

    dec = Decision(
        action=action,
        message=msg,
        message_ko=msg_ko,
        reason=plan.get("reason", f"llm:{action}"),
        needs_human=bool(plan.get("needs_human", action == "ask_confirmation")),
        tool_calls=list(plan.get("tool_calls", []) or []),
        evidence=dict(plan.get("evidence", {}) or {}),
        cooldown_s=float(plan.get("cooldown_s", 0.0) or 0.0),
    )
    return dec, {"rejected": False, "message_replaced": replaced}
