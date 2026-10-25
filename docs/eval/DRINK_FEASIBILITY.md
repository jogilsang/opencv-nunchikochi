# drink(물 마시기) 감지 타당성 노트 (V7)

T3 행동 `drink`(컵·병이 입 근처로 올라오는 동작)를 감지할 수 있는지 먼저 판단하고,
가능하면 구현했다.

## 결론: **구현함 (FEASIBLE)** — 손 랜드마크 아닌 **손바닥 검출기**로, 보수적으로.

손-입 근접(palm centre ↔ mouth, 지속)만 쓴다. 컵 자체 검출·21점 손뼈 모델은 추가하지
않았다. 세 게이트(라이선스·cv2.dnn 5.0·지연/용량)를 모두 통과했다. 단, **실제 손 클립
없이는 성능을 주장하지 않는다**(아래 §4 한계).

## 1. 후보와 게이트

| 게이트 | 기준 | 결과 |
|---|---|---|
| 라이선스 | Apache-2.0 | ✅ opencv_zoo `palm_detection_mediapipe` = **Apache-2.0** |
| cv2.dnn 5.0 | readNet+forward 동작 | ✅ 로드 OK, 출력 `(1,2016,18)` box/landmark delta + `(1,2016,1)` score |
| 지연 | 추가 p95 ≤ 12ms @320×240 | ✅ palm forward p95 **2.5ms**; analyze 전체 p95 9.2→**11.9ms (+2.7ms)** |
| 용량 | 저장소 증가 ≤ 8MB | ✅ **3.9MB** (palm만; 21점 handpose 4.1MB는 **추가 안 함**) |

- 출처: opencv/opencv_zoo `models/palm_detection_mediapipe`(README에 Apache 2.0 명시),
  Hugging Face `opencv/palm_detection_mediapipe`.
- 21점 handpose(4.1MB)를 쓰면 palm+handpose=8.0MB로 예산 경계에 걸리고, `drink`에는
  손 **중심 위치**면 충분하므로 **palm 검출기만** 채택(궤적은 프레임 간 손 중심으로).
- SSD 앵커 2016개는 파일에 박지 않고 **코드로 생성**(24×24×2 + 12×12×6). 공식 리터럴과
  **정확히 일치** 확인(`tests/vision/test_hands.py::test_anchor_*`).

## 2. 구현 요약

- `vision/hands.py` `PalmDetector`: 192 레터박스 전처리 → forward → 앵커 디코드
  (`(delta/192 + anchor)*scale`) → NMS → palm 중심. 모델 없으면 `available=False`,
  `detect()`는 `[]`.
- `metrics.mouth_centre`(입술 좌표 평균) + `hands.hand_mouth_distance`(최근접 palm↔입,
  얼굴 높이로 정규화) → `Metrics.hand_mouth_dist`(계약 필드, 기존부터 존재) 채움.
- `events.BehaviorStateMachine`: `drink`를 **SUPPORTED로 승격**(UNSUPPORTED 비움).
  손이 입 근처(`hand_mouth_dist < 0.9 face-height`)이고 **1.2초 이상 지속**일 때만
  `drink`. confidence는 근접도로 산출(가까울수록↑). 임계는 `BehaviorThresholds`
  한 곳.
- **이벤트 스키마 변경 없음.** variant(zoom_face/strict/enhance)에서는 `drink`를 포함해
  어떤 이벤트도 만들지 않음(상태 불변) — second_look과 충돌 없음.
- **모델은 OPTIONAL**: 파일이 없으면 `hand_mouth_dist=None` → `drink` 영원히 미발생,
  나머지 비전은 그대로. `VisionEngine.drink_supported`로 런타임 노출.

## 3. 오탐 위험 점검 (합성)

상태기계 로직은 합성 거리값으로 단위 검증(`test_events.py`): 근접+지속 → drink,
스치고 지나감(짧음) → drink 아님, 손 신호 없음 → drink 아님.

