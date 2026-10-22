"""Robustness (exception/error) and Agentic-Vision trace proof."""
from __future__ import annotations

import json

from nunchi.contracts import FrameResult, Metrics, Quality

from .conftest import ev, frame

# ------------------------------------------------------------ edge / exception


def test_none_and_missing_fields_do_not_raise(agent, ctx):
    """EDGE 1: a FrameResult with None metrics and empty quality is handled, no exception."""
    fr = FrameResult(session_id="t", t=1.0, face_present=True,
                     metrics=Metrics(), quality=Quality(ok=True))
    dec = agent.decide(ctx, fr)
    assert dec.action in ("none", "suppress_focus", "request_recalibration")
    assert isinstance(dec.to_dict(), dict)


def test_dict_with_missing_keys_decodes(agent, ctx):
    """EDGE 2: a partial dict (no metrics/quality/events) decodes to a safe Decision."""
    dec = agent.decide(ctx, {"session_id": "t", "t": 2.0, "face_present": True})
    assert dec.action in ("none", "suppress_focus")
    assert not dec.needs_human


def test_malformed_event_entries_are_skipped(agent, ctx):
    """EDGE 3: non-dict entries in events[] are ignored rather than crashing."""
    dec = agent.decide(ctx, {"t": 3.0, "face_present": True, "quality": {"ok": True},
                             "events": ["not-a-dict", None, {"type": "blink", "start": 2.0}]})
    assert dec.action in ("none", "suppress_focus")


# ------------------------------------------------------------ error handling


def test_bad_input_type_degrades_to_recalibration(agent, ctx):
    """ERROR 1: a wholly invalid input type degrades to a safe recalibration request, no raise."""
    dec = agent.decide(ctx, 12345)  # not a FrameResult or dict
    assert dec.action == "request_recalibration"
    assert dec.reason.startswith("error:")
    assert ctx.recalibrations >= 1


def test_internal_exception_is_caught(agent, ctx, monkeypatch):
    """ERROR 2: an exception inside the policy is caught and converted to a safe decision."""
    import nunchi.agent.policy as pol

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(pol, "decide", boom)
    dec = agent.decide(ctx, frame(1.0))
    assert dec.action == "request_recalibration"
    assert "RuntimeError" in dec.reason


# ------------------------------------------------- Agentic Vision trace proof


def test_trace_proves_vision_changed_decision(agent, ctx):
    """The trace shows the same agent taking DIFFERENT actions as OpenCV evidence changes."""
    # 1) clean frame -> none
    agent.decide(ctx, frame(5.0, events=[ev("blink", 4.9, 5.0, 0.9)]))
    # 2) dark frame -> recalibration (vision quality changed the action)
    agent.decide(ctx, frame(6.0, face=False, ok=False, issues=["too_dark", "no_face"]))
    # 3) sustained forward_head -> nudge
    agent.decide(ctx, frame(10.0, events=[ev("forward_head", 0.0, None, 0.9)]))
    agent.decide(ctx, frame(300.0, events=[ev("forward_head", 0.0, None, 0.9)]))

    actions = [ln.decision for ln in agent.trace.lines]
    assert "none" in actions
    assert "request_recalibration" in actions
    assert "nudge" in actions
    # every line carries the evidence and reason that drove it
    for ln in agent.trace.lines:
        d = ln.to_dict()
        assert {"ts", "session_id", "frame_t", "tool", "decision",
                "reason", "evidence"}.issubset(d)


def test_trace_jsonl_is_image_free(agent, ctx):
    """Trace output must never contain image/byte payloads (privacy)."""
    # sneak image-like keys into evidence via a crafted frame path
    agent.decide(ctx, frame(5.0, events=[ev("blink", 4.9, 5.0, 0.9)]))
    text = agent.trace.to_jsonl()
    for line in text.splitlines():
        obj = json.loads(line)
        blob = json.dumps(obj).lower()
        for bad in ("jpeg", "frame_bgr", "pixels", "b64", "image/"):
            assert bad not in blob
