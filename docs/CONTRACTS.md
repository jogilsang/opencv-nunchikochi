# 컴포넌트 계약 (인터페이스)

타입 정의의 원본은 `src/nunchi/contracts.py`(지휘자 소유). 변경이 필요하면 담당 탭은 보고서에 "CONTRACT-CHANGE: …"로 적고 지휘자가 반영·중계한다. **이 문서와 코드가 다르면 코드가 우선.**

## 1. Vision (OWNER: vision 탭) — `nunchi.vision`
```python
class VisionEngine:
    def __init__(self, models_dir: str, *, backend: str = "opencv"): ...
    def new_session(self, session_id: str) -> SessionState        # 보정 상태·상태기계 보관(프레임 보관 금지)
    def calibrate(self, state, frame_bgr) -> CalibrationResult    # 정면 5초 보정에서 프레임마다 호출, 완료 시 baseline 확정
    def analyze(self, state, frame_bgr: np.ndarray, t: float) -> FrameResult
    def quality(self, frame_bgr) -> Quality                       # 에이전트 도구로도 노출
    def analyze_variant(self, state, frame_bgr, t: float, variant: str) -> FrameResult
        # 능동 지각("두 번째 보기"): 같은 프레임(요청 범위 메모리)을 다른 방식으로 재분석. variant: "enhance"(CLAHE·감마 보정), "zoom_face"(얼굴 크롭 확대 후 재검출·랜드마크), "strict"(임계 상향 재검증). 상태(보정·상태기계)는 갱신하지 않는다.
def decode_jpeg(data: bytes, max_side: int = 640) -> np.ndarray  # 서비스가 사용. 디코드 후 원본 바이트는 즉시 폐기
```
- `FrameResult.overlay`(선택): 화면 표시용 **좌표만**(0~1 정규화 얼굴 상자, 랜드마크 점, 어깨·손 점). 픽셀·영상은 아니며 저장·로그·trace 금지. 웹이 프리뷰 위에 그려서 "OpenCV가 무엇을 보고 있는지"를 보여 준다(심사자 이해·UX). 좌표계는 서버가 받은 프레임 기준이고 웹이 거울 반전·크기 변환을 한다.
- `FrameResult.overlay.pose`(선택, **자세 인형용 숫자만**): `{"yaw_deg":float,"pitch_deg":float,"roll_deg":float,"depth":float,"conf":float}`.
  각도는 **보정(calibration) 때의 정면 자세를 0으로 한 상대값**이며 사용자 본인 시점 기준이다: `yaw_deg>0` 사용자 오른쪽으로 고개를 돌림, `pitch_deg>0` 턱을 숙임(아래를 봄), `roll_deg>0` 사용자 오른쪽 어깨 쪽으로 기울임. `depth`는 보정 때 얼굴 크기 대비 비율(1.0=같은 거리, >1 화면에 더 가까움, 거북목·구부정의 근거). `conf`는 0~1 신뢰도(낮으면 웹은 인형을 고정하고 "추정 불안정" 표시). 값은 FaceMesh 3D 랜드마크와 OpenCV `solvePnP`로 계산한다(어깨·몸통은 추정하지 않음). 이 값은 trace·DB·로그에 남기지 않고, 웹 브라우저 메모리의 세션 되감기에서만 쓴다.
