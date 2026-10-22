# eval — 비전 평가 하네스 & 클립 녹화 (V tab)

심사용 "평가 증거(실패 사례 포함)"를 만드는 파이프라인이다. 사용자가 **로컬에서**
라벨 클립을 찍고, 그 클립을 엔진에 흘려 행동별 precision/recall/F1·얼굴 검출률·조도별
분해·지연 분포·실패 사례(FP/FN)·이벤트 타임라인 PNG(얼굴 이미지 없음)를 뽑는다.

> ⚠️ **정직성**: 합성/공개 샘플 수치는 "파이프라인이 동작한다"만 증명한다. 실제 성능은
> 사용자 라벨 클립으로만 측정하고, 리포트의 `dataset` 필드로 구분한다
> (`synthetic` / `public-sample` / `real-clip`). 아직 실클립이 없으면
> `docs/eval/VISION_EVAL.md`는 "미측정"으로 둔다.

소유: 이 작업에 한해 `eval/`은 V 탭 소유. 단 **`eval/agent/`는 A 탭 소유**라 건드리지 않는다.

## 1) 라벨 클립 녹화 — `record_clips.py`

웹캠(OpenCV `VideoCapture`)으로 안내·카운트다운에 따라 행동을 연출하며 녹화한다.
영상은 `eval/clips/`(= .gitignore, **레포에 올라가지 않음**)에만 저장되고, 라벨은
`<clip>.labels.json`으로 분리된다. 업로드/전송 코드는 없다.

```bash
# 카메라 없이 계획만 확인
uv run python eval/record_clips.py --dry-run --light bright

# 실제 녹화 (밝은 환경 1세트)
uv run python eval/record_clips.py --light bright
# 어두운 환경 1세트도 (U1 권장: bright + dim 각 1세트 → 14개)
uv run python eval/record_clips.py --light dim
```

- 한 세트 = 7개 클립(정상·away·head_tilt·forward_head·blink·deep_blink·yawn), 약 2분.
- 녹화가 끝나면 각 `<clip>.labels.json`의 `start`/`end`를 **실제 행동 구간**에 맞게
  살짝 다듬으면 평가 정확도가 올라간다(기본값은 전체 길이에서 앞뒤 1초를 뺀 1차 라벨).
- 카메라 열기에 실패하면 macOS 카메라 권한 안내를 출력하고 종료한다
  (시스템 설정 > 개인정보 보호 및 보안 > 카메라에서 터미널 허용).

## 2) 평가 하네스 — `run_vision_eval.py`

클립 폴더(또는 합성 self-test)를 엔진에 흘려 리포트를 만든다.

```bash
# 합성 입력으로 파이프라인만 검증 (모델/카메라 불필요)
uv run python eval/run_vision_eval.py --self-test --out docs/eval/selftest

# 실제 클립 평가
uv run python eval/run_vision_eval.py --clips eval/clips --out docs/eval/run1 --iou 0.3
```

출력(`--out` 폴더): `vision_eval.json`(집계+클립별 점수+실패 표) + `timeline_<clip>.png`.

### 구간 매칭(허용 오차)

예측 이벤트 구간과 라벨 구간을 **행동별 temporal IoU**로 매칭한다. 기본 임계
`IoU ≥ 0.3`(`--iou`로 조정). start/end가 지속시간 게이트로 뜨고 ~2fps로 성기게
샘플링되므로 임계를 느슨하게 둔 것이며, 리포트에 그대로 기록된다. 라벨이 매칭되면
TP(recall), 매칭 안 된 예측은 FP, 매칭 안 된 라벨은 FN → 실패 표로 남는다.

## 3) 라벨 JSON 스키마 (`clip-labels/1`)

```json
{
  "schema": "clip-labels/1",
  "clip": "yawn_bright",
  "fps_hint": 2.0,
  "conditions": {"light": "bright", "angle": "frontal"},
  "labels": [
    {"behavior": "yawn", "start": 3.2, "end": 5.0}
  ]
}
```

- `behavior`는 채점 가능한 7종: `away`, `head_tilt`, `forward_head`, `blink`,
  `deep_blink`, `yawn`, `drink`. `drink`는 V7에서 손바닥 검출기(선택적 모델)로 지원되며,
  모델이 없으면 엔진이 `drink`를 내보내지 않아 라벨이 있으면 전부 미탐(FN)으로 집계된다.
- 스키마 오류는 문제가 난 필드/줄 정보와 함께 `ValueError`(`LabelError`)로 멈춘다.

## 4) 파이프라인 자체 테스트

```bash
uv run pytest tests/vision/test_eval_pipeline.py -q
```

알려진 라벨+예측 → 알려진 지표, 라벨 오류 → `ValueError`, 이벤트 스트림 → 구간,
타임라인 PNG 생성, 녹화 `--dry-run`, 하네스 `--self-test`까지 모델/카메라 없이 검증한다.

## 의존성

추가 의존성 없음. 타임라인 PNG는 `matplotlib` 대신 **`cv2`만으로** 막대(간트)로
그린다(얼굴 픽셀 없음). `pyproject.toml`은 수정하지 않았다.
