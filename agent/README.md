# agent — 결정 루프 (Agentic Vision)

`nunchi.agent`은 OpenCV 출력(`FrameResult`)을 받아 **지각→결정→행동** 한 바퀴를 돌리고,
그 결과를 `Decision`과 JSONL trace로 남긴다. 이미지는 어디에도 들어가지 않는다(개인정보).

> 대회 Agentic Vision 기준: *"시각 결과가 다음 계획·도구 호출·행동·사람 확인 요청을 바꿔야 한다.
> 설명만 하는 챗봇은 불충분."* 아래 trace 예시가 **같은 에이전트가 OpenCV 증거에 따라 다른 행동을
> 한다**는 것을, 그리고 **사람에게 묻기 전에 OpenCV로 다시 보는 능동 지각**(`second_look`)을 증명한다.

## 구성
| 파일 | 역할 |
|---|---|
| `context.py` | `AgentContext`(JSON 직렬화 세션 상태), `PolicyConfig`(튜닝 가능한 임계값 dataclass) |
| `tools.py` | 도구 7종 — 순수 파이썬, JSON in/out, 나중에 Strands `@tool`로 래핑 가능 |
| `policy.py` | 결정론 규칙(우선순위 루프). 숫자 knob은 전부 `PolicyConfig`에 |
| `summary.py` | `SummaryAccumulator`(이벤트 스트림→`SessionSummary`), `compare`(일일 비교) |
| `planner.py` | `Planner` 인터페이스 · `BedrockPlanner`(Converse 직접) · `FakeLLM`(테스트) · 비용/지연 로그 |
| `guardrails.py` | 결정론 가드레일(LLM이 못 넘는 안전·비용·지연·진단 금지 계층) |
| `strands_adapter.py` | 선택 Strands 어댑터(지연 import, 같은 가드레일 통과) |
| `trace.py` | `TraceRecorder`/`TraceLine` — JSONL, image/byte 키 차단, `planner` 필드 |
| `agent.py` | `NunchiAgent.decide / report / resolve_confirmation` (CONTRACTS §2 시그니처) |

## 도구 7종
`get_quality`, `get_metrics_window`, **`second_look`**, `request_recalibration`,
`ask_confirmation`, `send_nudge`, `suppress`. 모두 부작용 없는 순수 함수이며 결과는
"무엇을 하기로 했는지"를 기술할 뿐, 실제 전달(넛지 표시 등)은 서비스·웹 탭이 한다.

**`second_look`(능동 지각)** 은 `vision.analyze_variant(state, frame_bgr, t, variant)`를 호출해
**같은 프레임을 다른 방식으로 다시 본다**. `frame_bgr`는 이번 요청 처리 중에만 존재하는
메모리 참조로 vision에만 넘기고 **저장·반환·trace하지 않는다**(trace엔 variant·전후 수치만).
variant: `enhance`(어두움·흐림 보정), `zoom_face`(얼굴 크롭 확대 재검출), `strict`(임계 상향 재검증).
vision이 없거나 `analyze_variant`가 없으면 `second_look`을 건너뛰고(trace `skipped:no_variant`)
기존 동작으로 폴백한다. 도구 예외는 결정 루프 밖으로 새지 않는다(trace `error:<Type>` 후 안전 폴백).

## 의사결정 표 (입력 증거 → 행동 → 근거)
우선순위 순서. **첫 번째로 맞는 규칙이 이긴다**(안전·견고성이 잔소리보다 우선).
★ = 사람에게 묻기 전에 OpenCV로 다시 보는 **능동 지각** 지점.

