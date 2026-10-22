# Demo traces (Agentic Vision)

`eval/agent/demo_trace.py`가 생성. 각 시나리오는 사람이 읽는 타임라인(.md)과 기계 재현용 JSONL(.jsonl)을 함께 둔다. 이미지는 없다.

| # | 시나리오 | 워크플로우 분기 | 대응 테스트 | 타임라인 |
|---|---|---|---|---|
| 1 | 저품질 → 능동 지각(second_look) → 결정 변경 | quality 1b (enhance가 해소) | `tests/agent/test_second_look.py` | [`second_look_quality_cleared.md`](second_look_quality_cleared.md) |
| 2 | 저확신 → 사람 확인(human-in-the-loop) | low-confidence 3b (unchanged -> ask) | `tests/agent/test_scenarios.py` | [`low_conf_ask_confirmation.md`](low_conf_ask_confirmation.md) |
| 3 | 가드레일 차단 → 규칙 폴백 | failure: guardrail reject -> planner=rules | `tests/agent/test_llm_mode.py::test_llm_plan_rejected_by_guardrail_falls_back` | [`guardrail_blocks_action.md`](guardrail_blocks_action.md) |
| 4 | LLM 타임아웃 → 규칙 폴백 | failure: LLM timeout -> planner=rules | `tests/agent/test_llm_mode.py::test_llm_timeout_falls_back` | [`llm_timeout_fallback.md`](llm_timeout_fallback.md) |
| 5 | 사람 거부 → 임계 상향(지속) | human reply -> raise_threshold (persists) | `tests/agent/test_guardrails_deep.py::test_denial_raises_threshold_and_persists_across_frames` | [`denied_confirmation_raises_threshold.md`](denied_confirmation_raises_threshold.md) |

재현: `uv run python eval/agent/demo_trace.py` (결정적, 네트워크 없음). LLM 실호출 확인: `--live` (Haiku 4.5, captain, 최대 3콜).
