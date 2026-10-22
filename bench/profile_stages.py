#!/usr/bin/env python3
"""Per-stage latency profiler for the vision analyze hot path (V11). OWNER: vision tab.

WHY: C10 reported engine ``latency_ms`` doubling (148 -> 281 ms) on Graviton Lambda
after the V10 redeploy and attributed it to head pose, but did NOT A/B isolate it.
Locally pose was +0.1 ms. This script finds the real cost breakdown by timing each
engine stage (detect / landmark+retry / quality / metrics / palm / pose / state
machine / serialize) with ``time.perf_counter()``, using the SAME engine objects and
call order as ``VisionEngine.analyze`` (no re-implementation of the maths).

It also A/B's the two things that differ between "fast local" and "slow Lambda":
  * OpenCV thread count: ``--threads 1`` (Lambda-like, limited vCPU) vs default (many).
  * head pose on/off via ``NUNCHI_DISABLE_POSE`` (set per run).
Optionally pin to one core on Linux (``taskset -c 0``) to emulate a 1-vCPU Lambda.

READ-ONLY on engine logic: imports and calls the public pipeline pieces; it does not
change the engine. It writes nothing except stdout (the caller pastes numbers into
docs/eval/LATENCY_REGRESSION.md). Ephemeral, like bench_local.py.

Usage:
  nice -n 15 uv run python bench/profile_stages.py --threads 1 --n 100 --sample messi5.jpg
  NUNCHI_DISABLE_POSE=1 nice -n 15 uv run python bench/profile_stages.py --threads 1
  # Linux 1-vCPU emulation:
  taskset -c 0 nice -n 15 uv run python bench/profile_stages.py --threads 1
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nunchi.vision.engine import VisionEngine, pose_disabled
from nunchi.vision.hands import hand_mouth_distance
from nunchi.vision.io import decode_jpeg
from nunchi.vision.landmarks import count_people
from nunchi.vision.metrics import mouth_centre, raw_metrics
from nunchi.vision.overlay import build_overlay

MODELS = REPO / "models"
SAMPLES = REPO / "tests" / "vision" / "_samples"
_STAGES = ["detect", "landmark", "quality", "metrics", "palm", "pose", "state_machine", "serialize"]


def p95(xs: list[float]) -> float:
    s = sorted(xs)
    return s[max(0, round(0.95 * (len(s) - 1)))]


def _profile_once(eng: VisionEngine, st, frame, t: float, disable_pose: bool) -> dict[str, float]:
    """One analyze-equivalent pass, timing each stage. Mirrors VisionEngine._analyze
    order exactly so the sum is comparable to the real analyze latency."""
    stage: dict[str, float] = {}
    H, W = frame.shape[0], frame.shape[1]

    # 1. quality (detect runs inside quality AND again below, as in the real engine)
    c0 = time.perf_counter()
    q = eng.quality(frame)
    stage["quality"] = (time.perf_counter() - c0) * 1000.0

    # 2. landmark extract (includes the V6 small-face retry inside extract_best)
    c0 = time.perf_counter()
    lm = eng._extract(frame)
    stage["landmark"] = (time.perf_counter() - c0) * 1000.0
    face_present = bool(lm and lm.ok)

    # 3. detect (count_people path — a second YuNet detect, as in _analyze)
    c0 = time.perf_counter()
    faces = eng._lm.detect_faces(frame)
    _ = count_people(faces, W, H)
    stage["detect"] = (time.perf_counter() - c0) * 1000.0

    stage["metrics"] = stage["palm"] = stage["pose"] = 0.0
    hand_mouth = None
    metrics = None
    if face_present and lm.pts is not None:
        c0 = time.perf_counter()
        metrics = raw_metrics(lm.pts, baseline_face_px=st.baseline_face_px)
        stage["metrics"] = (time.perf_counter() - c0) * 1000.0

        # palm (only when the model is available, as in the real path)
        if eng._palm.available:
            c0 = time.perf_counter()
            palms = eng._palm.detect(frame)
            mouth = mouth_centre(lm.pts)
            fpx = float(st.baseline_face_px) if st.baseline_face_px else float(lm.bbox[3] if lm.bbox else 0)
            hand_mouth = hand_mouth_distance(palms, mouth, fpx)
            stage["palm"] = (time.perf_counter() - c0) * 1000.0

        # filters update (part of metrics stage in the engine; timed into metrics)
        c0 = time.perf_counter()
        if metrics.head_roll_deg is not None:
            st._roll.update(metrics.head_roll_deg)
        if metrics.head_pitch_proxy is not None:
            st._pitch.update(metrics.head_pitch_proxy)
        if metrics.face_scale is not None:
            st._scale.update(metrics.face_scale)
        if metrics.ear is not None:
            st._ear.update(metrics.ear)
        if metrics.mar is not None:
            st._mar.update(metrics.mar)
        _ = build_overlay(lm.pts, lm.bbox, W, H)
        stage["metrics"] += (time.perf_counter() - c0) * 1000.0

        # pose (head pose = solvePnP + eye-line roll + EMA), A/B switchable
        if not disable_pose:
            c0 = time.perf_counter()
            _ = eng._head_pose(st, lm, W, H, mutate=True)
            stage["pose"] = (time.perf_counter() - c0) * 1000.0

    # state machine
    c0 = time.perf_counter()
    if st._sm is not None:
        st._sm.update(
            face_present=face_present, quality_ok=q.ok,
            ear=(metrics.ear if metrics else None), mar=(metrics.mar if metrics else None),
            roll=(metrics.head_roll_deg if metrics else None),
            pitch=(metrics.head_pitch_proxy if metrics else None),
            face_scale=(metrics.face_scale if metrics else None),
            hand_mouth_dist=hand_mouth, baseline=st.baseline, t=float(t),
        )
    stage["state_machine"] = (time.perf_counter() - c0) * 1000.0

    # serialize (schema 3.0 state blob)
    c0 = time.perf_counter()
    _ = json.dumps(st.to_dict())
    stage["serialize"] = (time.perf_counter() - c0) * 1000.0
    return stage


def run(sample: str, threads: int, n: int, warmup: int) -> dict:
    cv2.setNumThreads(threads)
    disable_pose = pose_disabled()
    frame_path = SAMPLES / sample
    frame = decode_jpeg(frame_path.read_bytes(), max_side=640)
    frame = cv2.resize(frame, (320, 240))  # the service downscales to 320x240
    eng = VisionEngine(str(MODELS))
    st = eng.new_session("profile")
    for i in range(20):
        eng.calibrate(st, frame, t=i * 0.3)

    # warm up both the real analyze and the staged path
    for i in range(warmup):
        eng.analyze(st, frame, t=6.0 + i * 0.1)
        _profile_once(eng, st, frame, 6.0 + i * 0.1, disable_pose)

    per_stage: dict[str, list[float]] = {s: [] for s in _STAGES}
    whole: list[float] = []
    for i in range(n):
        t = 10.0 + i * 0.1
        t0 = time.perf_counter()
        r = eng.analyze(st, frame, t)          # real engine latency (ground truth)
        whole.append((time.perf_counter() - t0) * 1000.0)
        s = _profile_once(eng, st, frame, t, disable_pose)
        for k, v in s.items():
            per_stage[k].append(v)

    summary = {s: {"median": round(statistics.median(per_stage[s]), 3),
                   "p95": round(p95(per_stage[s]), 3)} for s in _STAGES}
    staged_total = sum(statistics.median(per_stage[s]) for s in _STAGES)
    return {
        "sample": sample, "shape": list(frame.shape), "threads_requested": threads,
        "cv2_threads": cv2.getNumThreads(), "cpu_count": os.cpu_count(),
        "pose_disabled": disable_pose,
        "face_present": bool(r.face_present), "persons": int(r.persons),
        "retry_used": None,  # not directly observable here; inferred from bbox size in docs
        "analyze_real": {"median": round(statistics.median(whole), 3), "p95": round(p95(whole), 3)},
        "staged_total_median": round(staged_total, 3),
        "stages": summary,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default="messi5.jpg")
    ap.add_argument("--threads", type=int, default=0, help="cv2.setNumThreads; 0 = leave default")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=10)
    args = ap.parse_args()
    thr = args.threads if args.threads > 0 else cv2.getNumThreads()
    out = run(args.sample, thr, args.n, args.warmup)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
