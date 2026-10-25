# 비전 평가 리포트 (VISION_EVAL)

행동 인식 성능의 심사용 증거(실패 사례 포함). **지금은 실제 라벨 클립이 없어
전부 "미측정"이다.** 아래 표는 사용자가 `eval/record_clips.py`로 클립을 찍고
`eval/run_vision_eval.py`를 돌리면 `docs/eval/run1/vision_eval.json`과
`timeline_<clip>.png`에서 자동으로 채워진다. 합성/공개 샘플 수치는 성능으로 쓰지 않는다.

## 1. 데이터 수집 조건

| 항목 | 값 |
|---|---|
| 녹화 도구 | `eval/record_clips.py` (웹캠, 로컬 전용, 영상 비커밋) |
| 클립 수 | _미측정_ (목표 14~20: bright 1세트 + dim 1세트, 각 7개) |
| 조명 | bright / dim (U1) |
| 각도 | frontal (기본), 필요 시 side |
| 프레임률 | ~2 fps (서비스와 동일, 320×240로 다운스케일 후 분석) |
| 보정 | 각 클립 첫 프레임을 정면 baseline으로 사용 |
| 분석 지연(이 개발 Mac, 320×240) | V6+V7+V10 반영, 3회 반복 중앙값: analyze **median ≈ 11.5ms, p95 ≈ 12.3ms** (palm + 머리 pose 경로 포함; 계약 p95<250ms는 Graviton C 탭 측정). V10 머리 pose(solvePnP 6점)가 더하는 비용은 **median/p95 ≈ +0.1ms**(3회 반복 안정 측정; 첫 측정의 +3ms p95는 워밍업 지터였음). 과거 V4의 8.7/9.4ms는 V6(roll-EAR·작은 얼굴 재시도)·V7(palm +~2.7ms) 이전 값이라 폐기 |

## 2. 구간 매칭 기준

- 행동별 **temporal IoU ≥ 0.3**(허용 오차, `--iou`로 조정 가능).
- 라벨 매칭 = TP(recall), 매칭 안 된 예측 = FP(precision 저하), 매칭 안 된 라벨 = FN.
- 근거: start/end가 지속시간 게이트로 뜨고 ~2fps 샘플링이 성겨서 느슨하게 둠.

## 3. 행동별 지표 (precision / recall / F1)

| behavior | P | R | F1 | TP | FP | FN | 비고 |
|---|---|---|---|---|---|---|---|
| away | _미측정_ | _미측정_ | _미측정_ | - | - | - | |
| head_tilt | _미측정_ | _미측정_ | _미측정_ | - | - | - | |
| forward_head | _미측정_ | _미측정_ | _미측정_ | - | - | - | |
| blink | _미측정_ | _미측정_ | _미측정_ | - | - | - | 저fps로 과소계수 가능 |
| deep_blink | _미측정_ | _미측정_ | _미측정_ | - | - | - | |
| yawn | _미측정_ | _미측정_ | _미측정_ | - | - | - | |
| drink | _미측정_ | _미측정_ | _미측정_ | - | - | - | **구현됨(V7)**: palm 검출기 근접·보수적. 실제 손 클립 미검증 |

## 4. 조도·각도별 분해

| 조건 | 클립 수 | 요약 F1 | 비고 |
|---|---|---|---|
| light=bright | _미측정_ | _미측정_ | |
| light=dim | _미측정_ | _미측정_ | 어두울 때 얼굴 검출률·EAR 영향 관찰 |

얼굴 검출률(조건별), 지연 median/p95도 `vision_eval.json`에 함께 기록된다.

## 5. 실패 사례 (오탐 FP / 미탐 FN)

| kind | behavior | start | end | best_iou | confidence | 추정 원인 |
|---|---|---|---|---|---|---|
| _미측정_ | | | | | | |

> 심사 포인트: 실패 사례를 숨기지 않고 타임라인 PNG(얼굴 없는 막대 그래프)와 함께
> 보여 준다. 예: 어두운 환경에서 EAR 상대 하락이 약해 `blink` 미탐, 측면 각도에서
> `head_tilt` 오탐 등.

## 6. 한계 (정직)

