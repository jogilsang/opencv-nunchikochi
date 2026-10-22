# Graviton 지연 2배(C8 148ms → C10 281ms) 원인 규명 (V11)

C10이 V10 재배포 후 엔진 `latency_ms` 148→281ms(≈1.9×)를 **pose 탓**이라 적었으나
A/B 격리를 하지 않았다(`docs/cloud/LATENCY.md` C10). 내 로컬은 pose +0.1ms였다. 두
사실이 모순이라 격리 측정으로 근본 원인을 찾았다. **추측으로 코드를 고치지 않았다.**

## 결론: **원인 "pose" 는 반증됨(확정). 2배 증가의 진짜 원인은 로컬에서 확정 불가 — C 탭 Lambda A/B 필요(미확정).**

- **pose는 원인이 아니다(확정).** 전체 `analyze` A/B(같은 코드·같은 입력·pose on/off)
  에서 pose 델타는 **median +0.43ms**(messi5, 3회 반복). C10 주장 +133ms와 정면 모순.
- C8(V9)와 C10(V10) 사이의 **hot-path 코드 델타는 pose + 상태 직렬화(schema 3.0)뿐**
  이다(아래 §4 git diff). 둘 다 격리상 ~0.4ms라 2배를 낼 수 없다.
- Lambda **절대 지연의 지배 단계는 FaceMesh 랜드마크(dnn)** 이고, C10이 쓴 입력
  `messi5.jpg`는 320×240에서 얼굴이 **23px(작음)** 이라 **V6 작은-얼굴 재시도**가 매
  프레임 발동해 랜드마크를 **2.5×(+7.56ms 로컬)** 로 키운다. 그러나 이는 **C8·C10
  공통**(재시도=V6, palm=V7 둘 다 C8 zip에 이미 포함, §4)이라 "증가"의 원인은 아니다.
- 로컬에서 **스레드 과다 구독 가설(가설 1)을 재현할 수 없다**: 이 macOS OpenCV는 병렬
  백엔드가 **GCD**라 `cv2.setNumThreads()`·`OPENCV_FOR_THREADS_NUM`·`OMP_NUM_THREADS`가
  전부 무시되고 항상 10을 보고한다. Lambda(Linux)의 OpenCV는 **pthreads**로 다른
  백엔드다. 그래서 2배의 남은 설명(스레드/vCPU 경합, 또는 단순히 C8↔C10이 다른 실행의
  측정 변동)은 **Lambda에서만** A/B할 수 있다 → 스위치(§3)와 단계 로깅 경로(§5) 제공.

## 1. 가설별 증거 표

| # | 가설 | 로컬 증거 | 판정 |
|---|---|---|---|
| — | **pose가 +133ms** | 전체 analyze A/B: pose on 19.15ms vs off 18.72ms → **+0.43ms**(median, messi5 3rep). 단계 분해 pose med **0.15ms** | **반증(확정)** |
| 1 | 스레드 과다 구독 | 로컬 백엔드=**GCD**, `setNumThreads(1)`·`OPENCV_FOR_THREADS_NUM=1`·`OMP_NUM_THREADS=1` 전부 무시(항상 10). Lambda는 pthreads라 백엔드가 다름 | **로컬 재현 불가 → Lambda에서 검증 필요(미확정, 유력 후보)** |
| 2 | 상태 직렬화(schema 3.0) | 단계 분해 serialize med **0.04ms**, blob 4.4KB | **무시 가능(확정)** |
| 3 | 의존성 재패키징(numpy/opencv) | 레포 `uv.lock` 이력 2커밋뿐(scaffold + moto), C8 이후 numpy/opencv 버전 변경 커밋 없음. 현재 numpy 2.5.4 / cv2 5.0.0 | **레포 증거 없음**(Lambda zip 빌드가 레포 lock과 다를 수만 있음 → C 탭 확인) |
| 4 | 작은-얼굴 재시도(V6) | messi5 320×240 얼굴 **23px ≤ 48** → 재시도 발동, 랜드마크 4.89→**12.45ms(+7.56)**. lena(102px)는 +0.02ms | **발동 확정, 단 C8·C10 공통**(절대 지연 주범·증가 원인 아님) |
| 5 | palm(V7) | C8 배포 zip에 `palm_detection_mediapipe`(3.9MB) **이미 포함**(DEPLOY_LOG §Palm, 139MB/3모델) | **C8·C10 공통(증가 원인 아님, 확정)** |

