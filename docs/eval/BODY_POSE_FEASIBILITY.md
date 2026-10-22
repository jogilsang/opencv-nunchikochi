# 몸 자세(상체·어깨) 추정 타당성 노트 (V10, 문서만)

웹 "자세 인형"이 머리뿐 아니라 **어깨·상체**까지 움직이게 하려면 몸 포즈 추정 모델이
필요한지 판단한다. 브리프 지시대로 **V10에서는 구현하지 않고** 게이트(라이선스·cv2.dnn
5.0 호환·지연·용량)만 조사해 결론만 적는다. 머리 3축(yaw/pitch/roll/depth)은 이미
V10에서 solvePnP로 구현되어 `overlay.pose`로 나간다(모델 추가 없음).

## 결론: **기술적으로 가능하나 V10 범위에서는 채택하지 않음(DEFER)**

- 자세 인형의 핵심인 "거북목·구부정"은 **머리 pitch(턱 숙임)+depth(화면에 가까움)+
  roll**로 이미 상당 부분 표현된다(V10 완료). 어깨 각도는 "있으면 좋은" 추가 신호다.
- 유일한 Zoo 경로(MediaPipe pose)는 **2단계(person detector → pose estimator)** 이고
  fp32 합계가 **17.56MB로 용량 예산(≤8MB)을 2배 초과**한다. int8 양자화 조합은
  5.17MB로 예산 안이지만 **cv2.dnn 5.0의 block-quantized int8 로드가 미검증**이다.
- 따라서 지금은 머리 pose로 자세 인형을 구동하고, 어깨/상체는 **후속(실클립 확보 +
  int8 cv2.dnn 로드 검증 이후)** 으로 미룬다. 억지로 넣으면 용량·지연·복잡도만 늘고
  데모 실패 위험이 커진다.

## 1. 후보와 게이트

후보는 OpenCV Zoo의 **MediaPipe Pose**(2단계)와 int8 변형이다. 수치는 Hugging Face의
`opencv/*` 저장소 파일 목록에서 직접 확인했다(아래 출처).

| 게이트 | 기준 | MediaPipe Pose fp32 | MediaPipe Pose int8bq |
|---|---|---|---|
| 라이선스 | Apache-2.0 | ✅ Zoo `pose_estimation_mediapipe`·`person_detection_mediapipe` LICENSE = **Apache-2.0** | ✅ 동일 |
| 용량(≤8MB) | 저장소 증가 | ❌ person 12MB + pose 5.56MB = **17.56MB** (2배 초과) | ✅ person 3.48MB + pose 1.69MB = **5.17MB** |
| cv2.dnn 5.0 | readNet+forward 동작 | ⚠️ **미검증**(모델 미다운로드, 타당성 단계). fp32 ONNX는 일반적으로 로드되나 V7에서 본 "new graph engine" 경고처럼 레이어 지원 확인 필요 | ⚠️ **미검증 + 위험**: block-quantized int8 ONNX의 cv2.dnn 5.0 지원은 불확실 |
| 지연(p95 추가) | 매 프레임 ≤25ms @320×240, 또는 가끔 호출 | ⚠️ **미측정**. 2단계(사람 검출→ROI crop→랜드마크)라 매 프레임은 25ms 초과 위험. "가끔 호출"(예: 1~2초마다 1회)이면 분산 가능 | ⚠️ 동일(미측정) |

- MediaPipe pose는 33개 상체·전신 키포인트(어깨·엉덩이·팔꿈치 등)와 세그멘테이션
  마스크를 낸다. **얼굴만 쓰는 우리 파이프라인과 달리 사람 전체가 프레임에 들어와야**
  어깨 각도가 유효한데, 책상 웹캠은 보통 얼굴·상체 일부만 잡혀 어깨 신뢰도가 낮다.
- 단일 단계 대안(OpenPose/Open Model Zoo human-pose-estimation)은 OpenVINO IR·Caffe
  포맷이거나 모델이 크고(수십 MB) cv2.dnn 직접 로드·라이선스가 제각각이라 **8MB 예산과
  "OpenCV만" 원칙에 더 맞지 않는다**(조사 범위에서 제외 사유).

