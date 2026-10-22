# Demo trace — LLM 타임아웃 → 규칙 폴백

- **id**: `llm_timeout_fallback`
- **모드**: llm
- **워크플로우 분기**: failure: LLM timeout -> planner=rules
- **대응 테스트**: `tests/agent/test_llm_mode.py::test_llm_timeout_falls_back`
- **왜 Agentic Vision인가**: 계획기가 프레임 예산(llm_timeout_s)보다 느리면 이번 프레임은 신뢰하지 않고 규칙 결정을 쓴다. 지연 상한이 UX를 지킨다.

타임라인 (프레임 → 비전 결과 → 도구 호출 → 결정 → 사유). 이미지는 없음.

## 스텝 1 · t=30s

- 상황: 저확신 drink — 계획기가 50ms 걸림(예산 1ms 초과)
- 비전 결과(OpenCV): face=있음 · persons=1 · quality=ok · events=[drink@0.50]
- 도구 호출:
  - `second_look`(variant=zoom_face) → skipped:no_variant
  - `ask_confirmation`(about=drink) → asked
- **결정**: `ask_confirmation` (사람 확인 필요)
  - 메시지(EN): Did you just take a drink?
  - 메시지(KO): 방금 물을 마셨나요?
- 사유: `low_confidence:drink`  ·  planner=`rules`
- 폴백 근거: `low_conf:drink|llm_timeout`
- 근거(evidence): `{'behavior': 'drink', 'confidence': 0.5, 'band': [0.4, 0.6]}`

---
기계 재현용 JSONL: `docs/submission/traces/llm_timeout_fallback.jsonl` (서비스 `GET /v1/trace/{session_id}`와 같은 포맷, 이미지 없음).