## 2. 단계별 A/B (로컬, messi5 320×240, `bench/profile_stages.py`)

`VisionEngine.analyze`와 같은 호출 순서로 각 단계를 `perf_counter()`로 측정. 로컬은
GCD라 `--threads`가 실제로 바뀌지 않음(요청만 기록, cv2_threads는 10 고정)을 밝혀 둔다.

| 단계 | threads req 10 (med ms) | threads req 1 (med ms) | 비고 |
|---|---|---|---|
| detect(YuNet) | 1.86 | 2.55 | `_analyze`의 두 번째 검출(count_people) |
| **landmark** | **12.39** | **19.65** | FaceMesh dnn + **V6 재시도**(messi5 작은 얼굴) — 지배 단계 |
| quality | 1.68 | 2.68 | 밝기/블러 + 첫 검출 |
| metrics(+filters+overlay) | 0.09 | 0.08 | |
| palm(V7) | 2.42 | 2.98 | 손 근접(drink) |
| **pose(V10)** | **0.16** | **0.15** | solvePnP 6점 + eye-line roll + EMA |
| state_machine | 0.003 | 0.003 | |
| serialize(schema 3.0) | 0.05 | 0.04 | |
| **analyze 실측 전체** | **18.77** | **28.07** | pose off 시 27.81 (−0.26) |

- pose on/off 전체: pose ON med 28.07 / OFF 27.81 (threads req 1) → **+0.26ms**.
- 단계 합(지배=landmark)에서 **pose 기여율 ≈ 0.5~0.8%**. "2배"를 낼 수 있는 단계가
  아니다.

## 3. 스위치 (영구 기능, 운영 안전장치) — `NUNCHI_DISABLE_POSE`

`src/nunchi/vision/engine.py::pose_disabled()`. `NUNCHI_DISABLE_POSE=1`(또는
`true`/`yes`)이면 `analyze`가 `overlay.pose`를 계산·첨부하지 않는다. 기본(미설정/0)은
pose ON. **매 호출마다 환경을 읽어** 재배포 없이 런타임에 켜고 끌 수 있다. 용도:
① C 탭이 Lambda에서 pose 비용을 **직접 A/B**(스위치만 바꿔 같은 코드로 전/후 측정),
② 부하 급증 시 pose를 벗어 지연을 덜어내는 안전밸브. 응답 스키마는 바뀌지 않는다(pose
키가 있거나 없을 뿐, 계약 §1에서 overlay.pose는 선택적).

테스트: `tests/vision/test_headpose_engine.py`(pose 존재/부재 경로), 전체 vision 135
통과.

## 4. C8 ↔ C10 코드·모델 델타 (git / 배포 로그, 읽기 전용)

- hot-path 커밋: V6 재시도 `edaaef4` → V7 palm `46e3171` → **C8 측정** → V10 pose
  `1534204`(C10). 즉 **C8 zip에 V6 재시도·V7 palm 모두 포함**.
- V10 커밋(`1534204`)이 `engine.py`에서 바꾼 것은 **pose 추가뿐** — `landmarks.py`·
  `hands.py`·검출/재시도/palm 경로는 **미변경**(`git show 1534204` grep: extract/retry/
  palm/detect_faces 매칭 0). landmarks.py·hands.py는 V10에서 커밋되지 않음.
- 모델: C8 zip = YuNet+FaceMesh+palm(139MB, 3모델). C10 zip = 동일 3모델(DEPLOY_LOG
  C10: `download_models.py --check` 3/3). **모델 목록 차이 없음.**
