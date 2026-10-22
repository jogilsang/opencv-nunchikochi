"""nunchi.agent — perceive->decide->act loop for Agentic Vision. OWNER: agent tab.

Public API (CONTRACTS §2):
    NunchiAgent.decide(ctx, result, frame_bgr=None) -> Decision
    NunchiAgent.report(summary, previous) -> {"text_en","text_ko","highlights"}
The decision is driven by OpenCV output (FrameResult); every decision is traced.
Active perception (`second_look`) re-runs OpenCV before asking a human.
In `llm` mode a Bedrock planner proposes on ambiguous moments, bounded by
deterministic guardrails (cost/latency/safety).
"""
from . import guardrails, planner, policy, tools
from .agent import NunchiAgent
from .context import AgentContext, PolicyConfig
from .planner import BedrockPlanner, FakeLLM, Planner, PlanRequest
from .summary import SummaryAccumulator, compare
from .trace import TraceLine, TraceRecorder

__all__ = [
    "AgentContext",
    "BedrockPlanner",
    "FakeLLM",
    "NunchiAgent",
    "PlanRequest",
    "Planner",
    "PolicyConfig",
    "SummaryAccumulator",
    "TraceLine",
    "TraceRecorder",
    "compare",
    "guardrails",
    "planner",
    "policy",
    "tools",
]
