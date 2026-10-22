"""Generate trace samples that visibly prove "OpenCV output changed the decision".

Run: uv run python agent/make_samples.py
Writes agent/samples/trace_quality.jsonl and trace_nudge.jsonl (JSONL, no images).
"""
from __future__ import annotations

import pathlib

from nunchi.agent import AgentContext, NunchiAgent, PolicyConfig, TraceRecorder
from nunchi.contracts import Event, FrameResult, Metrics, Quality

OUT = pathlib.Path(__file__).parent / "samples"
OUT.mkdir(exist_ok=True)


def _frame(t, *, face=True, persons=1, issues=None, ok=True, brightness=118.0,
           sharpness=210.0, face_px=96, events=None, roll=None):
    return FrameResult(
        session_id="demo", t=t, face_present=face, persons=persons, calibrated=True,
        metrics=Metrics(head_roll_deg=roll),
        quality=Quality(ok=ok, brightness=brightness, sharpness=sharpness,
                        face_px=face_px, issues=issues or []),
        events=events or [], backend="opencv", cv_version="5.0.0",
    )


def sample_quality() -> str:
    """Quality goes bad then recovers: the action tracks the visual evidence."""
    rec = TraceRecorder()
    agent = NunchiAgent(vision=None, config=PolicyConfig(), recorder=rec)
    ctx = AgentContext(session_id="demo")
    agent.decide(ctx, _frame(1.0, events=[Event("blink", 0.9, 1.0, 0.9)]))          # none
    agent.decide(ctx, _frame(3.0, face=False, ok=False, brightness=22.0,
                             issues=["too_dark", "no_face"]))                         # recalibration
    agent.decide(ctx, _frame(5.0, face=False, ok=False, brightness=24.0,
                             issues=["too_dark", "no_face"]))                         # recalibration (streak 2)
    agent.decide(ctx, _frame(7.0, face=False, ok=False, brightness=26.0,
                             issues=["too_dark", "no_face"]))                         # ask_confirmation (streak 3)
    agent.decide(ctx, _frame(20.0, events=[Event("blink", 19.9, 20.0, 0.9)]))        # none (recovered)
    return rec.to_jsonl()


def sample_nudge() -> str:
    """A sustained posture signal triggers a nudge; a repeat within cooldown is suppressed."""
    rec = TraceRecorder()
    agent = NunchiAgent(vision=None, config=PolicyConfig(), recorder=rec)
    ctx = AgentContext(session_id="demo")
    agent.decide(ctx, _frame(10.0, roll=1.0))                                        # none
    agent.decide(ctx, _frame(30.0, events=[Event("forward_head", 20.0, None, 0.9)])) # none (not yet sustained)
    agent.decide(ctx, _frame(220.0, events=[Event("forward_head", 20.0, None, 0.9)]))# nudge (>180s)
    agent.decide(ctx, _frame(260.0, events=[Event("forward_head", 20.0, None, 0.9)]))# suppress (cooldown)
    return rec.to_jsonl()


class _DemoVision:
    """Minimal fake vision for the sample: returns a pre-set FrameResult per variant.

    Stands in for the real VisionEngine.analyze_variant so the sample can show the
    active-perception loop without OpenCV or any image.
    """

    def __init__(self, by_variant: dict[str, FrameResult]):
        self._by = by_variant

    def new_session(self, session_id: str):
        return {"session_id": session_id}

    def analyze_variant(self, state, frame_bgr, t: float, variant: str) -> FrameResult:
        return self._by.get(variant, _frame(t))


_FRAME = object()  # request-scoped frame stand-in (never stored/traced)


def sample_second_look() -> str:
    """Active perception: an OpenCV second look decides whether a human is asked.

    Scene A (quality): a dark frame -> second_look(enhance) comes back clean ->
        decision NONE, no recalibration/human (OpenCV stood in for the user).
    Scene B (confidence): a borderline 'drink' (0.5) -> second_look(zoom_face)
        confirms (0.9) -> auto-confirm, no human.
    Scene C (confidence): a borderline 'yawn' (0.5) -> second_look stays 0.5 ->
        the agent DOES ask the human.
    """
    rec = TraceRecorder()
    cleaned = _frame(3.0, face=True, ok=True, brightness=120.0)
    confident = _frame(6.0, events=[Event("drink", 5.0, 6.0, 0.9)])
    unchanged = _frame(9.0, events=[Event("yawn", 8.0, 9.0, 0.5)])
    vision = _DemoVision({"enhance": cleaned, "zoom_face": confident})
    agent = NunchiAgent(vision=vision, config=PolicyConfig(), recorder=rec)
    ctx = AgentContext(session_id="demo")
    # A: dark -> enhance clears -> none (no human)
    agent.decide(ctx, _frame(3.0, face=False, ok=False, brightness=22.0,
                             issues=["too_dark", "no_face"]), _FRAME)
    # B: borderline drink -> zoom_face confirms -> none (no human)
    agent.decide(ctx, _frame(6.0, events=[Event("drink", 5.0, 6.0, 0.5)]), _FRAME)
    # C: borderline yawn -> zoom_face unchanged (returns enhance default) -> ask human
    vision_c = _DemoVision({"zoom_face": unchanged})
    agent.vision = vision_c
    agent.decide(ctx, _frame(9.0, events=[Event("yawn", 8.0, 9.0, 0.5)]), _FRAME)
    return rec.to_jsonl()


def main() -> None:
    (OUT / "trace_quality.jsonl").write_text(sample_quality() + "\n", encoding="utf-8")
    (OUT / "trace_nudge.jsonl").write_text(sample_nudge() + "\n", encoding="utf-8")
    (OUT / "trace_second_look.jsonl").write_text(sample_second_look() + "\n", encoding="utf-8")
    print(f"wrote {OUT/'trace_quality.jsonl'}")
    print(f"wrote {OUT/'trace_nudge.jsonl'}")
    print(f"wrote {OUT/'trace_second_look.jsonl'}")


if __name__ == "__main__":
    main()
