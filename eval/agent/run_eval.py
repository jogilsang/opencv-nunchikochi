"""Agent evaluation harness. OWNER: agent tab.

Runs every scenario in `scenarios/*.json` through NunchiAgent deterministically
(stubbed vision/LLM) and checks expected tool-call order + final action. Produces
metrics and representative traces, and writes the report. No images anywhere.

Usage:
    uv run python eval/agent/run_eval.py              # deterministic (no network)
    uv run python eval/agent/run_eval.py --live-smoke # minimal Haiku calls (captain)

Exit code 0 iff every scenario passes (deterministic mode).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any

from nunchi.agent import FakeLLM, NunchiAgent, PolicyConfig, TraceRecorder
from nunchi.agent.agent import _frame_from_dict
from nunchi.agent.context import AgentContext

HERE = pathlib.Path(__file__).resolve().parent
SCEN_DIR = HERE / "scenarios"
ADV_DIR = HERE / "scenarios_adversarial"
TRACE_DIR = HERE / "traces"
REPORT = HERE.parents[1] / "docs" / "eval" / "AGENT_EVAL.md"

# representative scenarios whose full trace we persist for judges
_KEEP_TRACES = {"second_look_quality_cleared", "low_conf_ask_confirmation",
                "guardrail_blocks_diagnosis", "llm_timeout_fallback"}


class StubVision:
    """Deterministic stand-in for VisionEngine.analyze_variant (eval-only, no images).

    `variants` maps variant name -> FrameResult dict. `raises` simulates a vision
    tool error. Never stores frames.
    """

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
            # unchanged: echo a minimal same-confidence frame so verdict == unchanged
            return _frame_from_dict({"t": t, "face_present": True, "quality": {"ok": True}})
        return _frame_from_dict({**spec, "t": spec.get("t", t)})


# a request-scoped frame stand-in (never stored/traced)
_FRAME = object()


@dataclass
class StepResult:
    idx: int
    action: str
    planner: str
    tools: list[str]
    reason: str
    ok_action: bool
    ok_tools: bool
    ok_planner: bool


@dataclass
class ScenarioResult:
    id: str
    description: str
    mode: str
    passed: bool
    latency_ms: float
    tool_calls_total: int
    steps: list[StepResult] = field(default_factory=list)
    failure: str = ""
    category: str = ""                  # adversarial scenario category label
    analysis: str = ""                  # optional pre-written failure analysis (scenario JSON)
    second_look_used: bool = False
    second_look_changed: bool = False   # second_look resolved -> decision differed from "ask human"
    asked_human: bool = False
    fell_back: bool = False             # llm proposed but guardrail/timeout/cap -> rules
    crashed: bool = False               # adversarial: agent/harness raised instead of degrading


def _subseq(expected: list[str], actual: list[str]) -> bool:
    """True if `expected` appears as an ordered (not necessarily contiguous) subsequence."""
    it = iter(actual)
    return all(tok in it for tok in expected)


def load_scenarios() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(SCEN_DIR.glob("*.json"))]


def load_adversarial() -> list[dict]:
    if not ADV_DIR.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(ADV_DIR.glob("*.json"))]


def run_scenario_safe(scn: dict, *, live_planner: Any = None) -> ScenarioResult:
    """run_scenario wrapped so an adversarial input that CRASHES is a recorded failure.

    The agent is designed to degrade (never raise) on bad input; if it or the
    harness still raises, we record it as a failed scenario (crashed=True) rather
    than aborting the whole eval. Expectations are NOT adjusted to the result.
    """
    try:
        return run_scenario(scn, live_planner=live_planner)
    except Exception as exc:  # noqa: BLE001 - adversarial: capture crash as failure
        return ScenarioResult(
            id=scn.get("id", "?"), description=scn.get("description", ""),
            mode=scn.get("mode", "deterministic"), passed=False, latency_ms=0.0,
            tool_calls_total=0, failure=f"CRASHED: {type(exc).__name__}: {exc}",
            crashed=True, category=scn.get("category", ""),
            analysis=scn.get("failure_analysis", ""))


def run_scenario(scn: dict, *, live_planner: Any = None) -> ScenarioResult:
    cfg = PolicyConfig(**(scn.get("config") or {}))
    ctx = AgentContext(session_id=scn["id"], **(scn.get("ctx") or {}))
    mode = scn.get("mode", "deterministic")

    vision = None
    if scn.get("vision_variants") is not None or scn.get("vision_raises"):
        vision = StubVision(scn.get("vision_variants"), raises=bool(scn.get("vision_raises")))

    planner = None
    if mode == "llm":
        planner = live_planner if (live_planner is not None and scn.get("live")) \
            else FakeLLM(scn.get("llm_script") or {},
                         raises=bool(scn.get("llm_raises")),
                         sleep_s=float(scn.get("llm_sleep_s", 0.0)))

    rec = TraceRecorder()
    agent = NunchiAgent(vision=vision, mode=mode, config=cfg, planner=planner, recorder=rec)

    res = ScenarioResult(id=scn["id"], description=scn.get("description", ""),
                         mode=mode, passed=True, latency_ms=0.0, tool_calls_total=0,
                         category=scn.get("category", ""),
                         analysis=scn.get("failure_analysis", ""))
    t0 = time.perf_counter()
    for i, step in enumerate(scn["steps"]):
        fr = _frame_from_dict(step["frame"])
        has_frame = bool(scn.get("vision_variants") is not None or scn.get("vision_raises"))
        dec = agent.decide(ctx, fr, _FRAME if has_frame else None)
        if "confirm" in step:
            agent.resolve_confirmation(ctx, bool(step["confirm"]))

        line = rec.lines[-1]
        tools = [tc.get("tool") for tc in dec.tool_calls]
        ok_action = ("expect_action" not in step) or dec.action == step["expect_action"]
        ok_tools = ("expect_tools" not in step) or _subseq(step["expect_tools"], tools)
        ok_planner = ("expect_planner" not in step) or line.planner == step["expect_planner"]
        res.steps.append(StepResult(
            idx=i, action=dec.action, planner=line.planner, tools=tools,
            reason=dec.reason, ok_action=ok_action, ok_tools=ok_tools, ok_planner=ok_planner))
        res.tool_calls_total += len(tools)
        # count a second_look as "used" only when it actually re-analysed (not skipped/error)
        for tc in dec.tool_calls:
            if tc.get("tool") == "second_look":
                rs = str(tc.get("result_summary", ""))
                if not rs.startswith("skipped") and not rs.startswith("error"):
                    res.second_look_used = True
                    if dec.reason.startswith("second_look:"):
                        res.second_look_changed = True
        if dec.needs_human:
            res.asked_human = True
        # bilingual sanity: any user-facing message must have BOTH en + ko
        if (dec.message or dec.message_ko) and not (dec.message and dec.message_ko):
            ok_action = False
            if not res.failure:
                res.failure = f"step {i}: message not bilingual (en/ko both required)"
            res.passed = False
        # adversarial: a step may demand the final message be free of banned (diagnosis) phrases
        if step.get("expect_message_safe"):
            from nunchi.agent import guardrails
            hit = guardrails.contains_banned(dec.message) or guardrails.contains_banned(dec.message_ko)
            if hit:
                if not res.failure:
                    res.failure = f"step {i}: banned phrase leaked into message: {hit!r}"
                res.passed = False
        if "guardrail:" in line.result_summary or "llm_timeout" in line.result_summary \
                or "llm_over_cap" in line.result_summary:
            res.fell_back = True
        if not (ok_action and ok_tools and ok_planner):
            res.passed = False
            if not res.failure:
                exp = {k: step.get(k) for k in ("expect_action", "expect_tools", "expect_planner")
                       if k in step}
                res.failure = (f"step {i}: got action={dec.action} planner={line.planner} "
                               f"tools={tools}; expected {exp}")
    res.latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    if scn["id"] in _KEEP_TRACES:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        rec.write(str(TRACE_DIR / f"{scn['id']}.jsonl"))
    return res


def aggregate(results: list[ScenarioResult]) -> dict[str, Any]:
    n = len(results)
    passed = sum(1 for r in results if r.passed)
    sl_used = [r for r in results if r.second_look_used]
    sl_changed = [r for r in sl_used if r.second_look_changed]
    asked = [r for r in results if r.asked_human]
    fb = [r for r in results if r.fell_back]
    avg_tools = sum(r.tool_calls_total for r in results) / n if n else 0.0
    avg_latency = sum(r.latency_ms for r in results) / n if n else 0.0
    return {
        "scenarios": n,
        "passed": passed,
        "success_rate": round(passed / n, 3) if n else 0.0,
        "second_look_used": len(sl_used),
        "second_look_changed_decision": len(sl_changed),
        "second_look_change_rate": round(len(sl_changed) / len(sl_used), 3) if sl_used else None,
        "asked_human": len(asked),
        "fallbacks": len(fb),
        "avg_tool_calls": round(avg_tools, 2),
        "avg_latency_ms": round(avg_latency, 2),
    }


def write_report(results: list[ScenarioResult], agg: dict[str, Any], *,
                 live: bool, live_note: str,
                 adversarial: list[ScenarioResult] | None = None) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# 에이전트 평가 리포트 (AGENT_EVAL)\n")
    lines.append("`eval/agent/run_eval.py`가 생성. OpenCV 결과가 도구 호출·행동·사람 승인을 "
                 "바꾼다는 것을 수치와 trace로 보인다. 실패는 숨기지 않는다.\n")
    lines.append(f"- 실행 모드: {'결정적 + 라이브 스모크' if live else '결정적(스텁, 네트워크 없음)'}")
    lines.append(f"- LLM 지표: {live_note}\n")

    lines.append("> **일반화 한계**: 아래 과업 성공률은 *우리가 직접 쓴 시나리오*와 *결정적 스텁 비전/LLM* "
                 "기준이다. 실제 카메라·실제 Bedrock 분포에 대한 일반화 증거가 아니라, 명세한 동작이 "
                 "코드에 구현돼 있음을 고정한 회귀 집합이다. 분포 밖·악의적 입력에 대한 강건함은 아래 "
                 "`적대·경계 시나리오` 절에서 별도로 측정하며, 그 결과는 기대값을 사후에 결과에 맞추지 "
                 "않고 통과·실패 그대로 싣는다.\n")

    lines.append("## 지표\n")
    lines.append("| 지표 | 값 |")
    lines.append("|---|---|")
    lines.append(f"| 시나리오 수 | {agg['scenarios']} |")
    lines.append(f"| 과업 성공률 | {agg['passed']}/{agg['scenarios']} = {agg['success_rate']:.1%} |")
    lines.append(f"| second_look 사용 | {agg['second_look_used']} |")
    sr = agg["second_look_change_rate"]
    lines.append(f"| second_look 후 결정 변경 비율 | "
                 f"{agg['second_look_changed_decision']}/{agg['second_look_used']}"
                 f"{f' = {sr:.1%}' if sr is not None else ''} |")
    lines.append(f"| 사람 확인 요청 시나리오 | {agg['asked_human']} |")
    lines.append(f"| 폴백 발동 시나리오 | {agg['fallbacks']} |")
    lines.append(f"| 평균 도구 호출 수 | {agg['avg_tool_calls']} |")
    lines.append(f"| 평균 지연(시나리오당) | {agg['avg_latency_ms']} ms |\n")

    lines.append("## 시나리오별 결과\n")
    lines.append("| # | id | 모드 | 최종 action | planner | 결과 | 비고 |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, r in enumerate(results, 1):
        last = r.steps[-1] if r.steps else None
        action = last.action if last else "-"
        planner = last.planner if last else "-"
        status = "PASS" if r.passed else "**FAIL**"
        note = r.description if r.passed else r.failure
        lines.append(f"| {i} | `{r.id}` | {r.mode} | {action} | {planner} | {status} | {note} |")

    fails = [r for r in results if not r.passed]
    lines.append("\n## 실패 사례 분석\n")
    if not fails:
        lines.append("결정적 모드에서 실패한 시나리오 없음. "
                     "(실패가 생기면 기대값을 결과에 맞추지 않고 원인을 여기에 적는다.)")
    else:
        for r in fails:
            lines.append(f"- `{r.id}`: {r.failure}")

    lines.append("\n## 대표 trace\n")
    lines.append("이미지 없는 JSONL, `eval/agent/traces/`:")
    for name in sorted(_KEEP_TRACES):
        lines.append(f"- `traces/{name}.jsonl`")
    lines.append("\n## 비용·지연 (LLM)\n")
    lines.append(live_note)
    lines.append("\n개발 중 Bedrock 누적 추정 비용은 `agent/llm_calls.jsonl` 기준 약 $0.011로 $2 상한 이내. "
                 "평균 지연·토큰·건당 비용은 `agent/README.md`의 스모크 표 참조.")

    if adversarial is not None:
        lines.extend(_adversarial_section(adversarial))

    lines.extend(_guardrails_section())

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _guardrails_section() -> list[str]:
    """Static note on the deepened guardrail tests + a guardrail defect found & fixed in A5."""
    return [
        "\n## 가드레일 심화 (A5)\n",
        "`tests/agent/test_guardrails_deep.py`(+ 기존 `test_guardrails.py`)가 고정하는 안전 불변:",
        "",
        ("- **trace에 이미지/바이트/좌표 없음**: 원시 bytes·금지 키(frame_bgr·image·landmark·bbox 등)를 "
         "trace 어디에 넣어도 직렬화 전에 제거된다. 프레임을 준 `decide()`도 이미지 없는 trace만 남긴다."),
        ("- **진단 금지(EN/KO)**: 여러 변형(you look/seem/are tired·exhausted·sleepy·drowsy, "
         "disorder·fatigue·burnout, 피곤·졸려·지쳐·우울·스트레스·질환 등)을 차단하고, 관찰 기반 문구는 "
         "오탐하지 않는다."),
        ("- **내장 문구 전수 안전**: 모든 넛지·확인 질문·품질 안내 문구가 관찰 기반이고 EN/KO 둘 다 있으며 "
         "200자 이내다."),
        ("- **쿨다운·일일 상한(정책 레벨)**: 쿨다운 안의 두 번째 넛지, 상한 도달 후의 넛지는 정책 경로에서 "
         "실제로 억제(suppress)되고 카운트가 오르지 않는다."),
        ("- **사람 거부 → 임계 상향 지속**: 경곗값 이벤트를 사람이 부정하면 그 행동의 확신 임계가 오르고, "
         "이후 여러 프레임에서 같은 경곗값을 다시 묻지 않으며, 다른 행동에는 영향이 없다."),
        "- **한/영 일치**: 사용자 메시지는 EN/KO 둘 다 있거나 둘 다 비어 있다.",
        "",
        "### A5에서 발견·수정한 가드레일 결함\n",
        "심화 테스트가 진단-금지 필터의 실제 결함 2건을 드러냈다(별도 커밋으로 수정, 임계값 조정 아님):",
        "",
        ("1. **과광범위(오탐)**: 금지어 `\"you have\"`가 정상 넛지 "
         "\"You have been leaning toward the screen...\"를 진단으로 오분류했다. "
         "→ `\"you have a \"`(병명 류)만 잡도록 좁혀 오탐 제거."),
        ("2. **공백(미탐)**: `\"you seem exhausted/sleepy/drowsy\"` 변형이 차단 목록에 없어 통과했다. "
         "→ `seem` 변형을 보강."),
        "",
        "두 수정 모두 agent 탭 소유(`guardrails.py`)이며 비전·서비스·웹·규칙 임계값은 건드리지 않았다.",
    ]


def _adversarial_section(adv: list[ScenarioResult]) -> list[str]:
    """Render the adversarial/boundary results table. Expectations are NOT tuned to results."""
    out: list[str] = []
    n = len(adv)
    passed = sum(1 for r in adv if r.passed)
    crashed = sum(1 for r in adv if r.crashed)
    out.append("\n## 적대·경계 시나리오\n")
    out.append("`eval/agent/scenarios_adversarial/`. 분포 밖·악의적 입력에 에이전트가 "
               "**안전하게 버티는지**(규칙 폴백·가드레일·죽지 않음)를 본다. 기대값은 먼저 쓰고 "
               "결과에 맞춰 고치지 않는다. 실패·크래시는 그대로 싣고 원인/수정 필요 탭을 적는다.\n")
    out.append(f"- 시나리오 수: {n}")
    out.append(f"- 기대대로 버팀(PASS): {passed}/{n}")
    out.append(f"- 크래시(에이전트가 예외로 죽음): {crashed}\n")
    out.append("| # | id | 유형 | 모드 | 최종 action | planner | 결과 | 기대/비고 |")
    out.append("|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(adv, 1):
        last = r.steps[-1] if r.steps else None
        action = last.action if last else "-"
        planner = last.planner if last else "-"
        if r.crashed:
            status = "**CRASH**"
        elif r.passed:
            status = "PASS"
        else:
            status = "**FAIL**"
        cat = r.category or "-"
        note = r.description if r.passed else r.failure
        out.append(f"| {i} | `{r.id}` | {cat} | {r.mode} | {action} | {planner} | {status} | {note} |")
    fails = [r for r in adv if not r.passed]
    out.append("\n### 적대 실패·크래시 분석\n")
    if not fails:
        out.append("적대 시나리오 전부 기대대로 버팀(폴백·가드레일·죽지 않음). "
                   "예측한 안전 동작과 실제가 일치. 수정 필요 없음.")
    else:
        for r in fails:
            kind = "크래시" if r.crashed else "불일치"
            detail = r.analysis or (
                f"{r.failure} — 원인 분석 후 수정이 필요하면 담당 탭(대개 agent, "
                f"비전 변형이면 vision)으로 분리한다.")
            out.append(f"- `{r.id}` ({kind}): {detail}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-smoke", action="store_true",
                    help="run scenarios marked live against Haiku 4.5 (captain)")
    args = ap.parse_args()

    live_planner = None
    live_note = "미측정(스텁만 실행). 라이브 지표는 `agent/README.md` 스모크 표 참조."
    if args.live_smoke:
        try:
            from nunchi.agent import BedrockPlanner
            live_planner = BedrockPlanner(profile="captain", region="us-east-1",
                                          max_tokens=160, timeout_s=10.0)
            live_note = "라이브 스모크 실행됨(Haiku 4.5, captain). 실패 시 스텁 폴백."
        except Exception as exc:  # noqa: BLE001 - creds/model issues -> stub only
            live_note = f"라이브 호출 실패({type(exc).__name__}) -> 스텁만, LLM 지표 미측정."

    scns = load_scenarios()
    results = [run_scenario(s, live_planner=live_planner) for s in scns]
    agg = aggregate(results)

    adv_scns = load_adversarial()
    adv_results = [run_scenario_safe(s, live_planner=live_planner) for s in adv_scns]
    write_report(results, agg, live=args.live_smoke, live_note=live_note,
                 adversarial=adv_results)

    print(json.dumps(agg, ensure_ascii=False, indent=2))
    if adv_results:
        adv_pass = sum(1 for r in adv_results if r.passed)
        adv_crash = sum(1 for r in adv_results if r.crashed)
        print(f"\nAdversarial: {adv_pass}/{len(adv_results)} held as expected"
              f"{f', {adv_crash} CRASHED' if adv_crash else ''}.")
        for r in adv_results:
            if not r.passed:
                print(f"  - {r.id}: {r.failure}")

    fails = [r for r in results if not r.passed]
    if fails:
        print("\nFAILED scenarios:")
        for r in fails:
            print(f"  - {r.id}: {r.failure}")
        return 1
    print(f"\nAll {len(results)} scenarios passed (deterministic).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
