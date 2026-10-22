"""Human-readable demo traces for the Agentic Vision submission. OWNER: agent tab.

Runs 5 representative scenarios through the real NunchiAgent and writes, per
scenario, BOTH:
  - a human-readable timeline markdown (frame -> vision result -> tool calls ->
    decision -> reason) a judge can read without running anything, and
  - the machine JSONL trace (same recorder the service exposes) for reproduction.

NO IMAGES anywhere. `frame_bgr` is a request-scoped sentinel; only numeric
vision summaries and tool/decision records are shown.

Scenarios (each maps to a workflow-spec branch and a pytest):
  1 second_look_quality_cleared  — bad quality -> second_look(enhance) clears -> none
  2 low_conf_ask_confirmation    — low confidence -> ask the human
  3 guardrail_blocks_action      — LLM proposes a forbidden action -> rejected -> rules
  4 llm_timeout_fallback         — planner slower than budget -> rules decision stands
  5 denied_confirmation_raises_threshold — human says no -> threshold rises, persists

Usage:
    uv run python eval/agent/demo_trace.py            # deterministic (no network)
    uv run python eval/agent/demo_trace.py --live      # scenarios 3-4 via Haiku (<=3 LLM calls)
"""
from __future__ import annotations

import argparse
import pathlib
from typing import Any

from nunchi.agent import FakeLLM, NunchiAgent, PolicyConfig, TraceRecorder
from nunchi.agent.agent import _frame_from_dict
from nunchi.agent.context import AgentContext

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parents[1] / "docs" / "submission" / "traces"

# request-scoped frame stand-in (never stored/traced)
_FRAME = object()


class StubVision:
    """Deterministic VisionEngine.analyze_variant stand-in (no OpenCV, no images)."""

    def __init__(self, variants: dict[str, dict] | None = None, *, raises: bool = False):
        self._variants = variants or {}
        self._raises = raises

    def new_session(self, session_id: str) -> dict:
        return {"session_id": session_id}

    def analyze_variant(self, state: Any, frame_bgr: Any, t: float, variant: str):
        if self._raises:
            raise RuntimeError("stub vision error")
        spec = self._variants.get(variant)
        if spec is None:
            return _frame_from_dict({"t": t, "face_present": True, "quality": {"ok": True}})
        return _frame_from_dict({**spec, "t": spec.get("t", t)})


# --------------------------------------------------------------------------- scenarios
# Each scenario is a dict describing how to build the agent and the frames to feed.
# Kept explicit (not the JSON eval set) so the timeline narration is first-class.

