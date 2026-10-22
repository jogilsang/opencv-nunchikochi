"""JSONL decision trace. OWNER: agent tab.

Records the perceive->decide->act loop as one JSON object per line. Fields follow
CONTRACTS §2: ts, session_id, frame_t, tool, args, result_summary, decision,
evidence, reason. NEVER contains image data or raw bytes (privacy).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# keys that must never leak into a trace line (defence in depth against images/bytes)
_FORBIDDEN_KEYS = ("frame", "frame_bgr", "image", "jpeg", "bytes", "pixels", "raw")


def _sanitise(value: Any) -> Any:
    """Drop anything that looks like image/byte payload; keep only JSON primitives/containers."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes dropped>"
    if isinstance(value, dict):
        return {
            k: _sanitise(v)
            for k, v in value.items()
            if not any(bad in str(k).lower() for bad in _FORBIDDEN_KEYS)
        }
    if isinstance(value, (list, tuple)):
        return [_sanitise(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # unknown object: stringify rather than risk serialising raw buffers
    return str(value)


@dataclass
class TraceLine:
    ts: int                                  # wall-clock ms
    session_id: str
    frame_t: float                           # session-relative seconds
    decision: str                            # action taken
    reason: str = ""
    tool: str | None = None               # last/primary tool, if any
    args: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    planner: str = "rules"                   # "rules" | "llm" (schema-compatible addition)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "session_id": self.session_id,
            "frame_t": self.frame_t,
            "tool": self.tool,
            "args": _sanitise(self.args),
            "result_summary": self.result_summary,
            "decision": self.decision,
            "evidence": _sanitise(self.evidence),
            "reason": self.reason,
            "tool_calls": _sanitise(self.tool_calls),
            "planner": self.planner,
        }


class TraceRecorder:
    """Collects trace lines in memory; callers can write JSONL. No disk I/O by default."""

    def __init__(self) -> None:
        self.lines: list[TraceLine] = []

    def add(self, line: TraceLine) -> None:
        self.lines.append(line)

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(ln.to_dict(), ensure_ascii=False) for ln in self.lines)

    def write(self, path: str) -> None:
        text = self.to_jsonl()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text + ("\n" if text else ""))

    def clear(self) -> None:
        self.lines.clear()