- **CONTRACT-CHANGE (V14, vision 탭 → `overlay.expr` 추가, 2026-10-25)**: 자세 인형이 **얼굴 표정·목 움직임**을 따라 하도록 `FrameResult.overlay.expr`(선택, **숫자만**)을 더한다. `{"eye_l":0..1|null,"eye_r":0..1|null,"mouth_open":0..1|null,"smile":0..1|null,"brow_raise":0..1|null}`.
  각 값은 **보정(5초 중립)을 기준으로 정규화한 얼굴 움직임**이며 **감정 추정이 아니다**(행복/슬픔 라벨 없음): `eye_*`=눈별 EAR 열림, `mouth_open`=MAR 기반 턱 벌림, `smile`=입꼬리 폭·높이 기하 변화(미소 **모양** 추정, 기쁨 아님), `brow_raise`=눈썹-눈 거리 변화(랜드마크 불안정 시 `null`). 정의·한계는 `docs/eval/FACE_EXPRESSION.md`. 짧은 평활(중앙값3+EMA, 지연 ≤200ms)·신뢰도 낮으면 `null`. 하위 호환: 필드 없으면 `null` 취급.
  `expr`는 **응답(overlay)에만** 있고 DynamoDB 상태 블롭·trace에는 **들어가지 않는다**(표정 평활 필터는 직렬화 안 함; 반례 테스트 `tests/vision/test_expression_privacy.py`). 보정 휴식 기준(`smile_rest`·`brow_rest`)만 `ear_open`·`mar_rest`와 같은 baseline 범주로 상태에 남는다.
  **cloud(C) 탭 할 일**(vision 직접 수정 안 함): ① 서버가 프레임 응답에 `overlay`(=`expr` 포함)를 그대로 실어 web이 받게 한다. ② 스텁(`stubs.py`)은 현재 `overlay`를 만들지 않으므로, 스텁 모드 데모에서 표정 인형을 보이려면 스텁 `analyze`에 `overlay.expr` 예시를 넣는다.
- `analyze`는 **영상을 반환·저장·로그하지 않는다.** 예외는 삼키지 않고 `FrameResult.quality.issues`로 표현 가능한 건 표현하고, 나머지는 예외로 올린다.
- `backend`는 런타임 증거로 채운다(`cv2.getBuildInformation()`·COOL 모듈 존재 확인), 설정값을 그대로 쓰지 않는다.
- 필수 성능: Graviton Lambda 1 vCPU 상당에서 프레임당 **p95 < 250 ms** (최종 측정은 cloud 탭과 협업).

## 2. Agent (OWNER: agent 탭) — `nunchi.agent`
```python
class NunchiAgent:
    def __init__(self, vision: VisionEngine | None, *, mode: str = "deterministic" | "strands", bedrock_model: str | None = None): ...
    def decide(self, ctx: AgentContext, result: FrameResult, frame_bgr: "np.ndarray | None" = None) -> Decision
        # frame_bgr 는 **이번 요청 처리 중에만** 존재하는 메모리 참조(저장·반환·trace 금지). 도구 `second_look` 이 vision.analyze_variant 에 넘긴다.
    def report(self, summary: SessionSummary, previous: SessionSummary | None) -> dict  # {"text_en","text_ko","highlights":[...]} (Bedrock, 실패 시 템플릿 폴백)
```
- `AgentContext`(agent 탭 정의, JSON 직렬화 가능): 세션 시작 시각, 마지막 넛지 시각·종류, 집중 구간 여부, 사용자 설정(방해 금지 등), 최근 N초 이벤트 요약. **프레임/이미지 금지.**
- **도구(tools)**: `get_quality`, `get_metrics_window`, `second_look`(능동 지각: 품질 불량·낮은 확신일 때 사람에게 묻기 전에 `analyze_variant`로 다시 보고, 결과가 해소되면 사람에게 묻지 않고, 아니면 묻는다), `request_recalibration`, `ask_confirmation`, `send_nudge`, `suppress`. 도구 호출·결과·결정 근거는 trace(JSONL, 필드: ts, session_id, frame_t, tool, args, result_summary, decision, evidence)로 남기고 **이미지는 남기지 않는다**.
- 결정론 모드(Bedrock 없이 규칙)가 기본이자 테스트 기준. Strands/Bedrock 모드는 같은 도구를 쓰며 실패하면 결정론으로 폴백.
- **CONTRACT-CHANGE (A11, agent 탭 제안 → 지휘자 수락 2026-10-25, 구현은 C14·W16)**: 알림 진정 + 시간대별 기록을 위해 두 가지를 더한다. 숫자만, 이미지 없음, 하위 호환(필드 없으면 null 취급).
  - `PolicyConfig`(agent 탭 정의) 조용한 기본값: `nudge_cooldown_s` 기본 1200초(행동별 20분), `max_nudges_per_hour=3`(최근 3600초 롤링), `max_confirms_per_hour=2`(같은 종류 연속 금지), `quality_warn_min_sustained_s=30.0`(불량이 30초 이상 지속돼야 경고). 억제된 신호는 버리지 않고 `AgentContext.suppressed_digest`에 세어 리포트에 반영하고 trace에 사유를 남긴다.
  - `SessionSummary`에 `timeline` 추가(제안): `{"bad_posture": {"5m":[{"start_s","events","seconds"},…], "10m":[…], "30m":[…], "60m":[…]}, "per_hour_rate": float|null}`. "나쁜 자세"=`forward_head`+`head_tilt`(deep_blink 제외). `per_hour_rate`는 세션 10분 미만이면 null. 지금은 `nunchi.agent.summary.summary_dict(summary, accumulator)`가 이 필드를 직렬화 결과에 덧붙인다(원본 `contracts.SessionSummary`는 미변경). 지휘자가 반영하면 `contracts.py`로 승격한다.
  - 다회차 비교: `compare(today, previous, *, history=[최근 5개 요약], today_rate)` → `trend={"direction":"improving|same|worsening|na", "today_rate","baseline_rate","n","line_en","line_ko"}`. `history`는 직렬화된 요약 dict(`timeline.per_hour_rate` 보유) 또는 객체. 나쁜 자세 시간당 횟수가 낮을수록 개선.
  - **cloud 탭 할 일**(직접 수정 안 함): ① 세션 종료 시 `summary_dict(summary, acc)`로 `timeline`을 포함해 DynamoDB `USER#<anon>`/`DAY#<date>`에 숫자만 저장. ② `GET /v1/summary`가 최근 5개(`history`)를 함께 반환해 web이 trend를 그릴 수 있게. ③ "같은 사용자" 잇기는 로그인 없이 **브라우저가 보관하는 익명 id**(localStorage의 무작위 토큰)를 `USER#<anon>`로 사용(개인 식별 정보 금지).

