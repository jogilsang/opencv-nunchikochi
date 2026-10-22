"""Active perception (second_look): OpenCV re-analysis changes human involvement.

Each test proves the Agentic-Vision point: a second OpenCV look BEFORE escalating
to a human changes whether the user is asked at all. Uses a FakeVision (no images).
"""
from __future__ import annotations

from .conftest import FRAME, ev, frame, make_agent

# ------- (1) quality: enhance resolves -> no human / no recalibration --------


def test_enhance_resolves_quality_no_human(ctx):
    """Dark frame, but enhance variant comes back clean -> decision none (OpenCV stood in)."""
    clean = frame(3.0, face=True, ok=True, issues=[], brightness=120.0)
    agent = make_agent({"enhance": clean})
    dec = agent.decide(ctx, frame(3.0, face=False, ok=False, issues=["too_dark", "no_face"],
                                  brightness=22.0), FRAME)
    assert dec.action == "none"
    assert dec.reason == "second_look:quality_cleared"
    assert dec.needs_human is False
    assert any(tc["tool"] == "second_look" for tc in dec.tool_calls)
    assert ctx.second_looks == 1 and ctx.second_look_resolved == 1
    assert ctx.recalibrations == 0  # recalibration was avoided


def test_enhance_does_not_resolve_requests_recalibration(ctx):
    """Dark frame and enhance still bad -> fall back to request_recalibration."""
    still_bad = frame(3.0, face=False, ok=False, issues=["too_dark", "no_face"], brightness=24.0)
    agent = make_agent({"enhance": still_bad})
    dec = agent.decide(ctx, frame(3.0, face=False, ok=False, issues=["too_dark", "no_face"],
                                  brightness=22.0), FRAME)
    assert dec.action == "request_recalibration"
    assert ctx.second_looks == 1 and ctx.second_look_resolved == 0
    assert ctx.recalibrations == 1
    # trace shows the second_look was tried before recalibration
    tools_seq = [tc["tool"] for tc in dec.tool_calls]
    assert tools_seq.index("second_look") < tools_seq.index("request_recalibration")


# ------- (2) confidence: closer look confirms / rejects, no human -----------


def test_confidence_rises_auto_confirms_no_human(ctx):
    """Borderline drink (0.5); zoom_face raises confidence above band -> auto-confirm, no ask."""
    confident = frame(30.0, events=[ev("drink", 29.0, 30.0, confidence=0.85)])
    agent = make_agent({"zoom_face": confident})
    dec = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, confidence=0.5)]), FRAME)
    assert dec.action == "none"
    assert dec.reason.startswith("second_look:confidence_confirm")
    assert dec.needs_human is False
    assert ctx.confirmations_asked == 0
    assert dec.evidence["verdict"] == "confirm"


def test_confidence_falls_auto_rejects_no_human(ctx):
    """Borderline drink (0.5); a closer look drops confidence below band -> auto-reject, no ask."""
    low = frame(30.0, events=[ev("drink", 29.0, 30.0, confidence=0.2)])
    agent = make_agent({"zoom_face": low})
    dec = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, confidence=0.5)]), FRAME)
    assert dec.action == "none"
    assert dec.reason.startswith("second_look:confidence_reject")
    assert ctx.confirmations_asked == 0
    assert dec.evidence["verdict"] == "reject"


def test_confidence_unchanged_still_asks_human(ctx):
    """If the second look leaves confidence in-band, the agent still asks the human."""
    same = frame(30.0, events=[ev("drink", 29.0, 30.0, confidence=0.5)])
    agent = make_agent({"zoom_face": same})
    dec = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, confidence=0.5)]), FRAME)
    assert dec.action == "ask_confirmation"
    assert dec.needs_human
    assert ctx.confirmations_asked == 1
    # the second_look was consulted first
    tools_seq = [tc["tool"] for tc in dec.tool_calls]
    assert "second_look" in tools_seq and "ask_confirmation" in tools_seq
    assert tools_seq.index("second_look") < tools_seq.index("ask_confirmation")


def test_event_vanishes_on_closer_look_rejects(ctx):
    """A closer look where the event is gone entirely -> reject (false positive filtered out)."""
    gone = frame(30.0, events=[])  # no drink event on re-analysis
    agent = make_agent({"zoom_face": gone})
    dec = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, confidence=0.55)]), FRAME)
    assert dec.action == "none"
    assert dec.evidence["verdict"] == "reject"
    assert ctx.confirmations_asked == 0


# ------- (3) fallback when vision cannot help --------------------------------


def test_no_vision_falls_back_to_ask(ctx):
    """vision=None -> second_look skipped (no_variant) -> classic ask_confirmation."""
    from nunchi.agent import NunchiAgent, PolicyConfig
    a = NunchiAgent(vision=None, config=PolicyConfig(sustained_min_s=180.0))
    dec = a.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, confidence=0.5)]))
    assert dec.action == "ask_confirmation"
    assert any(tc["tool"] == "second_look" and tc["result_summary"] == "skipped:no_variant"
               for tc in dec.tool_calls)


def test_vision_without_analyze_variant_skips(ctx):
    """A vision build lacking analyze_variant -> second_look skipped, classic path used."""
    from .conftest import FakeVision
    agent = make_agent(FakeVision(has_variant=False))
    dec = agent.decide(ctx, frame(3.0, face=False, ok=False, issues=["too_dark", "no_face"]),
                       FRAME)
    assert dec.action == "request_recalibration"
    assert any(tc["tool"] == "second_look" and "no_variant" in tc["result_summary"]
               for tc in dec.tool_calls)


def test_second_look_exception_is_contained(ctx):
    """If analyze_variant raises, the error is contained (trace: error) and we fall back."""
    from .conftest import FakeVision
    agent = make_agent(FakeVision(raises=True))
    dec = agent.decide(ctx, frame(3.0, face=False, ok=False, issues=["too_dark", "no_face"]),
                       FRAME)
    # error contained -> did not crash, fell back to recalibration
    assert dec.action == "request_recalibration"
    assert any(tc["tool"] == "second_look" and tc["result_summary"].startswith("error:")
               for tc in dec.tool_calls)


# ------- (4) frame_bgr never leaks into the trace ---------------------------


def test_frame_bgr_never_in_trace(ctx):
    """The request-scoped frame reference must not appear in any trace line."""
    clean = frame(3.0, ok=True, issues=[])
    agent = make_agent({"enhance": clean})
    agent.decide(ctx, frame(3.0, face=False, ok=False, issues=["too_dark"]), FRAME)
    text = agent.trace.to_jsonl().lower()
    assert "frame" not in text or "frame_t" in text  # only frame_t key allowed
    for bad in ("object at 0x", "frame_bgr", "<object"):
        assert bad not in text
