# eval/agent — 에이전트 평가 하네스 (OWNER: agent 탭)

`nunchi.agent`가 **시각 결과에 따라 도구 호출·행동·사람 승인을 바꾼다**는 것을 수치와 trace로
증명한다. 실패 시나리오를 숨기지 않는다.

- `scenarios/*.json` : 시간순 프레임 + (가짜) second_look/LLM/사람응답 + 기대 결과
- `run_eval.py`      : 러너. 시나리오를 결정적으로 돌려 지표·trace·리포트를 만든다
- `traces/`          : 대표 trace(JSONL, 이미지 없음)
- 리포트             : `docs/eval/AGENT_EVAL.md`

## 실행
```
uv run python eval/agent/run_eval.py              # 결정적(스텁) 모드 — 네트워크 없음
uv run python eval/agent/run_eval.py --live-smoke # Haiku 4.5 최소 실호출(captain, 선택)
```
결정적 모드는 `tests/agent/test_eval_harness.py`에서도 통과를 검증한다.

## 시나리오 스키마 (JSON)
```jsonc
{
  "id": "nudge_forward_head",
  "description": "지속 자세 신호 -> 넛지",
  "mode": "deterministic",            // "deterministic" | "llm"
  "config": {"sustained_min_s": 180}, // PolicyConfig 덮어쓰기(선택)
  "ctx": {"do_not_disturb": false},   // AgentContext 초기값(선택)
  "vision_variants": {"enhance": {...FrameResult...}},  // 가짜 second_look 응답(선택)
  "llm_script": {"low_confidence": {...plan...}},       // 가짜 LLM 응답(llm 모드, 선택)
  "steps": [
    {"frame": {...FrameResult dict...},
     "expect_action": "nudge",
     "expect_tools": ["get_metrics_window", "send_nudge"],  // 부분 순서(포함·순서 보존)
     "expect_planner": "rules",        // 선택
     "confirm": false}                 // 이 스텝 뒤 resolve_confirmation 주입(선택)
  ],
  "note": "..."                        // 의도/한계
}
```
`expect_tools`는 **부분 순서 포함**(해당 도구들이 그 순서로 등장) 검사다. 이미지는 어디에도 없다.