## 3. HTTP API (OWNER: cloud 탭, 소비: web·테스트) — 서비스 `nunchi.service`
공통: 헤더 `X-Api-Key`(배포 시 생성), JSON 응답, CORS는 웹 오리진만, 요청 크기 ≤ 200 KB, 비율 제한.

| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `GET /healthz` | - | `{"ok":true,"cv_version","backend","arch","build":"git-sha"}` |
| `POST /v1/sessions` | `{"client_date":"YYYY-MM-DD","lang":"en|ko"}` | `{"session_id","calibration":{"seconds":5,"instruction"}}` |
| `POST /v1/frames` | multipart: `session_id`, `t`(float), `frame`(JPEG ≤ 320x240 권장), 선택 `phase=calibrate|run` | `{"result":FrameResult,"decision":Decision,"calibrated":bool}` |
| `POST /v1/sessions/{id}/end` | - | `{"summary":SessionSummary,"report":{...}}` |
| `GET /v1/summary?date=YYYY-MM-DD` | - | `{"summary":SessionSummary \| null,"previous":SessionSummary \| null}` |
| `GET /v1/trace/{session_id}` | - | trace JSONL(이미지 없음, 심사자용 증거) |

- 프레임은 요청 처리 중에만 메모리에 존재. 디스크·S3·로그에 쓰지 않는다(`tests/test_no_persist.py`가 증명).
- 세션 상태(보정·상태기계)는 Lambda 인스턴스 메모리 대신 **세션 토큰에 서명한 압축 상태 또는 DynamoDB 상태 레코드**로 복원 가능해야 한다(콜드스타트·인스턴스 교체 허용). 결정은 cloud 탭이 하고 `docs/ARCHITECTURE.md`에 기록.

## 4. 저장소 (OWNER: cloud 탭)
DynamoDB 단일 테이블 `nunchi-*`: `pk=SESSION#<id>` `sk=STATE`(보정·상태, TTL 24h), `pk=USER#<anon>` `sk=DAY#<date>`(SessionSummary 집계, TTL 30일). **이미지·랜드마크 원시값 저장 금지.**

## 5. 웹 (OWNER: web 탭)
- 정적 파일(번들러 없이 동작하거나 빌드 산출물을 `web/dist`에 둠). API 주소·키는 `web/config.json`에서 읽는다(커밋 금지: `config.example.json`만).
- **목(mock) 모드**: `?mock=1` 이면 `tests/fixtures/*.json` 형태의 가짜 응답으로 전체 UI가 동작해야 한다(다른 탭을 기다리지 않기 위함).
- 프레임 전송은 320x240 JPEG(품질 0.7) ≤ 2 fps, 탭이 숨겨지면 중지.
