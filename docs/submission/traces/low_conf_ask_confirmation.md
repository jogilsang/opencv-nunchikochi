# Demo trace — 저확신 → 사람 확인(human-in-the-loop)

- **id**: `low_conf_ask_confirmation`
- **모드**: deterministic
- **워크플로우 분기**: low-confidence 3b (unchanged -> ask)
- **대응 테스트**: `tests/agent/test_scenarios.py`
- **왜 Agentic Vision인가**: 확신이 밴드(0.4~0.6)에 있고 second_look으로도 안 갈리면, 임의로 단정하지 않고 사람에게 예/아니오를 묻는다(사람 통제).

타임라인 (프레임 → 비전 결과 → 도구 호출 → 결정 → 사유). 이미지는 없음.

## 스텝 1 · t=30s

- 상황: 물 마심? 확신 0.5 (애매)
- 비전 결과(OpenCV): face=있음 · persons=1 · quality=ok · events=[drink@0.50]
- 도구 호출:
  - `second_look`(variant=zoom_face) → skipped:no_variant
  - `ask_confirmation`(about=drink) → asked
- **결정**: `ask_confirmation` (사람 확인 필요)
  - 메시지(EN): Did you just take a drink?
  - 메시지(KO): 방금 물을 마셨나요?
- 사유: `low_confidence:drink`  ·  planner=`rules`
- 근거(evidence): `{'behavior': 'drink', 'confidence': 0.5, 'band': [0.4, 0.6]}`

---
기계 재현용 JSONL: `docs/submission/traces/low_conf_ask_confirmation.jsonl` (서비스 `GET /v1/trace/{session_id}`와 같은 포맷, 이미지 없음).