- **blink rate 아님**: ~2fps에서 200ms 깜빡임은 대부분 프레임 사이로 빠진다. 단일
  프레임 포착분은 과소계수이며, 대안으로 PERCLOS 유사 지표(눈 감김 프레임 비율)를
  `BehaviorStateMachine.eyes_closed_fraction()`로 제공한다. 지속 감김(≥0.7s)은
  `deep_blink`로 잡는다.
- **drink(V7, 구현됨·실측 미검증)**: OpenCV Zoo 손바닥 검출기(Apache-2.0, 선택적
  모델)로 손 중심이 입 근처(얼굴 높이 대비)에서 지속되면 보수적으로 `drink`를 낸다.
  손 모델이 없으면 `hand_mouth_dist`=None이라 `drink`는 발생하지 않는다. **합성 손은
  검출기가 반응하지 않아** end-to-end 정확도는 실제 손 클립(U1)으로만 검증 가능하다.
  상세: `docs/eval/DRINK_FEASIBILITY.md`.
- **기울어진 얼굴 EAR(V6)**: EAR는 머리 roll만큼 역회전해(roll-aligned) 계산하므로
  기울어진 상태에서도 blink 변동이 줄어든다. 작은 얼굴은 2배 업스케일 1회 재시도로
  검출을 보강한다(아주 작으면 `face_too_small` 안내 우선). 근거/전후 수치:
  `docs/eval/VISION_ROBUSTNESS.md`.
- **합성 한계**: 합성 "감은 눈"은 EAR를 바꾸지 못해(두 모델 모두 그럴듯한 얼굴을
  회귀) blink/yawn의 실제 검증은 **실클립**에서만 유효하다.
- **임계값 미튜닝**: 현재 임계는 보수적 시작값이며, 사용자 클립 확보 후 별도 작업에서
  조정한다(이번 하네스는 조정하지 않음).

## 6b. 머리 3축 자세 overlay.pose (V10)

웹 "자세 인형"용으로 `FrameResult.overlay.pose`에 `{yaw_deg,pitch_deg,roll_deg,
depth,conf}`를 낸다. yaw/pitch는 FaceMesh 6점 + `cv2.solvePnP`(프레임 크기 기반 근사
intrinsics), roll은 눈 선 각도(`head_roll_deg`, 노이즈에 더 강함), depth는 보정 얼굴
높이 대비 비율(face_scale 재사용). 값은 **보정 정면을 0으로 한 상대값**이고 사용자 본인
시점 부호(계약 §1)다: yaw>0 오른쪽으로 고개 돌림, pitch>0 턱 숙임(아래 봄), roll>0
오른쪽 어깨로 기울임.

**합성 회전 오차 표**(알려진 각도로 3D 모델을 회전→투영→추정, `tests/vision/
test_headpose.py`). 같은 모델·intrinsics 생성이라 노이즈 없는 복원 오차는 0이며, 부호가
계약과 일치함을 못박는 용도다. 현실성 확인용으로 랜드마크에 ±1.5px 지터를 준 평균 오차도
함께 적는다(30회):

| 입력 (yaw,pitch,roll) | 추정 부호·크기 | 노이즈 無 오차 | ±1.5px 지터 평균\|오차\| |
|---|---|---|---|
| yaw +30 / −30 | +30.0 / −30.0 | 0.0° | yaw ≈ 3–5° |
| pitch +20 / −20 | +20.0 / −20.0 | 0.0° | pitch ≈ 5° |
| roll +30 / −30 (눈 선) | +30.0 / −30.0 | 0.0° | **roll ≈ 2–3°**(눈 선이 solvePnP roll보다 안정) |
| combo (15,10,−12) | (15,10,−12) | 0.0° | yaw/pitch ≈ 5° |

- **절대 정확도는 주장하지 않는다**: intrinsics·3D 모델이 근사라 상대 변화 추적용이다.
  실제 클립의 각도 정확도는 검증하지 않았다(합성 회전은 수학/부호만 보장).
- roll을 solvePnP가 아니라 눈 선에서 취한 이유: 6점 solvePnP의 roll은 픽셀 노이즈에
  매우 민감(지터 시 수십 도 오차)해서, 이미 필터링된 `head_roll_deg`가 훨씬 안정적이다
  (`test_headpose.py::test_roll_uses_eye_line`로 비교 검증).
