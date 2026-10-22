# Best Agentic Vision — Evidence Package (agent)

Submission evidence that **the vision result changes what the agent plans, which
tools it calls, what action it takes, and when it asks the human** — the required
signal for the Agentic Vision special prize ("a trace where the visual result
changes the subsequent decision, tool call, or approval request").

This file is the agent tab's contribution: every claim below is checkable from
**code + a trace + a test**, with the exact command to reproduce it. Nothing here
is a capability we cannot show running inside the app.

> **Scope / honesty.** This prize is about *the agent inside the running app*, not
> about using an AI coding assistant to build it. We claim only what the
> `nunchi.agent` decision loop does. Limits (stub-based eval, self-written
> scenarios, some LLM metrics measured only in a smoke run) are listed at the end
> and are **not** hidden.

- Agent code: `src/nunchi/agent/` — loop `agent.py`, rules `policy.py`, tools `tools.py`, guardrails `guardrails.py`, LLM planner `planner.py`, trace `trace.py`.
- Workflow diagram spec (source of the submission diagram): [`docs/diagrams/AGENT_WORKFLOW_SPEC.md`](../diagrams/AGENT_WORKFLOW_SPEC.md).
- Aggregate eval + adversarial + guardrail-deep report: [`docs/eval/AGENT_EVAL.md`](../eval/AGENT_EVAL.md).
- Human-readable demo timelines: [`docs/submission/traces/`](traces/) (one `.md` + one `.jsonl` each, **no images**).

---

## 1. 기준별 주장 → 증거 → 재현

판정 기준은 README의 특별상 요구(시각 결과가 결정·도구·승인을 바꾸는 trace + 워크플로우 다이어그램 + trace + 평가)로 정리했다.

| # | 심사 각도 | 주장(앱 안 에이전트가 하는 일) | 증거(파일) | 재현 명령 |
|---|---|---|---|---|
| C1 | 시각 결과가 **행동**을 바꾼다 | 어두워 얼굴이 안 보이던 프레임을 OpenCV `second_look(enhance)`가 복원 → 재보정·사람 호출 대신 `none`(조용히) | `traces/second_look_quality_cleared.md` / `.jsonl`; `src/nunchi/agent/policy.py` 1b; `tests/agent/test_second_look.py::test_enhance_resolves_quality_no_human` | `uv run python eval/agent/demo_trace.py`; `uv run pytest tests/agent/test_second_look.py -q` |
| C2 | 시각 결과가 **도구 호출**을 바꾼다 | 확신이 밴드(0.4~0.6)면 `second_look(zoom_face/strict)`로 다시 보고, confirm/reject면 자동 확정, unchanged면 사람에게 | `traces/low_conf_ask_confirmation.md`; `tests/agent/test_second_look.py::{test_confidence_rises_auto_confirms_no_human,test_confidence_falls_auto_rejects_no_human,test_confidence_unchanged_still_asks_human}` | `uv run pytest tests/agent/test_second_look.py -q` |
| C3 | 시각 결과가 **승인 요청**을 바꾼다 | 저확신 이벤트에만 사람에게 예/아니오를 묻고, second_look이 해소하면 묻지 않는다(사람 통제) | `traces/low_conf_ask_confirmation.md`; `tests/agent/test_scenarios.py::test_low_confidence_asks_confirmation` | `uv run pytest tests/agent/test_scenarios.py -q` |
| C4 | 시각 결과가 **학습된 통제**를 만든다 | 사람이 경곗값 이벤트를 부정하면 그 행동의 확신 임계가 오르고, 이후 같은 경곗값은 다시 묻지 않는다(지속) | `traces/denied_confirmation_raises_threshold.md`; `tests/agent/test_guardrails_deep.py::test_denial_raises_threshold_and_persists_across_frames` | `uv run pytest tests/agent/test_guardrails_deep.py -q` |
| D1 | **실패 처리**: 가드레일 | LLM이 화이트리스트 밖 action/도구/인자를 제안해도 거부하고 규칙 결정이 선다 | `traces/guardrail_blocks_action.md`; `tests/agent/test_llm_mode.py::test_llm_plan_rejected_by_guardrail_falls_back`; `eval/agent/scenarios_adversarial/0{1,2,3}_*.json` | `uv run pytest tests/agent/test_llm_mode.py tests/agent/test_guardrails.py -q` |
| D2 | **실패 처리**: 지연 상한 | 계획기가 프레임 예산(`llm_timeout_s`)보다 느리면 그 프레임은 신뢰하지 않고 규칙 결정 — 결정적 데모는 FakeLLM 지연으로, **실제 Bedrock 호출(2.8s)이 예산을 넘겨 폴백된 것**은 `agent/llm_calls.jsonl`에 기록 | `traces/llm_timeout_fallback.md`; `agent/llm_calls.jsonl`(실호출 2809ms); `tests/agent/test_llm_mode.py::test_llm_timeout_falls_back` | `uv run pytest tests/agent/test_llm_mode.py -q` (live: `uv run python eval/agent/demo_trace.py --live`) |
| D3 | **실패 처리**: 강건함 | 깨진·모순·누락 입력, 도구 예외, 예산 소진에도 에이전트가 예외로 죽지 않고 안전 action으로 강등 | `docs/eval/AGENT_EVAL.md`의 적대 절(9개); `tests/agent/test_adversarial.py::test_agent_never_crashes_on_adversarial_input` | `uv run python eval/agent/run_eval.py`; `uv run pytest tests/agent/test_adversarial.py -q` |
| E1 | **사람 통제**(human-in-the-loop) | 사람에게 묻기 전에 항상 OpenCV가 먼저 다시 본다(second_look); 방해 금지·자리비움·집중 구간은 조용히 | `traces/second_look_quality_cleared.md`, `low_conf_ask_confirmation.md`; `tests/agent/test_scenarios.py::{test_do_not_disturb_suppresses_nudges,test_away_stays_silent,test_focus_window_suppresses}` | `uv run pytest tests/agent/test_scenarios.py -q` |
| F1 | **프라이버시**(책임 있는 운영) | 프레임/이미지/좌표가 trace·반환·프롬프트에 없다; `frame_bgr`는 요청 범위 메모리 참조로만 vision에 전달 | `src/nunchi/agent/trace.py`; `tests/agent/test_guardrails_deep.py::{test_trace_drops_raw_bytes_in_evidence,test_agent_decide_trace_is_image_free_even_with_frame}`; `planner.assert_image_free` | `uv run pytest tests/agent/test_guardrails_deep.py tests/agent/test_llm_mode.py -q` |
| G1 | **다이어그램** | 에이전트 워크플로우(노드·엣지·도구·사람 개입·실패 경로)를 코드 기준으로 명세, Mermaid 3종 | `docs/diagrams/AGENT_WORKFLOW_SPEC.md` | (문서) |
| G2 | **평가** | 22개 결정적 시나리오 100% + 9개 적대 + 가드레일 심화 + 지표(도구 수·지연·second_look 결정변경률) | `docs/eval/AGENT_EVAL.md` | `uv run python eval/agent/run_eval.py` |

한 줄 재현(전체): `uv run pytest tests/agent -q && uv run python eval/agent/run_eval.py && uv run python eval/agent/demo_trace.py`

---

## 2. 워크플로우 분기 ↔ 증거 매핑

[`AGENT_WORKFLOW_SPEC.md`](../diagrams/AGENT_WORKFLOW_SPEC.md) §2(규칙 엣지 0~6)·§5(실패 경로)의 **모든 분기**를 trace 또는 테스트로 연결한다. 증거가 없는 분기는 "미검증"으로 표기한다(과장 금지).

### 결정 엣지 (spec §2)

| 분기 | 결과 | 증거(trace / 테스트) | 상태 |
|---|---|---|---|
| 0 away | suppress_focus | `test_scenarios.py::test_away_stays_silent`, `::test_return_from_away_clears_marker`; adv `04_conflicting_away_and_posture` | 검증 |
| 1a quality 반복 → 확인 | ask_confirmation | 결정적 시나리오 `06_quality_repeated_confirm` (AGENT_EVAL #6) | 검증 |
| 1b quality → second_look 해소 | none | **trace** `second_look_quality_cleared`; `test_second_look.py::test_enhance_resolves_quality_no_human` | 검증 |
| 1c quality → 미해소 재보정 | request_recalibration | `test_second_look.py::test_enhance_does_not_resolve_requests_recalibration`; adv `08_inconsistent_tool_result` | 검증 |
| 2 do_not_disturb | suppress_focus | `test_scenarios.py::test_do_not_disturb_suppresses_nudges` | 검증 |
| 3a 저확신 → second_look confirm/reject | none | `test_second_look.py::test_confidence_rises_auto_confirms_no_human`, `::test_confidence_falls_auto_rejects_no_human` | 검증 |
| 3b 저확신 unchanged → 사람 | ask_confirmation | **trace** `low_conf_ask_confirmation`; `test_second_look.py::test_confidence_unchanged_still_asks_human` | 검증 |
| 4 focus window | suppress_focus | `test_scenarios.py::test_focus_window_suppresses`; 시나리오 `22_focus_window_suppress` | 검증 |
| 5a 지속 → nudge | nudge | `test_scenarios.py::test_sustained_forward_head_triggers_nudge`; 시나리오 `01_nudge_forward_head` | 검증 |
| 5b 쿨다운/상한 → 억제 | suppress_focus | `test_guardrails_deep.py::test_cooldown_suppresses_second_nudge_in_policy`, `::test_daily_cap_blocks_further_nudges_in_policy` | 검증 |
| 6 normal | none | `test_scenarios.py::test_normal_good_frame_does_nothing` | 검증 |
| pending 중 재질문 억제 | none | adv `05_borderline_confidence_oscillation`; `test_adversarial.py` | 검증 |

### LLM refine + 실패 경로 (spec §5)

| 경로 | 처리 | 증거 | 상태 |
|---|---|---|---|
| 정상 프레임 = LLM 미호출 | 규칙(비용 0) | `test_llm_mode.py::test_normal_frame_never_calls_llm` | 검증 |
| LLM 수용(개인화 문구) | planner=llm | `test_llm_mode.py::test_low_confidence_calls_llm_and_uses_plan`, `::test_llm_nudge_wording_personalised`; 라이브 smoke `agent/llm_calls.jsonl` | 검증 |
| 가드레일 거부 | rules 폴백 | **trace** `guardrail_blocks_action`; `test_llm_mode.py::test_llm_plan_rejected_by_guardrail_falls_back` | 검증 |
| 진단 문구 교체 | planner=llm, 메시지 교체 | `test_llm_mode.py::test_llm_diagnosis_message_is_sanitised`; 시나리오 `14_guardrail_blocks_diagnosis` | 검증 |
| 타임아웃 | rules 폴백 | **trace(실호출)** `llm_timeout_fallback`; `test_llm_mode.py::test_llm_timeout_falls_back` | 검증 |
| 계획기 예외 | rules 폴백 | `test_llm_mode.py::test_llm_planner_exception_falls_back`; 시나리오 `17_llm_error_fallback` | 검증 |
| 세션 상한 초과 | rules 폴백 | `test_llm_mode.py::test_llm_over_session_cap_falls_back`; adv `07_llm_budget_zero` | 검증 |
| vision second_look 예외 | 고전 경로 | `test_second_look.py::test_second_look_exception_is_contained`; 시나리오 `18_vision_tool_error_fallback` | 검증 |
| vision 변형 미제공 | 고전 경로 | `test_second_look.py::test_vision_without_analyze_variant_skips` | 검증 |
| decide() 내부 예외 | request_recalibration 강등 | `test_robustness.py::test_internal_exception_is_caught`, `::test_bad_input_type_degrades_to_recalibration` | 검증 |
| 리포트 LLM 실패 | 템플릿 폴백 | `test_llm_mode.py::test_report_llm_diagnosis_falls_back_to_template` | 검증 |

**미검증(현재 없음).** 사람 확인(§4)과 임계 상향은 C3·C4에서, 프라이버시는 F1에서 다룬다. spec에 있는 분기 중 trace·테스트가 비어 있는 것은 없다. 새 분기를 코드에 추가하면 이 표에 "미검증"으로 먼저 올리고 증거가 생기면 바꾼다.

---

## 3. trace 묶음 (사람이 읽는 타임라인)

`eval/agent/demo_trace.py`가 생성. 각 시나리오는 프레임 → 비전 결과 → 도구 호출 → 결정 → 사유를 한 줄씩 보여 주는 `.md`와, 서비스 `GET /v1/trace/{id}`와 같은 포맷의 `.jsonl`을 함께 둔다. **이미지·좌표·바이트 없음.**

1. [`second_look_quality_cleared.md`](traces/second_look_quality_cleared.md) — 저품질 → second_look(enhance) → 결정이 `none`으로 바뀜 (C1)
2. [`low_conf_ask_confirmation.md`](traces/low_conf_ask_confirmation.md) — 저확신 → 사람 확인 (C3/E1)
3. [`guardrail_blocks_action.md`](traces/guardrail_blocks_action.md) — LLM이 금지 action 제안 → 가드레일 거부 → 규칙 (D1)
4. [`llm_timeout_fallback.md`](traces/llm_timeout_fallback.md) — 계획기가 예산 초과 → 규칙 폴백. 결정적 데모는 FakeLLM 지연으로 재현하고, 실제 Bedrock 호출이 예산을 넘긴 증거는 `agent/llm_calls.jsonl`(2809ms)에 있다 (D2)
5. [`denied_confirmation_raises_threshold.md`](traces/denied_confirmation_raises_threshold.md) — 사람 '아니오' → 임계 상향·지속 (C4)

재현: `uv run python eval/agent/demo_trace.py` (결정적). LLM 실호출 확인: `--live`(Haiku 4.5, captain, 1콜).

---

## 4. 비용·지연 (LLM 경로)

- 평상시 프레임은 **규칙 경로**(지연 0, 비용 0). LLM은 애매한 순간에만.
- 개발 중 Bedrock 누적(`agent/llm_calls.jsonl`): 약 **$0.012**(개발 예산 $2의 1% 미만). 호출당 토큰 in~230 / out~145, 지연 ~1.6~2.8s(그래서 프레임 예산 3s·리포트 예산 15s 분리).
- 라이브 호출당 추정 비용 ~$0.001(Haiku 4.5, 입력 $1 / 출력 $5 per 1M 기준, 실제 청구는 AWS).

---

## 5. 정직한 한계 (심사자 주의)

- **평가는 결정적 스텁 기반**이다. `run_eval.py`·`demo_trace.py`의 비전/LLM은 `StubVision`·`FakeLLM`이며(라이브는 명시된 trace만), 실제 카메라·실제 모델 분포에 대한 일반화 증거가 아니라 "명세한 동작이 코드에 있다"를 고정한 회귀·강건 집합이다.
- **시나리오는 우리가 직접 썼다.** 22개 결정적 + 9개 적대 모두 자작이라 100%는 커버리지가 아니라 명세 충족이다. 적대 집합에서 1건(`adv_llm_budget_zero`)은 기대값을 결과에 맞추지 않아 **FAIL로 그대로** 남겼다(에이전트는 정상, 시나리오 설계 결함). [AGENT_EVAL.md 적대 절] 참조.
- **LLM 지표는 스모크 수준**이다. 라이브 호출은 타임아웃 데모 1콜과 A3/A5 스모크 몇 콜뿐(`agent/llm_calls.jsonl`). 대량 분포·사용자 연구는 없다.
- **비전 정확도는 agent 탭 범위 밖**이다. 여기 trace는 "비전 결과가 들어오면 에이전트가 무엇을 하는가"만 보인다. 실제 OpenCV 검출 정확도·p95 지연은 vision/cloud 탭 증거(`docs/eval/`의 비전 쪽, `docs/report/`)에서 다룬다.
- **AI 코딩 도구 사용은 이 상의 대상이 아니다.** 이 문서의 모든 주장은 런타임에 도는 `nunchi.agent`에 대한 것이다.