| 위험 상황 | 왜 오탐 가능 | 완화 |
|---|---|---|
| 턱 괴기(chin rest) | 손이 얼굴 하단 근처 | 입 **중심** 기준 거리 + 1.2초 지속. 턱은 입보다 멀어 enter(0.9) 밖이기 쉬움 |
| 입 가리기(기침 등) | 손이 입 바로 앞 | 지속시간으로는 구분 불가 → **보수적 confidence**, 에이전트가 `ask_confirmation` 가능(계약) |
| 하품+손 가림 | yawn과 drink 동시 | 둘 다 각자 이벤트로 나감(상호 배제 안 함). 에이전트가 맥락으로 판단 |
| 배경에서 지나가는 손 | 큰 palm 오검출 | 근접(입 기준) + 지속 필요 → 멀리/짧으면 미발생 |

## 4. 한계 (정직 — 성능 주장 아님)

- **합성 손으로는 검증 불가.** 스킨톤 blob을 입 주변에 합성해도 palm 검출기가 반응하지
  않았다(실제 손 형태 필요). V3의 "합성 감은 눈이 EAR를 못 바꾼다"와 같은 종류의 한계다.
  따라서 **drink의 end-to-end 정확도는 실제 손 클립(U1)으로만** 측정 가능하다. 지금
  수치(지연·앵커 일치·거리 단위 로직)는 "파이프라인이 동작한다"까지만 보장한다.
- 임계값(`drink_enter/exit/hold`)은 보수적 **시작값**이며, 결과에 맞춰 조정해 성능을
  주장하지 않았다. 실제 클립 확보 후 별도 작업에서 튜닝한다.
- 손 중심만 쓰므로(21점 미사용) "컵을 들었는지"는 모른다 — 입 근처 손 동작의 **대리
  신호**다. 그래서 에이전트가 단정 대신 확인(ask_confirmation)에 쓰도록 설계된 계약과
  맞물린다(에이전트 코드는 이 탭에서 수정하지 않음).

## 5. 재현

```bash
uv run python models/download_models.py          # palm 모델 포함(optional, required=false)
uv run pytest tests/vision/test_hands.py tests/vision/test_events.py -q
```

모델 출처: opencv/opencv_zoo `palm_detection_mediapipe_2023feb.onnx`
(Apache-2.0, sha256 `78ff51c3…`, 3.9MB, `models/MANIFEST.json`).

---

## V12 — 타자 칠 때 drink 오탐 줄이기

사용자가 직접 써 보니 **타자만 치는데 `drink` 이벤트가 나왔다**. 원인은 §3에서 "위험"으로만
적어 둔 것들이 실제로 터진 것이다: 판정이 **손↔입 거리 하나**뿐이라, 입 근처로 올라온 손과
키보드/턱 밑의 손을 구분하지 못했다.

### 6. 오탐 경로 재현 (합성 기하)

실제 손 영상 대신, palm 중심 좌표를 직접 넣어 `hand_mouth_distance`가 각 상황에서 뭘
돌려주는지 재현했다(320×240, 얼굴 100px, 입 중심 y=120, `drink_enter`는 V11까지 0.9).
`dy = (palm_y − mouth_y)/face_height`, **음수 = 손이 입보다 위**.

| 상황 | palm y | 정규화 거리 | dy | 구 0.9 enter 통과? |
|---|---|---|---|---|
| 타자(손 키보드, 화면 하단) | 215 | 0.95 | +0.95 | 아니오(겨우 밖) |
| 타자-드리프트(손이 턱 밑까지 올라옴) | 170 | 0.50 | +0.50 | **예 → 오탐** |
| 턱 괴기(chin-rest, 정지) | 165 | 0.45 | +0.45 | **예 → 오탐** |
| 물 마시기(컵 입에) | 120 | 0.05 | 0.00 | 예(정상) |
| 물 마시기(손 입 위) | 100 | 0.20 | −0.20 | 예(정상) |
| 입 가리기 | 118 | 0.02 | −0.02 | 예 |

측정 명령: `tests/vision/test_hands.py`의 `hand_mouth_signal` 테스트가 같은 좌표로 dy 부호를
못박는다. 핵심: **오탐 두 경로(타자-드리프트·턱 괴기)는 거리로는 가깝지만 dy가 +(입 아래).**
정상 마시기는 dy ≈ 0 또는 −(입 위). 거리만으로는 못 가르고, **세로 방향이 가른다.**

### 7. 완화 (조합) — events.py `_update_drink`, hands.py `hand_mouth_signal`

손 거리만 보던 것을 **세 게이트**로 바꿨다(실제 마시기는 유지):

