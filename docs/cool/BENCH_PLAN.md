# Baseline benchmark plan (C tab)

Reproducible measurement of the vision `analyze` hot path, so a COOL-vs-baseline or
x86-vs-arm64 comparison is apples-to-apples. **Read-only**: the bench imports the V-tab
engine and calls its public API; it does not modify the engine.

## What we measure

The core CV workload = `VisionEngine.analyze(state, frame_bgr, t)` (JPEG decode happens
once up front via `nunchi.vision.io.decode_jpeg`, not inside the timed loop, so we time
detection + landmark + metric estimation — the Graviton-bound part COOL accelerates).

Metrics per run:
- **analyze latency**: median and **p95** in ms, from `FrameResult.latency_ms` (the engine's
  own wall-time field) AND an independent `time.perf_counter()` around the call (report both).
- **throughput**: frames/s = 1000 / median_ms.
- **memory**: RSS high-water mark via `resource.getrusage` (MB).
- **cost proxy**: Lambda billed GB-s per frame = memory_GB × median_s; then $/1M frames at
  the arm64 Lambda rate (same basis as cloud/README cost table). This lets a % speedup map
  straight to a % cost cut.

## Fixed inputs (reproducibility)

- Input frame: **`tests/vision/_samples/messi5.jpg`** (548×342, one clear face) — committed,
  deterministic. `decode_jpeg(..., max_side=640)` gives the same ndarray every run.
- Same `models/` ONNX (YuNet + FaceMesh), same `FilterConfig` defaults, same `t` schedule.
- One `SessionState` per config; warm the session (calibration frames) before timing.

## Protocol

1. Decode the fixed JPEG once → `frame_bgr`.
2. **Warm-up**: 10 `analyze` calls (discarded) — loads ONNX graphs, fills filters, pays
   first-call cost so we measure steady state.
3. **Measure**: N = 100 timed `analyze` calls on the same frame, fresh perf_counter each.
4. Record median, p95, min, max, throughput, peak RSS, and `runtime_info()` evidence
   (`cv_version`, `backend` = opencv|cool, `arch` baseline string).
5. Repeat the whole thing 3 times; report the median-of-medians to damp noise.
6. No other heavy process; run under `nice -n 15`.

## Configurations

| id | where | build | arch | notes |
|---|---|---|---|---|
| `local-arm64` | this Mac (Apple Silicon) | pip opencv-python-headless 5.0.0.93 | **arm64 (Apple, NOT Graviton)** | the one we run now |
| `graviton-pip` | Lambda/EC2 Graviton | pip headless 5.0.0.93 | arm64 Graviton | **deferred** — needs deploy (C3/U6) |
| `graviton-cool` | EC2 from COOL AMI | COOL | arm64 Graviton | **deferred** — needs U2 subscription |
| `x86-pip` | x86 box | pip headless 5.0.0.93 | x86_64 | optional honest cross-arch point |

**Honesty rule:** Apple Silicon ≠ Graviton. `local-arm64` is a *development* baseline that
proves the method and gives an order-of-magnitude, NOT a Graviton number. Any Graviton /
COOL / x86 row is marked "deferred (not measured here)" until actually run. We never
present the Mac figure as a Graviton or COOL result.

## Output

`bench/bench_local.py` runs `local-arm64` now and writes `docs/cool/RESULTS_local.md`
(a table + the runtime_info evidence + the environment). The deferred rows get a
placeholder line each so the comparison table's shape is ready for C3/U2.
