#!/usr/bin/env python3
"""눈치코치 비전 평가 하네스 (V4).

클립(또는 프레임 폴더)을 VisionEngine에 흘려 FrameResult.events를 모으고, 라벨
JSON과 구간 단위(temporal IoU)로 비교해 행동별 precision/recall/F1, 얼굴 검출률,
조도별 분해, 지연 분포, 실패 사례(FP/FN) 표, 이벤트 타임라인 PNG(얼굴 이미지 없음)를
만든다. 결과는 docs/eval/ 아래 JSON과 PNG로 떨어진다.

사용:
    uv run python eval/run_vision_eval.py --clips eval/clips --out docs/eval/run1
    uv run python eval/run_vision_eval.py --self-test     # 합성 입력으로 파이프라인만 확인

**정직성**: --self-test / 공개 샘플 수치는 '파이프라인이 동작한다'만 증명한다.
실제 성능은 사용자 라벨 클립(U1)으로만 측정하며, 리포트 dataset 필드로 구분한다.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

# eval/ is at the repo root; make the package importable whether invoked as
# `python eval/run_vision_eval.py` (sys.path[0]=eval/) or `-m`.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from eval.vision_eval.labels import LabelSet, load_labelset
from eval.vision_eval.metrics import (
    DEFAULT_IOU,
    EvalReport,
    Interval,
    aggregate,
    events_to_intervals,
    score_clip,
)
from eval.vision_eval.plot import timeline_png

_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv")


def _calibrate_engine(engine, state, first_frame) -> None:
    """Use the first frame as a frontal baseline (best-effort; skips if no face)."""
    for i in range(20):
        engine.calibrate(state, first_frame, t=i * 0.3)


def _frame_stream_from_video(path: Path, fps_hint: float):
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap or not cap.isOpened():
        raise OSError(f"cannot open video: {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or fps_hint or 2.0
    step = max(1, round(src_fps / max(fps_hint, 0.5)))  # subsample to ~fps_hint
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                t = idx / src_fps
                # downscale to the service resolution for representative latency
                frame = cv2.resize(frame, (320, 240))
                yield t, frame
            idx += 1
    finally:
        cap.release()


def _run_engine_on_frames(engine, frames) -> tuple[list[Interval], float, int, dict[str, float]]:
    """Feed (t, frame) pairs; return predicted intervals, face-detect-rate, n, latency."""
    stream: list[tuple[float, list[dict]]] = []
    lat: list[float] = []
    faces = 0
    n = 0
    state = None
    first = True
    for t, frame in frames:
        if first:
            state = engine.new_session("eval")
            _calibrate_engine(engine, state, frame)
            first = False
        t0 = time.perf_counter()
        r = engine.analyze(state, frame, t=t)
        lat.append((time.perf_counter() - t0) * 1000.0)
        n += 1
        if r.face_present:
            faces += 1
        stream.append((t, [e.to_dict() if hasattr(e, "to_dict") else _ev(e) for e in r.events]))
    pred = events_to_intervals(stream)
    latency = {}
    if lat:
        lat.sort()
        latency = {"median": round(statistics.median(lat), 2),
                   "p95": round(lat[int(len(lat) * 0.95) - 1] if len(lat) > 1 else lat[0], 2)}
    rate = (faces / n) if n else 0.0
    return pred, rate, n, latency


def _ev(e) -> dict:
    return {"type": e.type, "start": e.start, "end": e.end, "confidence": e.confidence}


def _gt_intervals(ls: LabelSet) -> list[Interval]:
    return [Interval(behavior=li.behavior, start=li.start, end=li.end) for li in ls.labels]


def eval_clip(engine, ls: LabelSet, clip_video: Path | None, *, iou_thr: float,
              out_dir: Path, dataset: str) -> EvalReport:
    if clip_video is not None and clip_video.exists():
        frames = _frame_stream_from_video(clip_video, ls.fps_hint or 2.0)
        pred, rate, n, latency = _run_engine_on_frames(engine, frames)
    else:
        pred, rate, n, latency = [], 0.0, 0, {}
    gt = _gt_intervals(ls)
    rep = score_clip(ls.clip, ls.conditions, pred, gt, iou_thr=iou_thr,
                     face_detect_rate=rate, frames=n, latency_ms=latency, dataset=dataset)
    png = out_dir / f"timeline_{ls.clip}.png"
    timeline_png(png, pred=pred, gt=gt, clip=ls.clip)
    return rep


def run_clips_dir(clips_dir: Path, out_dir: Path, *, iou_thr: float) -> dict:
    from nunchi.vision import VisionEngine
    engine = VisionEngine("models")
    out_dir.mkdir(parents=True, exist_ok=True)
    label_files = sorted(clips_dir.glob("*.labels.json"))
    if not label_files:
        raise SystemExit(f"no *.labels.json in {clips_dir} (record with eval/record_clips.py first)")
    reports: list[EvalReport] = []
    for lf in label_files:
        ls = load_labelset(lf)
        video = next((clips_dir / f"{ls.clip}{ext}" for ext in _VIDEO_EXTS
                      if (clips_dir / f"{ls.clip}{ext}").exists()), None)
        dataset = "real-clip" if video else "unmeasured"
        reports.append(eval_clip(engine, ls, video, iou_thr=iou_thr, out_dir=out_dir, dataset=dataset))
    agg = aggregate(reports)
    summary = {"iou_thr": iou_thr, "aggregate": agg,
               "clips": [r.to_dict() for r in reports]}
    (out_dir / "vision_eval.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                              encoding="utf-8")
    _print_summary(summary)
    return summary


def _print_summary(summary: dict) -> None:
    agg = summary["aggregate"]["overall"]
    print(f"\n== 비전 평가 요약 (IoU>={summary['iou_thr']}) ==")
    print(f"{'behavior':<14}{'P':>6}{'R':>6}{'F1':>6}{'TP':>5}{'FP':>5}{'FN':>5}")
    for b, s in sorted(agg.items()):
        print(f"{b:<14}{s['precision']:>6}{s['recall']:>6}{s['f1']:>6}{s['tp']:>5}{s['fp']:>5}{s['fn']:>5}")
    datasets = {c["dataset"] for c in summary["clips"]}
    print(f"\n데이터셋: {sorted(datasets)} (real-clip 외 수치는 파이프라인 검증용)")


def self_test(out_dir: Path, iou_thr: float) -> dict:
    """합성 라벨+합성 예측으로 매칭·지표·PNG 파이프라인을 모델 없이 검증."""
    out_dir.mkdir(parents=True, exist_ok=True)
    gt = [Interval("yawn", 3.0, 5.0), Interval("head_tilt", 8.0, 11.0), Interval("away", 15.0, 20.0)]
    pred = [Interval("yawn", 3.1, 5.2, 0.8),        # TP
            Interval("head_tilt", 8.5, 9.0, 0.6),   # low overlap -> maybe FN/FP by thr
            Interval("blink", 12.0, 12.4, 0.5)]      # FP (no label)
    rep = score_clip("selftest", {"light": "synthetic"}, pred, gt, iou_thr=iou_thr,
                     face_detect_rate=1.0, frames=40,
                     latency_ms={"median": 0.0, "p95": 0.0}, dataset="synthetic")
    timeline_png(out_dir / "timeline_selftest.png", pred=pred, gt=gt, clip="selftest")
    summary = {"iou_thr": iou_thr, "aggregate": aggregate([rep]), "clips": [rep.to_dict()]}
    (out_dir / "vision_eval_selftest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
    _print_summary(summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="눈치코치 비전 평가 하네스")
    ap.add_argument("--clips", help="라벨/영상이 있는 폴더(eval/clips)")
    ap.add_argument("--out", default="docs/eval/run1", help="리포트/PNG 출력 폴더")
    ap.add_argument("--iou", type=float, default=DEFAULT_IOU, help="구간 매칭 IoU 임계(허용 오차)")
    ap.add_argument("--self-test", action="store_true", help="합성 입력으로 파이프라인만 확인")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    if args.self_test or not args.clips:
        if not args.clips:
            print("[info] --clips 미지정 → self-test 모드 (합성 파이프라인 검증)")
        self_test(out_dir, args.iou)
        return 0
    run_clips_dir(Path(args.clips), out_dir, iou_thr=args.iou)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
