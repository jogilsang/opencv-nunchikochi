# Demo trace — 저품질 → 능동 지각(second_look) → 결정 변경

- **id**: `second_look_quality_cleared`
- **모드**: deterministic
- **워크플로우 분기**: quality 1b (enhance가 해소)
- **대응 테스트**: `tests/agent/test_second_look.py`
- **왜 Agentic Vision인가**: OpenCV 재분석(enhance)이 어두운 프레임을 깨끗이 복원하면, 사람에게 묻거나 재보정을 요구하는 대신 조용히 넘어간다. 시각 결과가 행동을 바꾼 핵심 사례.

타임라인 (프레임 → 비전 결과 → 도구 호출 → 결정 → 사유). 이미지는 없음.

## 스텝 1 · t=40s

- 상황: 어두워서 얼굴이 안 보임(too_dark, no_face)
- 비전 결과(OpenCV): face=없음 · persons=1 · quality=too_dark,no_face
- 도구 호출:
  - `get_quality`() → too_dark,no_face
  - `second_look`(variant=enhance) → quality_cleared
- **결정**: `none`
- 사유: `second_look:quality_cleared`  ·  planner=`rules`
- 근거(evidence): `{'issues_before': ['too_dark', 'no_face'], 'variant': 'enhance', 'after': {'ok': True, 'issues': [], 'brightness': 118.0, 'sharpness': 210.0, 'face_px': 96}}`

---
기계 재현용 JSONL: `docs/submission/traces/second_look_quality_cleared.jsonl` (서비스 `GET /v1/trace/{session_id}`와 같은 포맷, 이미지 없음).