def _scenarios() -> list[dict]:
    clean_q = {"ok": True, "brightness": 118, "sharpness": 210, "face_px": 96}
    dark_q = {"ok": False, "brightness": 20, "sharpness": 60, "face_px": 0,
              "issues": ["too_dark", "no_face"]}
    return [
        {
            "id": "second_look_quality_cleared",
            "title": "저품질 → 능동 지각(second_look) → 결정 변경",
            "branch": "quality 1b (enhance가 해소)",
            "pytest": "tests/agent/test_second_look.py",
            "why": "OpenCV 재분석(enhance)이 어두운 프레임을 깨끗이 복원하면, 사람에게 묻거나 "
                   "재보정을 요구하는 대신 조용히 넘어간다. 시각 결과가 행동을 바꾼 핵심 사례.",
            "mode": "deterministic",
            "vision_variants": {"enhance": {"face_present": True, "persons": 1,
                                            "quality": clean_q}},
            "steps": [
                {"frame": {"t": 40.0, "face_present": False, "persons": 1, "quality": dark_q},
                 "note": "어두워서 얼굴이 안 보임(too_dark, no_face)"},
            ],
        },
        {
            "id": "low_conf_ask_confirmation",
            "title": "저확신 → 사람 확인(human-in-the-loop)",
            "branch": "low-confidence 3b (unchanged -> ask)",
            "pytest": "tests/agent/test_scenarios.py",
            "why": "확신이 밴드(0.4~0.6)에 있고 second_look으로도 안 갈리면, 임의로 단정하지 않고 "
                   "사람에게 예/아니오를 묻는다(사람 통제).",
            "mode": "deterministic",
            "config": {"second_look_enabled": False},
            "steps": [
                {"frame": {"t": 30.0, "face_present": True, "persons": 1, "quality": clean_q,
                           "events": [{"type": "drink", "start": 29.0, "end": 30.0,
                                       "confidence": 0.5}]},
                 "note": "물 마심? 확신 0.5 (애매)"},
            ],
        },
        {
            "id": "guardrail_blocks_action",
            "title": "가드레일 차단 → 규칙 폴백",
            "branch": "failure: guardrail reject -> planner=rules",
            "pytest": "tests/agent/test_llm_mode.py::test_llm_plan_rejected_by_guardrail_falls_back",
            "why": "LLM이 화이트리스트 밖 action을 제안해도 결정적 가드레일이 거부하고, "
                   "안전한 규칙 결정이 그대로 선다. LLM은 제안만, 규칙·가드레일이 바닥.",
            "mode": "llm",
            "llm_script": {"low_confidence": {"action": "format_disk", "message": "boom"}},
            "steps": [
                {"frame": {"t": 30.0, "face_present": True, "persons": 1, "quality": clean_q,
                           "events": [{"type": "drink", "start": 29.0, "end": 30.0,
                                       "confidence": 0.5}]},
                 "note": "저확신 drink(애매한 순간이라 LLM 호출) — LLM이 'format_disk' 제안"},
            ],
        },
        {
            "id": "llm_timeout_fallback",
            "title": "LLM 타임아웃 → 규칙 폴백",
            "branch": "failure: LLM timeout -> planner=rules",
            "pytest": "tests/agent/test_llm_mode.py::test_llm_timeout_falls_back",
            "why": "계획기가 프레임 예산(llm_timeout_s)보다 느리면 이번 프레임은 신뢰하지 않고 "
                   "규칙 결정을 쓴다. 지연 상한이 UX를 지킨다.",
            "mode": "llm",
            "config": {"llm_timeout_s": 0.001},
            "llm_script": {"low_confidence": {"action": "none"}},
            "llm_sleep_s": 0.05,
            "live_capable": True,
            "steps": [
                {"frame": {"t": 30.0, "face_present": True, "persons": 1, "quality": clean_q,
                           "events": [{"type": "drink", "start": 29.0, "end": 30.0,
                                       "confidence": 0.5}]},
                 "note": "저확신 drink — 계획기가 50ms 걸림(예산 1ms 초과)"},
            ],
        },
        {
            "id": "denied_confirmation_raises_threshold",
            "title": "사람 거부 → 임계 상향(지속)",
            "branch": "human reply -> raise_threshold (persists)",
            "pytest": "tests/agent/test_guardrails_deep.py::test_denial_raises_threshold_and_persists_across_frames",
            "why": "같은 경곗값 이벤트를 사람이 부정하면 그 행동의 확신 임계를 올려, 이후 같은 "
                   "경곗값은 다시 묻지 않는다(학습된 사람 통제).",
            "mode": "deterministic",
            "config": {"second_look_enabled": False},
            "steps": [
                {"frame": {"t": 30.0, "face_present": True, "persons": 1, "quality": clean_q,
                           "events": [{"type": "drink", "start": 29.0, "end": 30.0,
                                       "confidence": 0.5}]},
                 "note": "저확신 drink -> 묻는다", "confirm": False,
                 "after": "사람이 '아니오' -> drink 임계 상향"},
                {"frame": {"t": 120.0, "face_present": True, "persons": 1, "quality": clean_q,
                           "events": [{"type": "drink", "start": 119.0, "end": 120.0,
                                       "confidence": 0.5}]},
                 "note": "같은 확신 0.5의 drink -> 이제 임계 위가 아니라 아래라 묻지 않음"},
            ],
        },
    ]


# --------------------------------------------------------------------------- running

def _vision_summary(fr) -> str:
    q = fr.quality
    bits = [f"face={'있음' if fr.face_present else '없음'}", f"persons={fr.persons}",
            f"quality={'ok' if q.ok else ','.join(q.issues) or 'bad'}"]
    if fr.events:
        evs = ", ".join(f"{e.type}@{e.confidence:.2f}" for e in fr.events)
        bits.append(f"events=[{evs}]")
    return " · ".join(bits)


def _build_agent(scn: dict, *, live_planner: Any, rec: TraceRecorder):
    cfg = PolicyConfig(**(scn.get("config") or {}))
    mode = scn.get("mode", "deterministic")
    vision = None
    if scn.get("vision_variants") is not None or scn.get("vision_raises"):
        vision = StubVision(scn.get("vision_variants"), raises=bool(scn.get("vision_raises")))
    planner = None
    used_live = False
    if mode == "llm":
        if live_planner is not None and scn.get("live_capable"):
            planner, used_live = live_planner, True
        else:
            planner = FakeLLM(scn.get("llm_script") or {},
                              sleep_s=float(scn.get("llm_sleep_s", 0.0)))
    agent = NunchiAgent(vision=vision, mode=mode, config=cfg, planner=planner, recorder=rec)
    return agent, cfg, used_live


