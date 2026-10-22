# Baseline results — local arm64 (C tab)

Generated 2026-10-22 01:26 UTC by `bench/bench_local.py` (see docs/cool/BENCH_PLAN.md).
**This is Apple Silicon, NOT AWS Graviton** — a development baseline proving the method
and giving an order-of-magnitude, not a Graviton or COOL number.

## Environment

| key | value |
|---|---|
| machine | arm64 (Apple Silicon — **not Graviton**) |
| system | Darwin 25.2.0 |
| python | 3.12.13 |
| OpenCV | 5.0.0 (backend `opencv`) |
| cv2 build baseline | `NEON FP16 NEON_DOTPROD NEON_FP16` |
| fixed input | `tests/vision/_samples/messi5.jpg` [342, 548, 3] (1 face: present=True, persons=1) |
| protocol | warmup 10, N 100, repeats 3 (median-of-medians) |

## Results — `analyze` hot path

| metric | value |
|---|---|
| median latency (wall) | **12.69 ms** |
| p95 latency (wall) | 13.69 ms |
| median latency (engine `latency_ms`) | 12.68 ms |
| throughput | 78.82 fps |
| peak RSS | 97.4 MB |
| cost proxy (Lambda arm64, 1536 MB) | ~$0.4531 / 1M frames |

## Comparison table (deferred rows not measured here)

| config | arch | build | median ms | fps | status |
|---|---|---|---|---|---|
| local-arm64 | Apple Silicon | pip headless 5.0.0.93 | 12.69 | 78.82 | **measured (dev baseline, not Graviton)** |
| graviton-pip | Graviton | pip headless 5.0.0.93 | — | — | deferred — needs deploy (C3/U6) |
| graviton-cool | Graviton | COOL AMI | — | — | deferred — needs U2 subscription; AMI-only |
| x86-pip | x86_64 | pip headless 5.0.0.93 | — | — | deferred — optional cross-arch point |

A COOL delta would slot into `graviton-cool` vs `graviton-pip`; AWS's published COOL
gain is 20–70% (avg ~1.5x). We do **not** claim that number as ours — it is cited, and
our own COOL row stays empty until actually run on a Graviton EC2 from the COOL AMI.
