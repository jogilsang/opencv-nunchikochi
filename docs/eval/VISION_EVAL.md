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

## 7. 재현 절차

```bash
uv run python eval/record_clips.py --light bright     # 그리고 --light dim
# 각 <clip>.labels.json 의 start/end 를 실제 구간으로 다듬기
uv run python eval/run_vision_eval.py --clips eval/clips --out docs/eval/run1 --iou 0.3
# -> docs/eval/run1/vision_eval.json + timeline_*.png 로 위 표를 채운다
```