| # | 입력 증거(OpenCV `FrameResult` / 컨텍스트) | 호출 도구 | 행동(`Decision.action`) | 근거(`reason`) |
|---|---|---|---|---|
| 0 | 얼굴 없음 + 품질 정상 + persons=0 (자리비움) | `suppress` | `suppress_focus`(조용히) | `away` |
| 1 ★ | 품질 불량(`too_dark`/`blurry`/`no_face`…) | `get_quality`→`second_look(enhance)` | 재분석이 해소하면 **`none`** / 아니면 `request_recalibration` | `second_look:quality_cleared` / `quality:<issue>` |
| 1b | 품질 불량이 `quality_repeat_for_confirm`회 연속 | `get_quality`→`ask_confirmation` | `ask_confirmation`(사람) | `quality_repeated:<n>` |
| 2 | `do_not_disturb` 설정 | `suppress` | `suppress_focus` | `do_not_disturb` |
| 3 ★ | 이벤트 확신 `0.4 ≤ c ≤ 0.6` | `second_look(zoom_face)` | 확신이 범위 밖이면 **`none`**(자동 확정/기각) / 그대로면 `ask_confirmation`(사람) | `second_look:confidence_{confirm,reject}` / `low_confidence:<b>` |
| 4 | 자세 변화 적음 + 깜빡임 낮음 + 지속 신호 없음 | `get_metrics_window`→`suppress` | `suppress_focus` | `focus_window` |
| 5 | 지속 신호(forward_head 등) ≥ `sustained_min_s` | `get_metrics_window`→`send_nudge` | `nudge` | `sustained:<behavior>` |
| 5b | 지속 신호지만 쿨다운 중/일일 상한 초과 | `suppress` | `suppress_focus` | `cooldown:…` / `daily_cap:…` |
| 6 | 그 외 | (`get_metrics_window`) | `none` | `normal` |

- 능동 지각이 성공하면 **사람 개입·재보정을 건너뛴다**. evidence에 `note: "OpenCV re-analysis
  replaced human/..."`와 전후 수치가 남아 "재분석이 사람을 대신했다"가 trace로 증명된다.
- 사람 확인(3·1b)에서 **사용자가 부정하면** `resolve_confirmation(ctx, confirmed=False)`가
  해당 행동의 확신 임계값을 올려(같은 경곗값으로 다시 묻지 않음) 이벤트를 취소한다.

## 기본 임계값과 근거 (`PolicyConfig`)
보수적으로(= 적고 신호가 분명한 넛지만) 잡았다. 전부 코드에서 바꿀 수 있는 dataclass 필드다.

| 필드 | 기본값 | 근거 |
|---|---|---|
| `sustained_min_s` | 180s | 3분 이상 지속돼야 자세 넛지. 순간 동작엔 반응 안 함 |
| `nudge_cooldown_s` | 자세 600s / 눈 300s | 같은 종류를 10분(눈 5분) 안에 다시 넛지하지 않음(잔소리 방지) |
| `daily_nudge_cap` | 20 | 세션당 넛지 상한 |
| `focus_min_quiet_s` | 120s | 2분 이상 조용해야 집중 구간으로 판단 |
| `focus_blink_rate_max` | 0.20/s | 이 이하 깜빡임이면 "낮음" |
| `focus_posture_change_max` | 3.0° | roll 변화 이 이하면 "자세 안정" |
| `quality_repeat_for_confirm` | 3 | 품질 불량 3연속이면 사람에게 확인 |
| `low_conf_lo / hi` | 0.40 / 0.60 | 이 구간 확신이면 단정하지 않고 (재분석 후에도) 사람에게 물음 |
| `second_look_enabled` | True | 사람에게 묻기 전에 OpenCV로 다시 보기 |
| `low_conf_variant` | `zoom_face` | 낮은 확신 이벤트를 더 가까이 보는 기본 variant |

메시지는 **관찰 기반**이고 진단하지 않는다("피곤해 보인다"❌ → "눈 감는 시간이 평소보다 길었어요"✅).
영어가 기본(`message`), 한국어(`message_ko`) 함께.

## 세션 집계 · 일일 비교 · 리포트
- `SummaryAccumulator`: 프레임/이벤트 스트림을 접어 `SessionSummary`(집계 숫자만 — count·
  accumulated seconds·longest streak + 넛지/확인/재보정 수)로 만든다. 서버가 저장하는 건 이 숫자뿐.
  진행 중 이벤트는 `finalize(end_t=…)`에서 마감해 seconds/longest에 반영. 같은 이벤트를 프레임마다
  중복 집계하지 않는다(type+start로 1회).
- `compare(today, previous)`: "어제보다 N% 증가/감소"를 **관찰형 문구**(EN/KO)로. 이전 값이 0이면
  pct는 None(나눗셈 크래시 없음), ±10% 이내는 "about the same". 진단 단어 금지.
- `NunchiAgent.report(summary, previous)`: 템플릿 폴백(EN/KO, 하이라이트 ≤3, 관찰 어투). 이전 날짜가
  있으면 비교 문구를 앞세운다. **Bedrock 생성은 A3**이며 이 템플릿이 실패 시 폴백이 된다.

## trace 예시 (OpenCV 결과가 결정을 바꾼 증거)
`uv run python agent/make_samples.py` 로 재생성. 이미지·바이트 없음.