- `conf`는 재투영 오차를 얼굴 높이로 정규화한 0~1 값(오차≈얼굴 높이의 8%면 ~0). 낮으면
  웹은 인형을 고정하고 "추정 불안정"을 표시한다. 얼굴 없음·solve 실패 시 pose는 아예
  없다(웹이 인형을 멈춘다).
- 지연: 머리 pose가 더하는 비용은 median/p95 ≈ +0.1ms(§1 지연 표)로 예산(≤3ms) 안.
- 어깨·상체(몸 포즈)는 V10에서 구현하지 않았다(타당성만): `docs/eval/
  BODY_POSE_FEASIBILITY.md` 참고 — fp32 2단계 모델이 용량 예산을 2배 초과하고 int8의
  cv2.dnn 5.0 호환이 미검증이라, 머리 pose로 자세 인형을 구동하고 후속으로 미뤘다.

## 6c. 일상 동작 오탐 점검 (V13)

사용자가 실사용 중 "인형이 엉뚱한 동작을 한다"고 느끼는 것이 가장 큰 품질 위험이라, V12(drink)
와 같은 방식으로 **일상 동작 → 이벤트** 경로를 합성 메트릭(상태기계 입력 스칼라)으로 재현했다.
실제 랜드마크가 아니라 메트릭 값을 직접 넣어 **판정 로직**이 오탐을 내는지만 본다(정확도 주장
아님). 측정 재현: `tests/vision/test_events.py`의 `test_v13_*`.

기준선: ear_open 0.30, mar_rest 0.10, roll_zero 0, pitch_frontal 0.50. 각 임계는
`BehaviorThresholds` 기본값.

| 일상 동작 | 입력 메트릭(지속) | 이벤트 | 재현? | 판단 / 대응 |
|---|---|---|---|---|
| 잠깐 웃음·짧은 발화 | mar 0.25 → 0.10 (0.4s) | — | 안 됨 | hold 게이트(1.2s)가 이미 막음 |
| 안경 고쳐 쓰기·힐끗 아래 | pitch 0.60 → 0.50 (0.3s) | — | 안 됨 | fwd_hold_s(1.5s)가 이미 막음 |
| 긴 문장 말하기 | mar 0.20 유지 | yawn | 됨(인위적) | **안 고침**: 실제 말하기는 MAR가 계속 요동쳐 1.2s 연속 유지가 드묾. yawn_mult를 올리면 **진짜 하품(졸음 신호)을 놓치는 비용**이 커서 보수적으로 유지 |
| 목 스트레칭(옆으로) | roll 15° 유지 | head_tilt | 됨 | **안 고침**: 그것은 실제로 '기운 자세'다. tilt_hold_s(1.0s)로 순간 동작은 거름. 길게 유지하면 뜨는 게 맞음 |
| 화면 가까이(거북목) | face_scale 1.25 | forward_head | 됨 | 의도된 자세 신호(거북목). 정상 |
| **고개 숙여 키보드 보기** | pitch 0.60 유지 | forward_head | 됨 | **부분 의도**: 아래로 숙인 머리 자세라 forward_head로 뜨는 것이 전적으로 틀린 건 아님. pitch 게이트를 올리면 **진짜 거북목을 놓침**. record_clips의 negative 클립으로 실측해 결정(아래 한계) |
| **스크린 보며 실눈** | ear 0.20(frac 0.67) 유지 | ~~deep_blink~~→blink | **고침** | V13: 얕은 눈 좁힘이 '오래 유지됐다는 이유만으로' deep_blink(졸음)로 승격되던 것을 막음 |
| **고개 숙여 눈꺼풀 내려감** | ear 0.12(frac 0.40)+pitch down | deep_blink | 일부 됨 | **부분 완화**: frac 0.40은 deep_frac(0.45) 아래라 '실제로 많이 감긴' 상태로 판정됨. EAR만으로 '아래를 봄'과 '졸려서 감음'을 가르기 어려움(아래 한계) |

### V13 수정 (events.py)