- 입력: C8 "~13KB 한 얼굴" = messi5 320×240 q70 = **12,965B**(측정) → C8·C10 **동일
  입력 messi5**(cloud 고정 입력, `docs/cool/BENCH_PLAN.md`).

→ C8·C10은 **같은 모델·같은 입력·재시도/palm 공통**이고 코드 델타는 pose뿐이다.
2배는 pose로 설명 불가하므로, 남은 설명은 **(a) 스레드/vCPU 경합(로컬 재현 불가) 또는
(b) 두 측정이 서로 다른 실행 환경(콜드/웜·동시성·CPU 크레딧)에서 나온 변동**이다.
둘 다 Lambda에서만 가릴 수 있다.

## 5. C 탭에 요청 (Lambda에서 확정할 것)

로컬 GCD 한계로 아래는 **C 탭만** 측정할 수 있다. 서비스 코드 수정이 필요하면 C 탭이 한다.

1. **pose A/B**: 같은 배포에서 `NUNCHI_DISABLE_POSE` 환경변수만 켜고/끄고 각각 웜 30
   프레임 `latency_ms` 측정. 격리상 pose는 ~0.4ms라 2배가 pose면 이 A/B에서 사라져야
   한다(사라지면 pose 무죄가 Lambda에서도 확정).
2. **스레드**: Lambda 환경에 `OMP_NUM_THREADS`/`OPENCV_FOR_THREADS_NUM`을 1·2로 두고
   `latency_ms` 비교. Linux pthreads 백엔드에서 과다 구독이면 스레드 1~2 고정이 개선을
   낸다(그러면 **최소 수정 = 엔진 초기화에서 스레드 수 제한**을 이 탭이 반영).
3. **같은 조건 재측정**: C8·C10을 **연속 같은 세션·같은 웜 상태**로 다시 재어 148 vs
   281이 재현되는지. 재현 안 되면 2배는 측정 변동이었다는 뜻.
4. 단계별 `stages_ms`를 서비스 로그의 숫자 필드로 내보내고 싶으면(응답 스키마 불변),
   엔진이 단계 시간을 반환하도록 이 탭이 **옵션 계측 훅**을 추가할 수 있다 — C 탭이
   원하면 "CONTRACT 불변, 로그 전용" 형태로 협의. 지금은 `bench/profile_stages.py`로
   로컬·EC2에서 같은 분해를 낼 수 있다.

## 6. 왜 지금 코드를 고치지 않는가 (정직)

- **원인이 pose가 아님은 확정**됐으나, 2배의 진짜 원인(스레드 경합 vs 측정 변동)은
  **로컬에서 재현·확정할 수 없다**(GCD). 추측으로 재시도 임계를 낮추거나 스레드를
  강제하면, V6가 해결한 "멀리 앉은 사용자 검출 저하"를 회귀시키거나(재시도) Lambda에서
  역효과(스레드)를 낼 수 있다. messi5의 작은 얼굴은 **벤치 샘플 특성**이지 실사용
  프레임(웹캠 30~50cm, 얼굴 80~150px, 재시도 미발동)이 아니다.
- 확정된 최소 수정(스레드 수 제한)은 **Lambda A/B(§5.2)로 효과가 증명된 뒤** 이 탭이
  엔진 초기화에 넣는 것이 맞다(로컬에선 GCD라 효과 측정 자체가 불가). 그 전까지는
  **스위치(§3)와 계측 스크립트**만 제공한다.

## 7. 재현

```bash
nice -n 15 uv run python bench/profile_stages.py --threads 1 --n 100 --sample messi5.jpg
NUNCHI_DISABLE_POSE=1 nice -n 15 uv run python bench/profile_stages.py --threads 1
# Linux 1-vCPU 에뮬레이션(가능 시): taskset -c 0 ... (macOS엔 taskset 없음)
```

> 수치는 이 개발 Mac(Apple Silicon, GCD 백엔드)에서 직접 측정했다. Graviton(Linux
> pthreads)의 절대값·스레드 거동은 다르며, 2배의 최종 판정은 C 탭의 Lambda A/B로만
> 확정된다.