## 2. 왜 지금 머리 pose로 충분한가 (중복 투자 회피)

| 자세 인형이 보여줘야 하는 것 | V10 머리 pose로 커버? | 몸 포즈가 주는 추가분 |
|---|---|---|
| 거북목(머리가 화면으로 전진) | ✅ `depth`>1 + `pitch`(턱 숙임) | 목·어깨 굽힘 각도(정밀도↑) |
| 고개 돌림/숙임/기울임 | ✅ yaw/pitch/roll | — |
| 구부정(상체 전체가 숙음) | △ 머리 depth·pitch로 **근사** | 어깨선 기울기(직접 신호) |
| 한쪽으로 치우쳐 앉음 | ✗ | 어깨 좌우 높이차 |

- 추가분(어깨 각도)은 "있으면 정밀"하지만, 그 대가가 **+17.56MB(또는 미검증 int8)와
  2단계 추론 지연**이다. 데모 품질 기준("실패가 보이지 않을 것")에서 리스크 대비 이득이
  낮다.

## 3. 채택한다면의 설계(미구현, 참고용)

- **가끔 호출**: 매 프레임이 아니라 N초마다 1회 person_detection→pose로 어깨 2점만
  추출해 `overlay`에 `shoulders`(정규화 좌표)와 `shoulder_ear_ratio`(계약에 이미 있는
  None 필드)를 채운다. 사이 프레임은 머리 pose만.
- **OPTIONAL 모델**: palm(V7)과 같이 `required:false`로 두어 모델이 없으면 어깨 신호만
  빠지고 나머지는 그대로 동작하게 한다.
- **검증 순서**: ① int8 ONNX를 실제로 `cv2.dnn.readNet`+`forward`로 로드·추론해
  cv2.dnn 5.0 호환을 **증거로** 확인 → ② @320×240 지연 측정(가끔 호출 분산 포함) →
  ③ 실클립으로 어깨 각도 변화가 의미 있는지 확인. ①에서 막히면 fp32는 용량 초과라
  경로가 닫힌다.

## 4. 한계 (정직 — 성능·호환 주장 아님)

- **cv2.dnn 5.0 로드/추론을 직접 돌려보지 않았다**(타당성 단계라 모델 미다운로드).
  라이선스·용량은 공개 파일에서 확인한 사실이고, cv2.dnn 호환과 지연은 **미검증 가정**
  이다. "가능"은 라이선스·용량(int8) 두 게이트 통과까지만 뜻한다.
- 어깨 추정 정확도는 **실제 사람 클립 없이 주장할 수 없다**(V3 합성 한계와 동일).
- 책상 웹캠 프레이밍(얼굴·상체 일부)에서 MediaPipe pose의 하체 키포인트는 대부분
  보이지 않아 신뢰도가 낮다 — 어깨 2점 위주로만 의미가 있다.

## 5. 출처

- OpenCV Zoo `pose_estimation_mediapipe`: 33 keypoints + segmentation, Apache-2.0,
  `pose_estimation_mediapipe_2023mar.onnx` **5.56MB** / int8bq **1.69MB**
  (huggingface.co/opencv/pose_estimation_mediapipe).
- OpenCV Zoo `person_detection_mediapipe`(2단계의 선행 검출기): Apache-2.0,
  `person_detection_mediapipe_2023mar.onnx` **12MB** / int8bq **3.48MB**
  (huggingface.co/opencv/person_detection_mediapipe).
- MediaPipe Pose가 detector→tracker 2단계라는 점: google-ai-edge/mediapipe pose 문서.

> 라이선스·용량 수치는 게시된 저장소 파일에서 확인했고, cv2.dnn 5.0 호환·지연은 모델을
> 받아 돌려 본 뒤에야 확정할 수 있다. 내용은 라이선스 준수를 위해 재서술했다.