- **deep_blink 지속-승격 게이트**: 종전엔 `is_deep(frac<deep_frac) OR held(≥0.7s)`로, 얕게
  좁힌 눈도 **오래 유지되면** deep_blink가 됐다(실눈·아래 응시). 새로 `deep_hold_frac(0.55)`를
  둬서 **지속으로 승격하려면 그 closure도 어느 정도 감겨 있어야**(frac<0.55) 한다. 즉
  `is_deep OR (held AND frac<deep_hold_frac)`. 결과: 실눈(frac 0.67)은 `blink`로 남고, 진짜
  감긴 눈(frac 0.27, 0.53)과 긴 폐안은 `deep_blink` 유지.
  - **놓치는 비용(정직)**: 0.55~0.70 사이에서 "살짝만 감고 오래 버티는 졸음"은 이제 blink로
    분류된다. 그러나 그런 상태는 졸음 근거로도 약하고, PERCLOS(eyes-closed fraction) 집계는
    여전히 blink_frac 기준으로 잡으므로 '눈 감은 비율' 추세 신호는 유지된다.

### 안 고친 것과 그 이유 (과수정 방지)

- yawn(긴 발화)·head_tilt(스트레칭)·forward_head(고개 숙임)는 **실제 신호와 겹친다**. 임계를
  올리면 오탐은 줄지만 **진짜 하품/기운 자세/거북목을 놓친다**. V12 drink처럼 "거리/방향/궤적"으로
  깔끔히 가를 추가 신호가 없어, 지금은 hold 게이트(순간 동작 차단)에 의존하고 임계는 보수적으로
  둔다. 실제 negative 클립(§7, typing/chin_rest/look_down) 측정 후 근거가 생기면 조정한다.

### 측정하지 못한 것 (정직)

- 전부 **합성 메트릭**이고, "일상 동작이 이 메트릭 값을 만든다"는 매핑 자체가 사람·자세·카메라
  각도에 따라 다르다. 실제 사용자 캠 클립 검증은 사용자 몫이며, 이를 위해 record_clips에
  typing(30s)/chin_rest/look_down_keyboard negative 클립을 넣었다(§7).
- **deep_blink vs 아래 응시**: EAR만으로는 '아래를 봐서 눈꺼풀이 내려간 것'과 '졸려서 감는 것'을
  완전히 가를 수 없다. 머리 pitch(아래를 봄)를 함께 보면 가를 수 있으나(V10 head-pose 재사용),
  실제 클립으로 효과가 확인되기 전에 **추측으로 결합하지 않았다**. look_down 클립 측정 후 결정.
- **forward_head vs 고개 숙임**: 둘 다 pitch-down이라 겹친다. 분리하려면 scale(가까워짐)과
  pitch를 **함께 요구**하는 방법이 있으나 진짜 거북목(가까워지지 않고 목만 빼는 경우)을 놓칠 수
  있어 보류. negative 클립의 forward_head 발생률로 결정.

## 6d. V12 후속 — 낮은 해상도 drink 깜빡임

320×240에서 palm 박스가 프레임마다 흔들려도, 거리 히스테리시스 밴드(enter 0.6 / exit 1.0)
안에서 흔들리는 한 drink 구간은 **하나로 유지**되고 켜졌다 꺼졌다 하지 않는다(테스트
`test_drink_v13_no_flicker_under_jitter_320x240`: 거리 0.4~0.9 지터 + 세로 미세 흔들림에도
완료 구간 0, 진행 유지). pitch 보정(카메라 높이에 따른 손·입 y 비율 왜곡)은 실제 클립 없이
경계값(drink_dy_max)을 흔들 위험이 커서 **구현하지 않고 한계로 남겼다**(DRINK_FEASIBILITY §8).

## 7. 재현 절차

```bash
uv run python eval/record_clips.py --light bright     # 그리고 --light dim
# 각 <clip>.labels.json 의 start/end 를 실제 구간으로 다듬기
uv run python eval/run_vision_eval.py --clips eval/clips --out docs/eval/run1 --iou 0.3
# -> docs/eval/run1/vision_eval.json + timeline_*.png 로 위 표를 채운다
```
