# 아키텍처와 핵심 결정

## 한 줄
브라우저 웹캠 → (저해상도 JPEG 프레임, 메모리에서만 처리) → **AWS Lambda arm64 컨테이너(Graviton) 안의 OpenCV 5** → 특징·이벤트 → **에이전트(결정 루프)** → 넛지/확인 요청/정상 → DynamoDB(집계 숫자만) → 일일 리포트(Bedrock).

## 대회 요건을 설계로 풀기
| 요건 | 결정 |
|---|---|
| OpenCV 5로 **실질적** 분석 | 얼굴 검출(YuNet `FaceDetectorYN`)·얼굴/자세/손 랜드마크를 **cv2.dnn ONNX 모델(OpenCV Zoo)**로 구현. MediaPipe 등 외부 추론 프레임워크는 쓰지 않는다. 기하·보정·상태기계·품질 점검(블러·밝기·크기)도 OpenCV/NumPy |
| AWS에서 핵심 컴포넌트 실행 | 영상 분석 전부를 AWS(Lambda 컨테이너 arm64)에서 실행. 브라우저는 캡처·표시만 |
| 개인정보·책임 있는 사용 | 동의 화면, 카메라 켜짐 표시, **프레임 미저장**(테스트로 증명), 저장되는 건 집계 숫자뿐, 감정 진단 금지(관찰 기반 신호), 로컬 전용 모드 병기 |
| Agentic Vision | 에이전트가 OpenCV 도구를 호출하는 지각-결정-행동 루프. **시각 결과가 다음 행동을 바꾼다**: 품질 불량→재보정/조명 요청, 불확실→사용자 확인(human-in-the-loop), 지속 신호→넛지, 집중 구간→억제. 각 결정은 trace(JSONL)로 남김 |
| COOL | 같은 코드가 Graviton에서 COOL(Marketplace)로 도는 경로 + x86/pip OpenCV 베이스라인 측정(지연·처리량·비용). COOL 구독은 사용자 승인 필요(DECISIONS) |
| 재현 가능성 | uv.lock 고정, CloudFormation 한 번 배포, 테스트·평가 명령 한 줄 |

## 구성 (영역 = 담당 탭)
```
[web/]  브라우저(getUserMedia) ── JPEG 320x240 @2fps ──▶ [cloud/]  CloudFront(S3 정적) + Lambda Function URL(arm64)
   ▲ 오버레이·넛지·리포트                                        │
   │                                                              ├─▶ [vision/] nunchi.vision.analyze()  (OpenCV 5)
   └──────────── Decision + FrameResult ◀────────────────────────├─▶ [agent/]  nunchi.agent.decide()   (도구 루프·정책·trace)
                                                                  └─▶ DynamoDB(집계) · CloudWatch(지표·로그) · Bedrock(리포트)
```
- 서비스 코드는 `nunchi.vision`, `nunchi.agent` 를 라이브러리로 import 한다(모노레포, 단일 uv 환경). 서로 직접 호출하는 건 `nunchi.contracts` 타입을 통해서만.
- 로컬에서도 같은 서비스를 `uvicorn`으로 띄워 웹과 연동할 수 있어야 한다(개발 속도).

## 동작 6종 (우선순위)
T1: 자리비움, 고개 갸우뚱(roll), 전방 머리(얼굴 크기·위치의 개인 기준 대비 비율; 어깨·자세 모델은 쓰지 않음) / T2: 눈 깜빡임(개인 기준 상대 EAR; 2fps 한계로 분당 횟수 대신 눈 감김 비율 제공), 하품(MAR) / T3: 음료 마시기(손바닥 검출기 palm 중심과 입의 근접 지속; 컵은 검출하지 않으며 실제 클립 검증 전까지 성능을 주장하지 않음). 정확도는 **사용자가 찍은 라벨 클립 + 합성 변형 이미지**로 평가하고 실패 사례를 문서화.

## 비목표(범위 밖)
감정·건강 진단, 다중 인물, 영상 저장·재생, 모바일 앱, 사용자 계정 시스템(데모는 세션 토큰).

## 세션 상태 (C 탭 결정)
Lambda 인스턴스는 메모리를 공유하지 않으므로 보정 baseline·상태기계·AgentContext를 외부에 둔다. **DynamoDB 상태 레코드(pk=SESSION#id, sk=STATE, TTL 24h)** 채택, 서명 토큰 왕복(b)은 기각. 근거: (지연) 프레임당 get+put 2회는 수 ms로 vision p95 250ms 대비 작다. (비용) 세션당 소량 R/W + TTL 자동 삭제라 저렴, 저장은 집계·상태 JSON뿐(이미지 없음). (단순성) 2fps로 계속 갱신되는 가변 상태를 매 프레임 재서명·재전송하지 않고, vision SessionState 직렬화 포맷을 web이 몰라도 서버가 소유한다. (콜드스타트) 상태가 프로세스 밖이라 인스턴스 교체·콜드스타트에 영향 없음. 로컬 개발은 동일 인터페이스의 인메모리 어댑터(`NUNCHI_STATE_BACKEND=memory`)를 쓴다.

## Lambda 패키징 (C 탭 결정)
**zip(a) 채택**, 컨테이너(b) 기각. 근거: (크기) arm64 휠(opencv-python-headless 5.0.0.93 + numpy 2.2.6 + fastapi/mangum/python-multipart)을 `--python-platform aarch64-manylinux2014 --only-binary=:all:`로 풀면 unzipped 실측 140MB(테스트·pyc·dist-info 제거 시 130MB), 모델 ~5MB·앱코드 합쳐 ~135MB로 Lambda unzipped 250MB 한도에 여유. (단순성) 노트북 도커 데몬이 꺼져 있고 교차아키 빌드가 느려 zip이 가장 단순·재현적. (의존성) boto3는 Lambda 런타임에 포함돼 패키지에서 제외, numpy는 manylinux 휠이 있는 2.2.6으로 고정(2.5.4는 aarch64 휠 부재→소스빌드 실패). zip은 S3 경유로 Lambda에 올린다. **전환 조건**: COOL(C4)이 컨테이너/AMI 전용으로만 제공되면 그 경로에 한해 (b) CodeBuild(arm64)→ECR로 바꾼다. 베이스라인·기본 배포는 zip 유지.
