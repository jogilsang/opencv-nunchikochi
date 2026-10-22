"""Fixtures and builders for agent sequence tests. No images anywhere."""
from __future__ import annotations

import json
import pathlib

import pytest

from nunchi.contracts import Event, FrameResult, Metrics, Quality

FIX = pathlib.Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text())


def frame(t: float, *, face=True, persons=1, issues: list[str] | None = None,
          ok: bool = True, brightness: float = 118.0, sharpness: float = 210.0,
          face_px: int = 96, events: list[Event] | None = None,
          ear=None, mar=None, roll=None, pitch=None, scale=None,
          hand_mouth=None, calibrated: bool = True) -> FrameResult:
    """Convenience FrameResult builder for time-ordered scenarios."""
    return FrameResult(
        session_id="t", t=t, face_present=face, persons=persons, calibrated=calibrated,
        metrics=Metrics(ear=ear, mar=mar, head_roll_deg=roll, head_pitch_proxy=pitch,
                        face_scale=scale, hand_mouth_dist=hand_mouth),
        quality=Quality(ok=ok, brightness=brightness, sharpness=sharpness,
                        face_px=face_px, issues=issues or []),
        events=events or [],
        backend="opencv", cv_version="5.0.0",
    )


def ev(type_: str, start: float, end=None, confidence: float = 0.85, count: int = 1) -> Event:
    return Event(type=type_, start=start, end=end, confidence=confidence, count=count)


class FakeVision:
    """A fake VisionEngine for second_look tests. No OpenCV, no images.

    `variant_result` maps a variant name -> a function(before_frame) -> FrameResult,
    or a FrameResult directly. `has_variant=False` simulates a vision build without
    analyze_variant (agent must skip second_look). `raises` makes analyze_variant throw.
    """

    def __init__(self, variant_result=None, *, has_variant: bool = True, raises: bool = False):
        self._map = variant_result or {}
        self._raises = raises
        self.calls: list[tuple[float, str]] = []
        if not has_variant:
            # simulate a vision build without analyze_variant: attribute is None
            object.__setattr__(self, "analyze_variant", None)

    def new_session(self, session_id: str):
        return {"session_id": session_id}

    # only defined when has_variant; otherwise overwritten to None in __init__
    def analyze_variant(self, state, frame_bgr, t: float, variant: str):
        self.calls.append((t, variant))
        if self._raises:
            raise RuntimeError("variant boom")
        spec = self._map.get(variant)
        if spec is None:
            # default: return the same thing unchanged (no help)
            return frame(t)
        return spec(frame) if callable(spec) else spec


@pytest.fixture
def agent():
    from nunchi.agent import NunchiAgent, PolicyConfig
    # smaller thresholds so time-ordered tests stay short
    cfg = PolicyConfig(sustained_min_s=180.0, focus_min_quiet_s=120.0)
    return NunchiAgent(vision=None, mode="deterministic", config=cfg)


def make_agent(vision, **cfg_kw):
    """Agent wired to a (fake) vision for active-perception tests.

    `vision` may be a FakeVision, None, or a variant_result dict (wrapped in FakeVision).
    """
    from nunchi.agent import NunchiAgent, PolicyConfig
    if isinstance(vision, dict):
        vision = FakeVision(vision)
    cfg = PolicyConfig(sustained_min_s=180.0, focus_min_quiet_s=120.0, **cfg_kw)
    return NunchiAgent(vision=vision, mode="deterministic", config=cfg)


# a sentinel standing in for a request-scoped frame buffer (never stored/traced)
FRAME = object()


@pytest.fixture
def ctx():
    from nunchi.agent import AgentContext
    return AgentContext(session_id="t", session_start_ms=0)
