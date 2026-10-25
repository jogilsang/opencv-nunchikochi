"""Deep guardrail/safety tests (A5). No network, no images.

Goes beyond test_guardrails.py (which proves plan rejection + message sanitise)
to attack the harder, product-level invariants the hackathon is judged on:

  - trace JSONL never carries image bytes / forbidden keys (privacy)
  - no-diagnosis holds across many phrasings (EN + KO), incl. inside the LLM path
  - every built-in nudge / confirm wording is observation-based + length-bounded
  - cooldown + daily cap actually suppress at the POLICY level (not just plan check)
  - a human denial raises the threshold and it PERSISTS across later frames
  - any user-facing message is bilingual (both EN and KO) or empty on both
"""
from __future__ import annotations

from nunchi.agent import NunchiAgent, PolicyConfig, guardrails
from nunchi.agent import policy as policy_mod
from nunchi.agent.context import AgentContext
from nunchi.agent.trace import TraceLine, TraceRecorder

from .conftest import ev, frame

# ---------------------------------------------- trace never leaks image/bytes


def test_trace_drops_raw_bytes_in_evidence():
    """Raw bytes placed anywhere in a trace line are replaced, not serialised."""
    line = TraceLine(
        ts=1, session_id="s", frame_t=1.0, decision="none",
        evidence={"frame_bgr": b"\x00\x01\x02", "note": "ok"},
        tool_calls=[{"tool": "second_look", "args": {"image": b"JFIF...."}}],
    )
    blob = line.to_dict()
    import json
    text = json.dumps(blob)
    # the forbidden keys are stripped and the byte payload never appears verbatim
    assert "frame_bgr" not in text
    assert "image" not in text
    assert "\\u0000" not in text and "JFIF" not in text
    assert blob["evidence"]["note"] == "ok"


def test_trace_recorder_jsonl_has_no_banned_keys():
    """A recorded line serialised to JSONL contains none of the image/coord keys."""
    rec = TraceRecorder()
    rec.add(TraceLine(ts=1, session_id="s", frame_t=1.0, decision="nudge",
                      reason="sustained:forward_head",
                      evidence={"behavior": "forward_head", "duration_s": 190.0}))
    jsonl = rec.to_jsonl().lower()
    for bad in ("jpeg", "frame_bgr", "pixels", "landmark", "bbox", "bytes", "image"):
        assert bad not in jsonl


def test_agent_decide_trace_is_image_free_even_with_frame():
    """decide() given a (sentinel) frame still writes an image-free trace line."""
    rec = TraceRecorder()
    agent = NunchiAgent(vision=None, mode="deterministic",
                        config=PolicyConfig(), recorder=rec)
    ctx = AgentContext(session_id="t")
    agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]), object())
    jsonl = rec.to_jsonl().lower()
    for bad in ("jpeg", "frame_bgr", "pixels", "image", "<object"):
        assert bad not in jsonl


# ------------------------------------------- no-diagnosis across many phrasings


def test_many_diagnosis_phrasings_blocked_en():
    """A spread of English diagnosis phrasings are all caught."""
    for bad in ("You look tired.", "you seem exhausted", "You are sleepy now",
                "I think you have burnout", "This looks like a sleep disorder",
                "signs of fatigue"):
        assert guardrails.contains_banned(bad) is not None, bad


def test_many_diagnosis_phrasings_blocked_ko():
    """A spread of Korean diagnosis phrasings are all caught."""
    for bad in ("많이 피곤해 보여요", "졸려 보이네요", "지쳐 보입니다",
                "어디 아파요?", "우울해 보여요", "스트레스가 많아 보여요", "피로가 쌓였어요"):
        assert guardrails.contains_banned(bad) is not None, bad


def test_observation_wording_not_falsely_flagged():
    """Observation-based wording must NOT be flagged (no false positives)."""
    for ok in ("Easing back might feel better.",
               "Your head has been tilted for a while.",
               "등을 조금 펴볼까요?", "잠깐 먼 곳을 봐볼까요?",
               "A short look away might help."):
        assert guardrails.contains_banned(ok) is None, ok


def test_every_builtin_nudge_wording_is_safe_and_bounded():
    """Every built-in nudge string: observation-based (not banned) + <=200 chars + bilingual."""
    for behavior in ("forward_head", "head_tilt", "deep_blink", "unknown_behavior"):
        en, ko = policy_mod._nudge_text(behavior)
        assert en and ko, behavior                         # bilingual
        assert len(en) <= guardrails.MAX_MESSAGE_CHARS
        assert len(ko) <= guardrails.MAX_MESSAGE_CHARS
        assert guardrails.contains_banned(en) is None, (behavior, en)
        assert guardrails.contains_banned(ko) is None, (behavior, ko)


def test_every_builtin_confirm_wording_is_safe_and_bounded():
    """Every built-in confirmation question is a question, bilingual, and not a diagnosis."""
    for behavior in ("drink", "yawn", "forward_head", "head_tilt", "mystery"):
        _tag, en, ko = policy_mod._confirm_text(behavior)
        assert en and ko
        assert len(en) <= guardrails.MAX_MESSAGE_CHARS
        assert len(ko) <= guardrails.MAX_MESSAGE_CHARS
        assert guardrails.contains_banned(en) is None, (behavior, en)
        assert guardrails.contains_banned(ko) is None, (behavior, ko)


def test_issue_guidance_wording_is_safe_and_bilingual():
    """Quality-issue guidance strings are observation-based + bilingual for every issue."""
    for issue in ("too_dark", "too_bright", "blurry", "face_too_small",
                  "face_cut_off", "no_face", "multiple_faces", "weird_unknown"):
        en, ko = policy_mod._issue_guidance([issue])
        assert en and ko
        assert guardrails.contains_banned(en) is None, (issue, en)
        assert guardrails.contains_banned(ko) is None, (issue, ko)