def run_one(scn: dict, *, live_planner: Any = None) -> tuple[str, TraceRecorder, bool]:
    """Run one scenario; return (markdown_timeline, recorder, used_live)."""
    rec = TraceRecorder()
    agent, _cfg, used_live = _build_agent(scn, live_planner=live_planner, rec=rec)
    ctx = AgentContext(session_id=scn["id"], **(scn.get("ctx") or {}))
    has_frame = bool(scn.get("vision_variants") is not None or scn.get("vision_raises"))

    md: list[str] = []
    md.append(f"# Demo trace — {scn['title']}\n")
    md.append(f"- **id**: `{scn['id']}`")
    md.append(f"- **모드**: {scn.get('mode')}{'  (LLM 실호출)' if used_live else ''}")
    md.append(f"- **워크플로우 분기**: {scn['branch']}")
    md.append(f"- **대응 테스트**: `{scn['pytest']}`")
    md.append(f"- **왜 Agentic Vision인가**: {scn['why']}\n")
    md.append("타임라인 (프레임 → 비전 결과 → 도구 호출 → 결정 → 사유). 이미지는 없음.\n")

    for i, step in enumerate(scn["steps"], 1):
        fr = _frame_from_dict(step["frame"])
        dec = agent.decide(ctx, fr, _FRAME if has_frame else None)
        line = rec.lines[-1]
        md.append(f"## 스텝 {i} · t={fr.t:.0f}s\n")
        if step.get("note"):
            md.append(f"- 상황: {step['note']}")
        md.append(f"- 비전 결과(OpenCV): {_vision_summary(fr)}")
        if dec.tool_calls:
            md.append("- 도구 호출:")
            for tc in dec.tool_calls:
                args = tc.get("args") or {}
                argstr = ", ".join(f"{k}={v}" for k, v in args.items())
                md.append(f"  - `{tc.get('tool')}`"
                          f"{f'({argstr})' if argstr else '()'}"
                          f" → {tc.get('result_summary', '')}")
        else:
            md.append("- 도구 호출: 없음")
        md.append(f"- **결정**: `{dec.action}`"
                  f"{' (사람 확인 필요)' if dec.needs_human else ''}")
        if dec.message or dec.message_ko:
            md.append(f"  - 메시지(EN): {dec.message or '—'}")
            md.append(f"  - 메시지(KO): {dec.message_ko or '—'}")
        md.append(f"- 사유: `{dec.reason}`  ·  planner=`{line.planner}`")
        if line.result_summary and ("guardrail:" in line.result_summary
                                    or "llm_timeout" in line.result_summary
                                    or "llm_over_cap" in line.result_summary):
            md.append(f"- 폴백 근거: `{line.result_summary}`")
        if dec.evidence:
            keep = {k: v for k, v in dec.evidence.items()
                    if k not in ("note",)}
            md.append(f"- 근거(evidence): `{keep}`")
        if "confirm" in step:
            out = agent.resolve_confirmation(ctx, bool(step["confirm"]))
            verdict = "확정(예)" if step["confirm"] else "부정(아니오)"
            md.append(f"- 사람 응답: {verdict} → {out}")
            if step.get("after"):
                md.append(f"  - 결과: {step['after']}")
        md.append("")

    md.append("---")
    md.append(f"기계 재현용 JSONL: `docs/submission/traces/{scn['id']}.jsonl` "
              "(서비스 `GET /v1/trace/{session_id}`와 같은 포맷, 이미지 없음).")
    return "\n".join(md) + "\n", rec, used_live


def write_all(*, live_planner: Any = None) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    scns = _scenarios()
    index: list[tuple[str, str, str, str]] = []  # (id, title, branch, pytest)
    live_used = 0
    for scn in scns:
        md, rec, used_live = run_one(scn, live_planner=live_planner)
        (OUT / f"{scn['id']}.md").write_text(md, encoding="utf-8")
        rec.write(str(OUT / f"{scn['id']}.jsonl"))
        live_used += int(used_live)
        index.append((scn["id"], scn["title"], scn["branch"], scn["pytest"]))

    # index file
    idx: list[str] = []
    idx.append("# Demo traces (Agentic Vision)\n")
    idx.append("`eval/agent/demo_trace.py`가 생성. 각 시나리오는 사람이 읽는 타임라인(.md)과 "
               "기계 재현용 JSONL(.jsonl)을 함께 둔다. 이미지는 없다.\n")
    idx.append("| # | 시나리오 | 워크플로우 분기 | 대응 테스트 | 타임라인 |")
    idx.append("|---|---|---|---|---|")
    for i, (sid, title, branch, pytest_name) in enumerate(index, 1):
        idx.append(f"| {i} | {title} | {branch} | `{pytest_name}` | [`{sid}.md`]({sid}.md) |")
    idx.append("\n재현: `uv run python eval/agent/demo_trace.py` (결정적, 네트워크 없음). "
               "LLM 실호출 확인: `--live` (Haiku 4.5, captain, 최대 3콜).")
    (OUT / "README.md").write_text("\n".join(idx) + "\n", encoding="utf-8")
    return {"scenarios": len(scns), "live_used": live_used, "out": str(OUT)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="run LLM-capable scenarios against Haiku 4.5 (captain); <=3 calls")
    args = ap.parse_args()

    live_planner = None
    if args.live:
        try:
            from nunchi.agent import BedrockPlanner
            live_planner = BedrockPlanner(profile="captain", region="us-east-1",
                                          max_tokens=160, timeout_s=10.0)
        except Exception as exc:  # noqa: BLE001 - creds/model issues -> deterministic
            print(f"live planner unavailable ({type(exc).__name__}); deterministic only")

    info = write_all(live_planner=live_planner)
    print(f"wrote {info['scenarios']} demo traces to {info['out']} "
          f"(live LLM used: {info['live_used']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