1. **세로 위치**: 손이 입보다 위(턱~입 높이 이상)여야 인정. `dy > drink_dy_max(0.15)`면
   거부. → 타자-드리프트(+0.50)·턱 괴기(+0.45) 탈락, 마시기(0.00/−0.20) 통과.
2. **올라온 궤적**: 입 근처 머묾을 **시작**하려면 최근 `drink_rise_window_s(2.5s)` 안에
   손이 입보다 `drink_rise_from_dy(0.35)` 아래에서 올라온 적이 있어야 한다. 한 자리에
   머무는 손(턱 괴기)은 아래에서 올라온 적이 없어 거부. `_hand_dy_hist`(직렬화됨)에 최근
   (t, dy)만 보관.
3. **조용히 버림**: confirm된 구간이라도 신뢰도가 `drink_min_conf(0.25)` 미만이면 이벤트를
   **내지 않는다**(사람에게 묻는 토스트 과다 방지).

**바꾼 임계값과 근거**:

| 값 | 전 | 후 | 근거 |
|---|---|---|---|
| `drink_enter` | 0.9 | **0.6** | 위 표에서 타자-드리프트(0.50)는 세로 게이트로 이미 탈락하지만, 거리도 조여 "입에서 반 얼굴 안"으로 한정 |
| `drink_hold_s` | 1.2 | **1.6** | 타자 중 손이 입 앞을 스치는 드리프트(수백 ms)보다 길게. 실제 한 모금 지속(≈2s)보다는 짧게 둬서 정상 마시기는 유지. 1.5~2.0 중 1.6으로(1.5는 드리프트에 아슬, 2.0은 짧은 한 모금 놓침) |
| `drink_dy_max` | — | **0.15** | 표의 마시기 dy(0.00/−0.20/−0.02)는 통과, 오탐(+0.45/+0.50)은 탈락하는 경계 |
| `drink_rise_from_dy` | — | **0.35** | 타자 손 시작 위치(+0.5~+0.95)에서 올라오는 궤적을 "올라옴"으로 인정하는 하한. 턱 괴기(계속 +0.1~0.45 부근 정지)는 이 아래로 내려간 기록이 없음 |

구현상 `hands.hand_mouth_signal`이 거리(계약 필드 `hand_mouth_dist` 그대로)와 함께 **부호 있는
세로 오프셋 dy**를 돌려주고, 엔진이 이를 상태기계에 전달한다. `hand_mouth_distance`(계약 필드
공급원)와 계약 `Metrics.hand_mouth_dist`의 **의미·타입은 바꾸지 않았다**(에이전트 영향 없음).

### 8. 측정하지 못한 것 (정직)

- **실제 사용자 캠 클립으로는 검증하지 못했다**(사용자 몫). 위 표·게이트는 전부 **합성 기하**
  이고, "타자 중 손이 입보다 아래/위"라는 가정 자체가 사람·자세·카메라 각도에 따라 달라질 수
  있다. 예컨대 노트북 내장 캠을 올려다보는 각도면 키보드 손도 프레임 위쪽에 잡혀 dy가 작아질
  수 있다 — 이 경우 세로 게이트가 약해지고 **궤적 게이트**가 주 방어선이 된다.
- 세로 오프셋 dy는 얼굴 높이로만 정규화했고 **머리 pitch(고개 숙임)를 보정하지 않았다.** 깊이
  변화가 큰 자세에서 dy 경계(0.15)가 어긋날 수 있다. pitch 보정은 실제 클립으로 효과가 보일 때
  (V10 head-pose 재사용) 후속으로 미룬다 — 지금 추측으로 넣지 않았다.
- `drink_hold_s`·`drink_dy_max`·`drink_rise_*`의 최종값은 **실측 튜닝이 아니라** 합성 표에서
  오탐/정상을 가르는 보수적 경계다. 클립 확보 후 조정 대상.
- 여전히 **입 가리기(기침)**는 궤적(아래→위)과 세로 위치가 마시기와 같을 수 있어 완전히는 못
  거른다. 그래서 조용히-버림 임계와, 에이전트의 확인(ask_confirmation) 설계에 기댄다.

### 9. V12 재현

```bash
uv run pytest tests/vision/test_events.py tests/vision/test_hands.py -q
# 정상 2(올라갔다 머묾 / 컵 없이 입 근처 지속), 예외 2(타자 손 아래 / 턱 괴기 정지),
# 오류 1(손 신호 없음 → drink 없음)
```
