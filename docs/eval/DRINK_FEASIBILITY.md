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
