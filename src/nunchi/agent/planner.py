"""LLM planner (Bedrock) behind a deterministic guardrail. OWNER: agent tab.

The planner *proposes* a plan (action + optional message + tool_calls) from a
compact, image-free summary of the current frame and context. The proposal is
then forced through `guardrails.apply_guardrails`; anything it cannot satisfy is
rejected and the caller falls back to the deterministic policy.

Only "ambiguous" moments reach the planner (low confidence after second_look,
repeated bad quality, nudge wording). Normal frames stay on the rules path
(zero latency, zero cost).

Design (README): Strands full dependency tree measured at ~63MB (boto3 baseline
28MB, +~35MB) which is a large Lambda-package increase, so the default planner
is a direct Bedrock Converse tool loop (`BedrockPlanner`); Strands is an optional
adapter (`strands_adapter.py`). Both must pass the same guardrails.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..contracts import FrameResult
from . import guardrails

# Default Haiku 4.5 inference profile (captain / us-east-1), per brief.
DEFAULT_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Haiku 4.5 public pricing (USD per 1M tokens). Used only to estimate dev cost in
# the call log; the authoritative bill is AWS. Update if pricing changes.
_PRICE_IN_PER_1M = 1.0
_PRICE_OUT_PER_1M = 5.0

_LLM_LOG = pathlib.Path(__file__).resolve().parents[3] / "agent" / "llm_calls.jsonl"


@dataclass
class PlanRequest:
    """Compact, image-free input to the planner. No coordinates/landmarks/bytes."""
    purpose: str                              # "low_confidence" | "quality_repeated" | "nudge_wording" | "report"
    summary: dict[str, Any] = field(default_factory=dict)
    options: list[str] = field(default_factory=list)   # allowed actions for this moment

    def to_prompt_payload(self) -> dict[str, Any]:
        return {"purpose": self.purpose, "summary": self.summary, "options": self.options}


class Planner(Protocol):
    """Anything that can propose a plan dict for a PlanRequest."""
    def plan(self, req: PlanRequest) -> dict[str, Any]: ...


# ---------------------------------------------------------------- summarising

# keys allowed to reach the LLM. Anything else (coordinates, raw landmarks) is dropped.
_ALLOWED_SUMMARY_KEYS = {
    "face_present", "persons", "quality_ok", "quality_issues",
    "behavior", "confidence", "second_look", "bad_quality_streak",
    "in_focus", "do_not_disturb", "recent_counts",
}


def summarise_frame(result: FrameResult, ctx: Any, *,
                    second_look: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a compact, image-free summary for the prompt (no coords/landmarks/bytes)."""
    prim = None
    evs = result.events or []
    if evs:
        ongoing = [e for e in evs if e.end is None]
        prim = max(ongoing or evs, key=lambda e: (e.confidence or 0.0))
    s: dict[str, Any] = {
        "face_present": bool(result.face_present),
        "persons": int(result.persons),
        "quality_ok": bool(result.quality.ok),
        "quality_issues": list(result.quality.issues),
        "bad_quality_streak": int(getattr(ctx, "bad_quality_streak", 0)),
        "in_focus": bool(getattr(ctx, "in_focus", False)),
        "do_not_disturb": bool(getattr(ctx, "do_not_disturb", False)),
    }
    if prim is not None:
        s["behavior"] = prim.type
        s["confidence"] = round(float(prim.confidence or 0.0), 3)
    if second_look is not None:
        # only numbers/verdict, never frames
        s["second_look"] = {k: second_look.get(k) for k in ("variant", "verdict", "reason")
                            if k in second_look}
    # drop anything not whitelisted (defence in depth)
    return {k: v for k, v in s.items() if k in _ALLOWED_SUMMARY_KEYS}


def assert_image_free(payload: Any) -> None:
    """Raise if a prompt payload contains image/coordinate-like keys (safety)."""
    bad = ("frame", "image", "jpeg", "bytes", "pixels", "landmark", "bbox",
           "coord", "_x", "_y", "rex", "rey", "lex", "ley")
    blob = json.dumps(payload, ensure_ascii=False).lower()
    for b in bad:
        if b in blob:
            raise ValueError(f"prompt payload contains forbidden key fragment: {b}")


# ---------------------------------------------------------------- fake planner


class FakeLLM:
    """Scripted planner for deterministic tests (no network).

    `script` maps purpose -> plan dict, or a callable(req)->plan. `calls` records
    the PlanRequests seen. Optionally simulate latency/timeout/raise.
    """

    def __init__(self, script: dict[str, Any] | None = None, *,
                 raises: bool = False, sleep_s: float = 0.0):
        self.script = script or {}
        self.raises = raises
        self.sleep_s = sleep_s
        self.calls: list[PlanRequest] = []

    def plan(self, req: PlanRequest) -> dict[str, Any]:
        self.calls.append(req)
        if self.sleep_s:
            time.sleep(self.sleep_s)
        if self.raises:
            raise RuntimeError("fake llm failure")
        spec = self.script.get(req.purpose)
        if callable(spec):
            return spec(req)
        if spec is None:
            return {"action": "none", "reason": "llm:no_script"}
        return dict(spec)


# ---------------------------------------------------------------- bedrock


def _log_call(record: dict[str, Any]) -> None:
    """Append one LLM call record (tokens, latency, est. cost, prompt HASH only)."""
    try:
        _LLM_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_LLM_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging must never break a decision


def estimate_cost_usd(tokens_in: int, tokens_out: int) -> float:
    return round(tokens_in / 1e6 * _PRICE_IN_PER_1M + tokens_out / 1e6 * _PRICE_OUT_PER_1M, 6)