**`samples/trace_quality.jsonl`** — 품질이 나빠졌다가 회복(능동 지각 OFF 경로):
```
frame_t=3  decision=request_recalibration reason=quality:too_dark   ← 어두운 프레임이 행동을 바꿈
frame_t=7  decision=ask_confirmation      reason=quality_repeated:3 ← 반복되자 사람에게 확인
frame_t=20 decision=none                 (회복)
```

**`samples/trace_nudge.jsonl`** — 지속 자세 신호 → 넛지 → 쿨다운 억제:
```
frame_t=220 decision=nudge     reason=sustained:forward_head  ← 180s 넘자 넛지(send_nudge)
frame_t=260 decision=suppress_focus reason=cooldown:forward_head ← 쿨다운 중이라 억제
```

**`samples/trace_second_look.jsonl`** — ★재분석이 사람 확인 여부를 바꾼다:
```
Scene A  decision=none  reason=second_look:quality_cleared      ← 어두운 프레임 → enhance 재분석이
         tools=[get_quality, second_look]                         깨끗하게 복원 → 사람·재보정 안 거침
Scene B  decision=none  reason=second_look:confidence_confirm:drink ← 확신 0.5 → zoom_face로 0.9 →
         tools=[second_look]                                        자동 확정, 사람 안 물음
Scene C  decision=ask_confirmation reason=low_confidence:yawn    ← 확신 0.5 → zoom_face로도 0.5 →
         tools=[second_look, ask_confirmation]                      그대로라 사람에게 물음
```
A·B(재분석이 해결 → 사람 안 물음) 대 C(재분석해도 불확실 → 사람에게 물음)의 대비가
"OpenCV 재분석이 사람 개입 여부를 바꿨다"를 그대로 보여준다. evidence엔 `confidence_before/after`·
`verdict`·`variant`만 남고 프레임은 없다.

같은 `NunchiAgent`가 입력 `FrameResult`의 **시각 증거**에 따라
`none` / `request_recalibration` / `ask_confirmation` / `nudge` / `suppress_focus`로 **행동을 바꾼다**.
각 줄의 `tool` · `tool_calls` · `evidence` · `reason`이 그 근거를 그대로 담는다.

## LLM 플래너 + 가드레일 (mode="llm", A3)
"Orchestration and appropriate autonomy": **LLM이 허용된 도구 중에서 계획·선택**하되
**결정론 가드레일이 안전·비용·지연을 보장**한다. 모든 프레임이 아니라 **애매한 순간에만** LLM을 쓴다.

**동작**: `decide`는 항상 결정론 결정을 먼저 계산한다(테스트 기준·비용 0). `mode="llm"`이고 그 결정이
애매할 때(`ask_confirmation` / `nudge` / `quality_repeated`)만 플래너에게 계획을 요청한다.
평상시 프레임(정상·쿨다운·집중 등)은 규칙 경로라 **LLM 호출 0·지연 0**. trace에 `planner: "rules"|"llm"`.

```
결정론 decide ─┬─ 애매하지 않음 ──────────────▶ 결정 확정 (planner=rules)
               └─ 애매함(llm 모드) ─▶ planner.plan ─▶ 가드레일
                    ├─ 통과 ─▶ LLM 결정 채택 (planner=llm)
                    └─ 거부/타임아웃/상한/오류 ─▶ 결정론 결정 유지 (planner=rules,
                         trace에 guardrail:<이유> / llm_timeout / llm_over_cap 기록)
```

**가드레일(결정론, LLM이 못 넘음, `guardrails.py`)**: 행동 화이트리스트 · 도구 7종 화이트리스트+인자
스키마 · 넛지 쿨다운·일일 상한 불변 · `do_not_disturb` 준수 · **진단·감정 단정 금지 후처리**(금지 표현
목록 EN/KO → 걸리면 템플릿 문구로 교체) · 메시지 ≤ 200자 · 도구 인자 검증(위반 시 `rejected_by_guardrail`)
· 프롬프트에 **이미지·좌표 원시값 미포함**(`summarise_frame`이 화이트리스트 키만 통과시키고
`assert_image_free`가 frame/bbox/landmark/좌표 키를 거부).

**상한·타임아웃**: 세션당 LLM 호출 `llm_max_calls`(기본 20), 프레임 결정 타임아웃 `llm_timeout_s`(3초),
리포트 타임아웃 `llm_report_timeout_s`(15초·세션 끝 1회라 여유). 초과 시 규칙/템플릿 폴백.

