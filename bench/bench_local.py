#!/usr/bin/env python3
"""Local arm64 baseline bench for the vision analyze hot path. OWNER: cloud tab.

Reproducible per docs/cool/BENCH_PLAN.md. READ-ONLY: imports the V-tab engine and calls
its public API (new_session / analyze); it never modifies the engine. Writes
docs/cool/RESULTS_local.md.

This measures Apple Silicon (NOT Graviton) — a development baseline that proves the
method. Graviton / COOL / x86 rows are deferred (need a deploy or a Marketplace
subscription) and are emitted as placeholders only.

Usage:  nice -n 15 uv run python bench/bench_local.py [--n 100] [--warmup 10] [--repeats 3]
"""
from __future__ import annotations

import argparse
import json
import platform
import resource
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nunchi.vision.engine import VisionEngine, runtime_info  # noqa: E402
from nunchi.vision.io import decode_jpeg  # noqa: E402

FIXED_FRAME = REPO / "tests" / "vision" / "_samples" / "messi5.jpg"
MODELS_DIR = REPO / "models"
OUT = REPO / "docs" / "cool" / "RESULTS_local.md"


def _peak_rss_mb() -> float:
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux reports kilobytes.
    return ru / (1024 * 1024) if sys.platform == "darwin" else ru / 1024


def measure(frame, n: int, warmup: int) -> dict:
    eng = VisionEngine(str(MODELS_DIR))
    st = eng.new_session("bench")
    # Warm-up (model graph load, filter fill, first-call cost) — discarded.
    for i in range(warmup):
        eng.analyze(st, frame, float(i) * 0.1)
    # Measure on the SAME frame; fresh perf_counter each call.
    wall_ms: list[float] = []
    engine_ms: list[float] = []
    t = float(warmup) * 0.1
    for _ in range(n):
        t += 0.1
        t0 = time.perf_counter()
        r = eng.analyze(st, frame, t)
        wall_ms.append((time.perf_counter() - t0) * 1000.0)
        engine_ms.append(float(r.latency_ms))
    return {
        "wall": wall_ms,
        "engine": engine_ms,
        "face_present": bool(r.face_present),
        "persons": int(r.persons),
        "backend": r.backend,
    }


def p95(xs: list[float]) -> float:
    s = sorted(xs)
    k = max(0, int(round(0.95 * (len(s) - 1))))
    return s[k]


def summarize(samples: list[float]) -> dict:
    return {
        "median": statistics.median(samples),
        "p95": p95(samples),
        "min": min(samples),
        "max": max(samples),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()

    if not FIXED_FRAME.exists():
        print(f"ERROR: fixed frame missing: {FIXED_FRAME}", file=sys.stderr)
        return 2
    frame = decode_jpeg(FIXED_FRAME.read_bytes(), max_side=640)
    info = runtime_info()

    # repeats runs; take median-of-medians to damp noise.
    med_wall, med_engine, p95_wall, peaks = [], [], [], []
    last = {}
    for _ in range(args.repeats):
        res = measure(frame, args.n, args.warmup)
        w = summarize(res["wall"])
        e = summarize(res["engine"])
        med_wall.append(w["median"])
        p95_wall.append(w["p95"])
        med_engine.append(e["median"])
        peaks.append(_peak_rss_mb())
        last = {"w": w, "e": e, "res": res}

    median_wall = statistics.median(med_wall)
    median_engine = statistics.median(med_engine)
    p95_of_runs = statistics.median(p95_wall)
    peak_mb = max(peaks)
    thr = 1000.0 / median_wall if median_wall else 0.0

    # Lambda cost proxy (arm64), same basis as cloud/README cost table.
    mem_gb = 1536 / 1024.0
    arm_gb_s = 0.0000133  # us-east-1 arm64 Lambda $/GB-s
    cost_per_frame = mem_gb * (median_wall / 1000.0) * arm_gb_s
    cost_per_million = cost_per_frame * 1_000_000 + 0.20  # + $0.20/M requests

    env = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "machine": platform.machine(),
        "system": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "cv_version": info["cv_version"],
        "backend": info["backend"],
        "arch_baseline": info["arch"],
        "frame": str(FIXED_FRAME.relative_to(REPO)),
        "frame_shape": list(frame.shape),
        "n": args.n,
        "warmup": args.warmup,
        "repeats": args.repeats,
        "face_present": last["res"]["face_present"],
        "persons": last["res"]["persons"],
    }
    results = {
        "median_wall_ms": round(median_wall, 2),
        "p95_wall_ms": round(p95_of_runs, 2),
        "median_engine_ms": round(median_engine, 2),
        "throughput_fps": round(thr, 2),
        "peak_rss_mb": round(peak_mb, 1),
        "cost_per_million_usd": round(cost_per_million, 4),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(env, results), encoding="utf-8")
    print(json.dumps({"env": env, "results": results}, indent=2))
    print(f"\nwrote {OUT.relative_to(REPO)}")
    return 0


def render(env: dict, r: dict) -> str:
    return f"""# Baseline results — local arm64 (C tab)

Generated {env['generated_utc']} by `bench/bench_local.py` (see docs/cool/BENCH_PLAN.md).
**This is Apple Silicon, NOT AWS Graviton** — a development baseline proving the method
and giving an order-of-magnitude, not a Graviton or COOL number.

## Environment

| key | value |
|---|---|
| machine | {env['machine']} (Apple Silicon — **not Graviton**) |
| system | {env['system']} |
| python | {env['python']} |
| OpenCV | {env['cv_version']} (backend `{env['backend']}`) |
| cv2 build baseline | `{env['arch_baseline']}` |
| fixed input | `{env['frame']}` {env['frame_shape']} (1 face: present={env['face_present']}, persons={env['persons']}) |
| protocol | warmup {env['warmup']}, N {env['n']}, repeats {env['repeats']} (median-of-medians) |

## Results — `analyze` hot path

| metric | value |
|---|---|
| median latency (wall) | **{r['median_wall_ms']} ms** |
| p95 latency (wall) | {r['p95_wall_ms']} ms |
| median latency (engine `latency_ms`) | {r['median_engine_ms']} ms |
| throughput | {r['throughput_fps']} fps |
| peak RSS | {r['peak_rss_mb']} MB |
| cost proxy (Lambda arm64, 1536 MB) | ~${r['cost_per_million_usd']} / 1M frames |

## Comparison table (deferred rows not measured here)

| config | arch | build | median ms | fps | status |
|---|---|---|---|---|---|
| local-arm64 | Apple Silicon | pip headless 5.0.0.93 | {r['median_wall_ms']} | {r['throughput_fps']} | **measured (dev baseline, not Graviton)** |
| graviton-pip | Graviton | pip headless 5.0.0.93 | — | — | deferred — needs deploy (C3/U6) |
| graviton-cool | Graviton | COOL AMI | — | — | deferred — needs U2 subscription; AMI-only |
| x86-pip | x86_64 | pip headless 5.0.0.93 | — | — | deferred — optional cross-arch point |

A COOL delta would slot into `graviton-cool` vs `graviton-pip`; AWS's published COOL
gain is 20–70% (avg ~1.5x). We do **not** claim that number as ours — it is cited, and
our own COOL row stays empty until actually run on a Graviton EC2 from the COOL AMI.
"""


if __name__ == "__main__":
    raise SystemExit(main())
