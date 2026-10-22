"""Optional Strands Agents adapter. OWNER: agent tab.

Strands is NOT the default: its full dependency tree measured ~63MB (boto3
baseline 28MB, so ~+35MB) which is a large Lambda-package increase, so the
default planner is the direct Bedrock Converse loop in `planner.py`. This adapter
lets the same agent run on Strands when it is installed, producing a plan dict
that goes through the EXACT SAME `guardrails`.

`strands-agents` is declared in the `agent` dependency-group but intentionally
not installed in the dev env; import is lazy so this module always loads.
"""
from __future__ import annotations

import json
from typing import Any

from .planner import _SYSTEM_PROMPT, DEFAULT_MODEL, PlanRequest, assert_image_free


def strands_available() -> bool:
    """True iff the optional `strands` package can be imported."""
    try:
        import strands  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - optional dependency
        return False


class StrandsPlanner:
    """A Planner backed by Strands Agents. Same prompt + output contract as BedrockPlanner.

    Requires `uv pip install strands-agents`. Raises at construction if unavailable
    so callers can fall back to BedrockPlanner explicitly.
    """

    def __init__(self, *, model_id: str = DEFAULT_MODEL, region: str = "us-east-1",
                 max_tokens: int = 256, agent: Any = None):
        if agent is None and not strands_available():
            raise RuntimeError(
                "strands-agents is not installed. Install it (agent group) or use "
                "BedrockPlanner. Default is BedrockPlanner due to package size (~+35MB)."
            )
        self.model_id = model_id
        self.region = region
        self.max_tokens = max_tokens
        self._agent = agent  # injectable for tests

    def _build_agent(self) -> Any:
        from strands import Agent
        from strands.models import BedrockModel
        model = BedrockModel(model_id=self.model_id, region_name=self.region,
                             max_tokens=self.max_tokens, temperature=0.2)
        return Agent(model=model, system_prompt=_SYSTEM_PROMPT)

    def plan(self, req: PlanRequest) -> dict[str, Any]:
        payload = req.to_prompt_payload()
        assert_image_free(payload)
        agent = self._agent if self._agent is not None else self._build_agent()
        result = agent(json.dumps(payload, ensure_ascii=False))
        text = str(getattr(result, "message", result) or "")
        from .planner import _parse_plan_json
        return _parse_plan_json(text)