_SYSTEM_PROMPT = (
    "You are the decision core of a desk-ergonomics assistant. You receive a compact, "
    "image-free summary of one webcam frame and session context. Choose ONE action from "
    "the provided options and, if it is a nudge or question, write a SHORT user-facing "
    "message in English and Korean. Rules you MUST follow: observations only, never a "
    "diagnosis or a statement about feelings/health (no 'you are tired', '피곤해 보여요'); "
    "<=200 characters; be kind and brief. Reply with ONLY a JSON object: "
    '{"action","message","message_ko","reason","behavior"?}. No prose outside JSON.'
)

_REPORT_SYSTEM_PROMPT = (
    "You write a short end-of-session summary for a desk-ergonomics assistant from "
    "image-free aggregate numbers (counts, seconds, day-over-day deltas). Rules you MUST "
    "follow: observations only, never a diagnosis or a statement about feelings/health "
    "(no 'you are tired', '피곤해 보여요'); kind and brief; <=200 characters each. Reply with "
    'ONLY a JSON object: {"message": <English summary>, "message_ko": <Korean summary>}. '
    "No prose outside JSON."
)


def _system_for(purpose: str) -> str:
    return _REPORT_SYSTEM_PROMPT if purpose == "report" else _SYSTEM_PROMPT


class BedrockPlanner:
    """Direct Bedrock Converse planner. Lazy boto3 import so tests need no AWS."""

    def __init__(self, *, model_id: str = DEFAULT_MODEL, region: str = "us-east-1",
                 profile: str | None = "captain", max_tokens: int = 256,
                 timeout_s: float = 3.0, client: Any = None):
        self.model_id = model_id
        self.region = region
        self.profile = profile
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self._client = client  # injectable for tests

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        import boto3  # lazy: Lambda runtime provides boto3; tests never hit this
        from botocore.config import Config
        session = boto3.Session(profile_name=self.profile) if self.profile else boto3.Session()
        cfg = Config(read_timeout=self.timeout_s, connect_timeout=self.timeout_s,
                     retries={"max_attempts": 0})
        self._client = session.client("bedrock-runtime", region_name=self.region, config=cfg)
        return self._client

    def plan(self, req: PlanRequest) -> dict[str, Any]:
        payload = req.to_prompt_payload()
        assert_image_free(payload)
        user_text = json.dumps(payload, ensure_ascii=False)
        system = _system_for(req.purpose)
        prompt_hash = hashlib.sha256((system + user_text).encode()).hexdigest()[:16]
        client = self._get_client()
        t0 = time.perf_counter()
        status = "ok"
        tokens_in = tokens_out = 0
        try:
            resp = client.converse(
                modelId=self.model_id,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user_text}]}],
                inferenceConfig={"maxTokens": self.max_tokens, "temperature": 0.2},
            )
            usage = resp.get("usage", {})
            tokens_in = int(usage.get("inputTokens", 0))
            tokens_out = int(usage.get("outputTokens", 0))
            text = _extract_text(resp)
            plan = _parse_plan_json(text)
        except Exception as exc:  # noqa: BLE001 - any Bedrock failure -> caller falls back
            status = f"error:{type(exc).__name__}"
            plan = {"action": "none", "reason": f"llm_error:{type(exc).__name__}"}
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        _log_call({
            "ts": int(time.time() * 1000), "purpose": req.purpose,
            "model": self.model_id, "status": status,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "latency_ms": latency_ms,
            "est_cost_usd": estimate_cost_usd(tokens_in, tokens_out),
            "prompt_sha16": prompt_hash,
        })
        plan.setdefault("_latency_ms", latency_ms)
        plan.setdefault("_tokens", {"in": tokens_in, "out": tokens_out})
        return plan


def _extract_text(resp: dict[str, Any]) -> str:
    try:
        parts = resp["output"]["message"]["content"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, TypeError):
        return ""


def _parse_plan_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of the model text; safe default on failure."""
    text = (text or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return {"action": "none", "reason": "llm:unparseable"}


# ---------------------------------------------------------------- run w/ budget


def run_with_budget(planner: Planner, req: PlanRequest, *, ctx: Any, cfg: Any,
                    timeout_s: float = 3.0, now: Callable[[], float] = time.perf_counter
                    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Call the planner under a per-session cap + timeout, then run guardrails.

    Returns (plan_or_None, info). info carries latency_ms, over_cap/timeout flags,
    and guardrail result. A None plan means "fall back to deterministic".
    """
    info: dict[str, Any] = {"planner": "llm"}
    # per-session LLM call cap
    cap = getattr(cfg, "llm_max_calls", 20)
    used = getattr(ctx, "llm_calls", 0)
    if used >= cap:
        info.update({"skipped": "over_cap", "used": used, "cap": cap})
        return None, info

    t0 = now()
    try:
        plan = planner.plan(req)
    except Exception as exc:  # noqa: BLE001 - planner failure -> deterministic fallback
        info.update({"error": type(exc).__name__})
        return None, info
    latency_ms = (now() - t0) * 1000.0
    info["latency_ms"] = round(latency_ms, 1)
    ctx.llm_calls = used + 1

    # soft timeout: if the call took too long, don't trust it this frame
    if latency_ms > timeout_s * 1000.0:
        info["timeout"] = True
        return None, info

    dec, ginfo = guardrails.apply_guardrails(plan, ctx=ctx, cfg=cfg)
    info.update(ginfo)
    if ginfo.get("rejected"):
        info["rejected_by_guardrail"] = ginfo.get("reason")
        return None, info
    # attach the accepted decision via info so the agent can use it
    info["decision"] = dec
    return plan, info