# --------------------------------------------- cooldown / daily cap at policy level


def test_cooldown_suppresses_second_nudge_in_policy():
    """Two sustained nudges inside the cooldown window -> second is suppressed, not sent."""
    cfg = PolicyConfig(sustained_min_s=180.0)
    agent = NunchiAgent(vision=None, mode="deterministic", config=cfg)
    ctx = AgentContext(session_id="t")
    # start the forward_head timer, then cross the sustained threshold -> first nudge
    agent.decide(ctx, frame(10.0, events=[ev("forward_head", 10.0, None, 0.9)]))
    d1 = agent.decide(ctx, frame(200.0, events=[ev("forward_head", 10.0, None, 0.9)]))
    assert d1.action == "nudge"
    assert ctx.nudges_sent == 1
    # still sustained, still within 600s cooldown -> suppressed (rate)
    d2 = agent.decide(ctx, frame(260.0, events=[ev("forward_head", 10.0, None, 0.9)]))
    assert d2.action == "suppress_focus"
    assert d2.reason.startswith("cooldown")
    assert ctx.nudges_sent == 1  # NOT incremented


def test_daily_cap_blocks_further_nudges_in_policy():
    """At the daily cap, a fresh sustained signal is suppressed (daily_cap), not nudged."""
    cfg = PolicyConfig(sustained_min_s=180.0, daily_nudge_cap=0)
    agent = NunchiAgent(vision=None, mode="deterministic", config=cfg)
    ctx = AgentContext(session_id="t")
    agent.decide(ctx, frame(10.0, events=[ev("forward_head", 10.0, None, 0.9)]))
    d = agent.decide(ctx, frame(200.0, events=[ev("forward_head", 10.0, None, 0.9)]))
    assert d.action == "suppress_focus"
    assert d.reason.startswith("daily_cap")
    assert ctx.nudges_sent == 0


# ------------------------------------- human denial raises threshold & persists


def test_denial_raises_threshold_and_persists_across_frames():
    """Deny a borderline event -> threshold rises -> the SAME borderline reading
    is no longer asked, across later frames (persistence, not one-shot)."""
    cfg = PolicyConfig(second_look_enabled=False)  # isolate the ask/deny logic
    agent = NunchiAgent(vision=None, mode="deterministic", config=cfg)
    ctx = AgentContext(session_id="t")
    # borderline drink -> ask
    d1 = agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]))
    assert d1.action == "ask_confirmation"
    raised = agent.resolve_confirmation(ctx, confirmed=False)
    assert raised["event_cancelled"] is True
    new_thr = ctx.conf_threshold["drink"]
    assert new_thr > cfg.low_conf_lo

    # a later borderline drink at the SAME confidence is below the raised threshold
    d2 = agent.decide(ctx, frame(90.0, events=[ev("drink", 89.0, 90.0, 0.5)]))
    assert d2.action != "ask_confirmation"
    # and the threshold is still raised much later (persistence)
    d3 = agent.decide(ctx, frame(300.0, events=[ev("drink", 299.0, 300.0, 0.5)]))
    assert d3.action != "ask_confirmation"
    assert ctx.conf_threshold["drink"] == new_thr


def test_denial_threshold_does_not_bleed_to_other_behaviours():
    """Raising the drink threshold must not silence a different borderline behaviour."""
    cfg = PolicyConfig(second_look_enabled=False)
    agent = NunchiAgent(vision=None, mode="deterministic", config=cfg)
    ctx = AgentContext(session_id="t")
    agent.decide(ctx, frame(30.0, events=[ev("drink", 29.0, 30.0, 0.5)]))
    agent.resolve_confirmation(ctx, confirmed=False)
    # a borderline YAWN is still asked (its own threshold untouched)
    d = agent.decide(ctx, frame(90.0, events=[ev("yawn", 89.0, 90.0, 0.5)]))
    assert d.action == "ask_confirmation"
    assert d.reason == "low_confidence:yawn"


# ---------------------------------------------------------- bilingual invariant


def test_llm_message_missing_korean_is_handled():
    """Guardrail output: if the LLM gives EN only, sanitize keeps EN, KO stays empty
    (the harness bilingual check is what flags this at scenario level)."""
    msg, msg_ko, _ = guardrails.sanitize_message(
        "nudge", "Ease back from the screen?", "")
    assert msg and msg_ko == ""


def test_sanitize_is_idempotent_on_clean_text():
    """Sanitising already-clean text twice yields the same text (no drift)."""
    en = "Your blinks have been longer than usual for a while."
    ko = "한동안 눈 감는 시간이 평소보다 길었어요."
    a = guardrails.sanitize_message("nudge", en, ko)
    b = guardrails.sanitize_message("nudge", a[0], a[1])
    assert a[0] == b[0] == en
    assert a[1] == b[1] == ko
    assert a[2] is False and b[2] is False


def test_length_clamp_keeps_within_bound_and_marks_replaced():
    """A >200-char message is clamped to the bound and flagged replaced."""
    long_ko = "자" * 400
    _, ko, replaced = guardrails.sanitize_message("nudge", "ok", long_ko)
    assert len(ko) <= guardrails.MAX_MESSAGE_CHARS
    assert replaced is True


def test_cooldown_lookup_default_for_unknown_behavior():
    """_cooldown_for falls back to the 'default' cooldown for an unknown behaviour."""
    cfg = PolicyConfig()
    assert policy_mod._cooldown_for("forward_head", cfg) == 1200.0
    assert policy_mod._cooldown_for("totally_unknown", cfg) == cfg.nudge_cooldown_s["default"]
