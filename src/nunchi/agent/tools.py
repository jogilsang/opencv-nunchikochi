"""Agent tools. OWNER: agent tab.

Six pure Python functions with JSON-serialisable args and results so they can
later be wrapped as Strands `@tool`s unchanged. No side effects beyond the
returned dict (sending a nudge just *describes* the nudge; the service/web tab
delivers it). None of these touch images.

Tools (CONTRACTS §2):
  get_quality, get_metrics_window, second_look, request_recalibration,
  ask_confirmation, send_nudge, suppress
"""
from __future__ import annotations

from typing import Any

from ..contracts import FrameResult


def get_quality(result: FrameResult) -> dict[str, Any]:
    """Expose the vision quality of the current frame as a JSON dict.

    This is the tool through which the agent *perceives* input quality; a bad
    result here changes the decision (ask for light / recalibrate).
    """
    q = result.quality
    return {
        "ok": bool(q.ok),
        "brightness": float(q.brightness),
        "sharpness": float(q.sharpness),
        "face_px": int(q.face_px),
        "issues": list(q.issues),
        "face_present": bool(result.face_present),
        "persons": int(result.persons),
    }


def get_metrics_window(recent: list[dict[str, Any]], behavior: str | None = None,
                       window_s: float = 60.0, now_t: float = 0.0) -> dict[str, Any]:
    """Summarise recent event history (not frames) over the last `window_s` seconds.

    `recent` is AgentContext.recent (list of {t, type, confidence, ...}). Used to
    detect focus windows and nudge rate. JSON-serialisable in and out.
    """
    lo = now_t - window_s
    items = [e for e in recent if e.get("t", 0.0) >= lo]
    if behavior is not None:
        items = [e for e in items if e.get("type") == behavior]
    count = len(items)
    confs = [float(e.get("confidence", 0.0)) for e in items if e.get("confidence") is not None]
    rolls = [float(e.get("head_roll_deg")) for e in items if e.get("head_roll_deg") is not None]
    roll_spread = (max(rolls) - min(rolls)) if rolls else 0.0
    return {
        "window_s": float(window_s),
        "behavior": behavior,
        "count": count,
        "rate_per_s": (count / window_s) if window_s > 0 else 0.0,
        "mean_confidence": (sum(confs) / len(confs)) if confs else 0.0,
        "roll_spread_deg": roll_spread,
    }


def request_recalibration(reason: str) -> dict[str, Any]:
    """Ask the user to recalibrate (face the camera for 5 s). Describes the request only."""
    return {"tool": "request_recalibration", "reason": reason, "requested": True}


def ask_confirmation(question_en: str, question_ko: str, about: str,
                     behavior: str | None = None) -> dict[str, Any]:
    """Human-in-the-loop question. `about` is a machine tag, `behavior` the event type if any."""
    return {
        "tool": "ask_confirmation",
        "about": about,
        "behavior": behavior,
        "question_en": question_en,
        "question_ko": question_ko,
        "needs_human": True,
    }


def send_nudge(behavior: str, message_en: str, message_ko: str,
               cooldown_s: float) -> dict[str, Any]:
    """Describe a nudge to deliver. Observation-based wording only (no diagnosis)."""
    return {
        "tool": "send_nudge",
        "behavior": behavior,
        "message_en": message_en,
        "message_ko": message_ko,
        "cooldown_s": float(cooldown_s),
        "sent": True,
    }


def suppress(reason: str, kind: str = "focus") -> dict[str, Any]:
    """Suppress nudging for a reason (focus window, do-not-disturb, away)."""
    return {"tool": "suppress", "kind": kind, "reason": reason, "suppressed": True}


def _conf_of(result: FrameResult, behavior: str | None) -> float | None:
    """Confidence of the ongoing/most-salient event of `behavior` (or any) in a FrameResult."""
    evs = result.events or []
    if behavior is not None:
        evs = [e for e in evs if e.type == behavior]
    if not evs:
        return None
    ongoing = [e for e in evs if e.end is None]
    pool = ongoing or evs
    return max((e.confidence or 0.0) for e in pool)


def second_look(vision: Any, state: Any, frame_bgr: Any, t: float, variant: str,
                *, before: FrameResult, behavior: str | None = None,
                conf_lo: float = 0.40, conf_hi: float = 0.60) -> dict[str, Any]:
    """Active perception: re-analyse the SAME frame a different way before asking a human.

    Calls ``vision.analyze_variant(state, frame_bgr, t, variant)``. ``frame_bgr`` is
    a request-scoped memory reference passed straight to vision; it is never stored,
    returned, or traced. Only before/after quality and confidence numbers come back.

    Returns a JSON-serialisable dict:
      {available, variant, resolved, reason, before:{...}, after:{...}, verdict}
    - For quality variants (``enhance``): ``resolved`` = after frame is clean.
    - For confidence variants (``zoom_face``/``strict``): ``verdict`` is
      "confirm" (conf rose above hi), "reject" (conf fell below lo), or
      "unchanged" (still in band); ``resolved`` True iff verdict != "unchanged".
    """
    fn = getattr(vision, "analyze_variant", None)
    if vision is None or fn is None or not callable(fn):
        return {"tool": "second_look", "available": False, "variant": variant,
                "resolved": False, "reason": "no_variant"}

    after: FrameResult = fn(state, frame_bgr, t, variant)

    b_q, a_q = before.quality, after.quality
    before_sum = {"ok": bool(b_q.ok), "issues": list(b_q.issues),
                  "brightness": float(b_q.brightness), "sharpness": float(b_q.sharpness),
                  "face_px": int(b_q.face_px)}
    after_sum = {"ok": bool(a_q.ok), "issues": list(a_q.issues),
                 "brightness": float(a_q.brightness), "sharpness": float(a_q.sharpness),
                 "face_px": int(a_q.face_px)}

    out: dict[str, Any] = {
        "tool": "second_look", "available": True, "variant": variant,
        "before": before_sum, "after": after_sum,
    }

    if variant == "enhance":
        resolved = bool(a_q.ok) and after.face_present
        out.update({"resolved": resolved,
                    "reason": "quality_cleared" if resolved else "quality_still_bad"})
        return out

    # confidence variants: zoom_face / strict
    c_before = _conf_of(before, behavior)
    c_after = _conf_of(after, behavior)
    out["before"]["confidence"] = c_before
    out["after"]["confidence"] = c_after
    if c_after is None:
        verdict = "reject"          # event vanished on a closer/stricter look
    elif c_after > conf_hi:
        verdict = "confirm"
    elif c_after < conf_lo:
        verdict = "reject"
    else:
        verdict = "unchanged"
    out.update({"verdict": verdict, "resolved": verdict != "unchanged",
                "reason": f"confidence_{verdict}"})
    return out


# Names the agent/strands wrapper can enumerate.
TOOL_NAMES = (
    "get_quality",
    "get_metrics_window",
    "second_look",
    "request_recalibration",
    "ask_confirmation",
    "send_nudge",
    "suppress",
)