**프레임워크 결정(직접 측정)**: `uv pip install strands-agents` 전체 의존성 트리 **63MB**
(boto3 기준선 28MB → **약 +35MB**). Lambda 패키지 증가가 커서 기본 플래너는 **Bedrock Converse 도구
루프를 직접 구현**(`planner.BedrockPlanner`), Strands는 **선택 어댑터**(`strands_adapter.StrandsPlanner`,
지연 import라 미설치여도 모듈 로드됨)로 둔다. 둘 다 같은 `guardrails`를 통과한다.
boto3/botocore는 Lambda 런타임 기본 제공이라 BedrockPlanner의 실질 추가는 사실상 0.
근거: [Bedrock Converse](https://docs.aws.amazon.com/bedrock/latest/userguide/converse-api.html) ·
[Strands Agents](https://strandsagents.com/).

**모델·비용**: Claude Haiku 4.5 inference profile `us.anthropic.claude-haiku-4-5-20251001-v1:0`,
프로필 `captain`, 리전 `us-east-1`. 호출마다 입력·출력 토큰·지연·추정 비용을 `agent/llm_calls.jsonl`에
기록한다(**프롬프트 원문 없이 sha16 해시·토큰 수만**). 로컬에서 captain SSO 자격 해석에는
`botocore[crt]`가 필요하다(개발용 임시 설치, Lambda는 IAM role이라 불필요).

**실측 스모크(라이브 Bedrock, `agent/smoke_llm.py`, ≤10회)**: 4콜 전부 성공.

| purpose | tokens in | tokens out | 지연 ms | 추정 비용 $ |
|---|---|---|---|---|
| low_confidence | 236 | 139 | 2243 | 0.000931 |
| low_confidence | 237 | 138 | 1776 | 0.000927 |
| nudge_wording | 239 | 147 | 1608 | 0.000974 |
| report | 219 | 149 | 1867 | 0.000964 |
| **평균/합계** | **233** | **143** | **1873** | **건당 ~0.00095 / 세트 합 0.0038** |

- 비용 추정 단가: 입력 $1 / 출력 $5 per 1M tokens(Haiku 4.5 공개가, 게시 전 재확인). 권위 있는 값은 AWS 청구.
- 개발 전체 누적(탐색 9콜 + 스모크 4콜) ≈ **$0.011** — $2 상한 대비 안전.
- 평균 지연 1873ms로 프레임 타임아웃 3초 이내. 3초를 자주 넘으면 `max_tokens` 축소·프롬프트 간소화로 대응.

**trace 예시 `samples/trace_llm.jsonl`** (planner 필드가 규칙/LLM을 구분):
```
frame_t=30  decision=ask_confirmation  planner=llm   ← LLM이 저확신 drink를 개인화해 물음(정상 LLM 결정)
frame_t=60  decision=ask_confirmation  planner=llm   ← 저확신 yawn
frame_t=300 decision=nudge             planner=rules ← LLM이 낸 넛지가 guardrail:violates_cooldown로
            result_summary="nudge:forward_head|guardrail:violates_cooldown"  막혀 규칙 결정으로 폴백
```
정상 LLM 결정(ask_confirmation)과 **가드레일이 막은 라인**(violates_cooldown)이 한 trace에 함께 있다.
리포트는 `source: "llm"`(가드레일 통과) 또는 `"template_fallback"`(실패·타임아웃·진단 교체).

## 테스트
```
uv run pytest tests/agent -q
# 64개: (A1) 정상 2 · 정책 1~5 · DND · 엣지 3 · 오류 2 · trace 증명 2
#       (A2) second_look 9 · 집계·비교·리포트 10
#       (A3) 가드레일 위반 6종+sanitize 12 · LLM 모드(평상시 미호출 / 저확신·넛지 개인화 /
#            거부·진단 교체·상한·타임아웃·예외 폴백 / 리포트 llm·폴백 / 이미지 free) 12
```

## 범위
- A1 결정론 루프, A2 능동 지각(second_look)·집계·비교, **A3 LLM 플래너(Bedrock Converse 직접)+가드레일
  +Strands 선택 어댑터+Bedrock 리포트(+템플릿 폴백)**. `mode="deterministic"`가 기본이자 테스트 기준.
- vision 구현·HTTP·웹·AWS 리소스 생성 없음(Bedrock은 호출만). 입력은 `FrameResult`(+ `second_look`용
  요청 범위 `frame_bgr`)뿐, 이미지·좌표는 저장·반환·trace·프롬프트에 넣지 않는다.
