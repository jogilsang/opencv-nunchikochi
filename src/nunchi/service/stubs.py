"""Deterministic stubs for vision/agent. OWNER: cloud tab.

When the real vision/agent implementations are not available (early integration,
web tab wants to connect without mock mode), the service returns contract-shaped
responses built from these stubs. Stub use is surfaced at /healthz ("stubs": true).

Shapes mirror tests/fixtures/*.json. No image bytes are ever read, kept or returned —
the stub ignores the decoded frame entirely; it only uses `t` and calibration count.
"""
from __future__ import annotations

from typing import Any

from nunchi.contracts import (
    SCHEMA_VERSION,
    Decision,
    Event,
    FrameResult,
    Metrics,
    Quality,
    SessionSummary,
)

# Number of calibrate frames before the stub reports baseline established.
STUB_CALIBRATION_FRAMES = 3


class StubVision:
    """Stand-in for nunchi.vision.VisionEngine. Deterministic; never touches image content."""

    backend = "stub"
    cv_version = "stub"

    def new_session(self, session_id: str) -> dict[str, Any]:
        return {"session_id": session_id, "calib_frames": 0, "calibrated": False}

    def calibrate(self, state: dict[str, Any], t: float) -> dict[str, Any]:
        state["calib_frames"] = int(state.get("calib_frames", 0)) + 1
        state["calibrated"] = state["calib_frames"] >= STUB_CALIBRATION_FRAMES
        return state

    def analyze(self, state: dict[str, Any], t: float) -> FrameResult:
        """Return a plausible, deterministic FrameResult. A sustained head_tilt event
        is emitted after t>=10s so agent/web integration has something to react to."""
        calibrated = bool(state.get("calibrated", False))
        events = []
        if calibrated and t >= 10.0:
            events.append(Event(type="head_tilt", start=10.0, end=None, confidence=0.82, count=1))
        return FrameResult(
            schema=SCHEMA_VERSION,
            session_id=str(state.get("session_id", "")),
            t=t,
            face_present=calibrated,
            persons=1 if calibrated else 0,
            metrics=Metrics(
                ear=0.27 if calibrated else None,
                mar=0.31 if calibrated else None,
                head_roll_deg=14.2 if (calibrated and t >= 10.0) else (2.0 if calibrated else None),
                head_pitch_proxy=0.18 if calibrated else None,
                face_scale=1.12 if calibrated else None,
            ),
            quality=Quality(
                ok=calibrated,
                brightness=118.0 if calibrated else 22.0,
                sharpness=210.0 if calibrated else 0.0,
                face_px=96 if calibrated else 0,
                issues=[] if calibrated else ["too_dark", "no_face"],
            ),
            events=events,
            calibrated=calibrated,
            latency_ms=0.0,
            backend=self.backend,
            cv_version=self.cv_version,
        )


class StubAgent:
    """Stand-in for nunchi.agent.NunchiAgent. Deterministic rule: sustained head_tilt -> nudge."""

    def decide(self, ctx: dict[str, Any], result: FrameResult) -> Decision:
        tilt = any(e.type == "head_tilt" and e.end is None for e in result.events)
        if tilt:
            return Decision(
                action="nudge",
                message="You have been tilting your head for a while. Straighten up?",
                message_ko="고개가 한참 기울어져 있어요. 바로 세워볼까요?",
                reason="sustained:head_tilt",
                needs_human=False,
                tool_calls=[{"tool": "get_quality", "args": {}, "result_summary": "ok"}],
                evidence={"head_roll_deg": result.metrics.head_roll_deg, "duration_s": 2.5},
                cooldown_s=300.0,
            )
        if not result.quality.ok and "too_dark" in result.quality.issues:
            return Decision(
                action="request_recalibration",
                message="It's a bit dark — can you add some light and face the camera?",
                message_ko="화면이 조금 어두워요. 조명을 켜고 카메라를 바라봐 주세요.",
                reason="quality:too_dark",
                needs_human=True,
                evidence={"brightness": result.quality.brightness},
                cooldown_s=30.0,
            )
        return Decision(action="none", reason="nominal")

    def report(self, summary: SessionSummary, previous: SessionSummary | None) -> dict[str, Any]:
        return {
            "text_en": "Session recorded. (stub report — agent not wired yet.)",
            "text_ko": "세션이 기록되었습니다. (스텁 리포트 — 에이전트 미연결)",
            "highlights": [],
        }
