# Demo trace — 사람 거부 → 임계 상향(지속)

- **id**: `denied_confirmation_raises_threshold`
- **모드**: deterministic
- **워크플로우 분기**: human reply -> raise_threshold (persists)
- **대응 테스트**: `tests/agent/test_guardrails_deep.py::test_denial_raises_threshold_and_persists_across_frames`
- **왜 Agentic Vision인가**: 같은 경곗값 이벤트를 사람이 부정하면 그 행동의 확신 임계를 올려, 이후 같은 경곗값은 다시 묻지 않는다(학습된 사람 통제).

타임라인 (프레임 → 비전 결과 → 도구 호출 → 결정 → 사유). 이미지는 없음.

## 스텝 1 · t=30s

- 상황: 저확신 drink -> 묻는다
- 비전 결과(OpenCV): face=있음 · persons=1 · quality=ok · events=[drink@0.50]
- 도구 호출:
  - `second_look`(variant=zoom_face) → skipped:no_variant
  - `ask_confirmation`(about=drink) → asked
- **결정**: `ask_confirmation` (사람 확인 필요)
  - 메시지(EN): Did you just take a drink?
  - 메시지(KO): 방금 물을 마셨나요?
- 사유: `low_confidence:drink`  ·  planner=`rules`
- 근거(evidence): `{'behavior': 'drink', 'confidence': 0.5, 'band': [0.4, 0.6]}`
- 사람 응답: 부정(아니오) → {'resolved': True, 'confirmed': False, 'behavior': 'drink', 'event_cancelled': True, 'new_threshold': 0.65}
  - 결과: 사람이 '아니오' -> drink 임계 상향

## 스텝 2 · t=120s

- 상황: 같은 확신 0.5의 drink -> 이제 임계 위가 아니라 아래라 묻지 않음
- 비전 결과(OpenCV): face=있음 · persons=1 · quality=ok · events=[drink@0.50]
- 도구 호출:
  - `get_metrics_window`(window_s=120.0) → count=2,roll_spread=0.0
  - `suppress`(kind=focus) → suppressed
- **결정**: `suppress_focus`
- 사유: `focus_window`  ·  planner=`rules`
- 근거(evidence): `{'roll_spread_deg': 0.0, 'blink_rate_per_s': 0.0}`

---
기계 재현용 JSONL: `docs/submission/traces/denied_confirmation_raises_threshold.jsonl` (서비스 `GET /v1/trace/{session_id}`와 같은 포맷, 이미지 없음).
