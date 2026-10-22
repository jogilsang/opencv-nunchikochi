# Latency & cost — measured on AWS Graviton (C8)

Real measurements of the deployed `nunchi-service` Lambda (arm64 / **AWS Graviton**),
not the local dev baseline. Date 2026-10-22.

| condition | value |
|---|---|
| region | us-east-1 |
| architecture | arm64 (Graviton) — `/healthz` reports `arch: aarch64` |
| runtime | Python 3.12, OpenCV 5.0.0 (real engine, `stubs:false`) |
| default memory | 1536 MB |
| input | 320×240 JPEG with one face (~13 KB) |
| rate | 1 frame / 0.4 s (2.5/s, well under the 6/s app limit and the 50k/5min alarm) |
| key handling | read from SSM into process memory only; never printed or written |

> **This is AWS Graviton, a different environment from the local Apple-Silicon baseline.**
> The local warm `analyze` figure was **12.69 ms** (`docs/cool/RESULTS_local.md`, Apple M-series,
> native, no network). The Graviton numbers below are higher — that is the honest
> cross-environment difference (Graviton core vs Apple Silicon, Lambda runtime), not a
> regression. Do not compare the two as if same-hardware.

## 1. Warm frame-analyze latency (server-side engine `latency_ms`)

100 frames, one session, first 5 as warmup (excluded from steady stats).

| metric | server `latency_ms` (engine, Graviton) | client RTT (KR → us-east-1 via API Gateway) |
|---|---|---|
| median | **148.2 ms** | 1030 ms |
| p95 | 157.4 ms | 1076 ms |
| p99 | 161.7 ms | 1108 ms |
| min / max | 135.0 / 165.6 ms | 973 / 1477 ms |
| warmup (n=5) median | 146.1 ms | — |

- Server `latency_ms` is the engine's own wall time for detection + landmark + metrics; it
  is stable from the first frame (models load at init, not per frame).
- Client RTT is network-dominated (Korea ↔ us-east-1 + TLS + API Gateway), **not** compute —
  reported for completeness, not as the engine figure.

## 2. Cold start (forced new execution environment, n=5)

Forced by updating the function env var then invoking; sequential; config restored after.

| metric | Init Duration (model load + import) |
|---|---|
| median | **2489 ms** |
| p95 | 2968 ms |
| min / max | 1956 / 2968 ms |
| raw (ms) | 1956, 1973, 2489, 2559, 2968 |

- The ONNX models (YuNet + FaceMesh + palm ≈ 9 MB) load once during Init; the **first
  frame's analyze time is the same ~148 ms** as warm (analyze cost is per-frame and does
  not include model load), so a cold request's total ≈ Init (~2.5 s) + ~0.15 s analyze.

## 3. Memory vs latency vs cost (warm, 30 frames each)

| memory | median analyze | GB-ms per frame | relative $ | note |
|---|---|---|---|---|
| 1024 MB | 217.5 ms | 1.0 × 217.5 = ~222,700 MB-ms | baseline | slower (less vCPU) |
| **1536 MB (deployed)** | **148.2 ms** | 1.5 × 148.2 = ~227,600 MB-ms | ~+2% | **~32% faster for ~2% more cost** |

Billed GB-ms per frame is nearly identical, so **1536 MB is the better pick** (large speedup
for negligible cost delta). (A step up to 2048 MB was not measured to keep within the rate
budget; the 1024↔1536 curve already shows the near-flat cost / rising speed trade.)

### Cost basis (official AWS Lambda pricing)

- arm64 (Graviton) duration: **~$0.0000133/GB-s** (≈ 20% below x86 $0.0000166667/GB-s, first
  tier) + **$0.20 / 1M requests**. Docs: <https://aws.amazon.com/lambda/pricing/> ,
  arm64 regions: <https://docs.aws.amazon.com/lambda/latest/dg/foundation-arch.html>
- Per frame @ 1536 MB, 148 ms: 1.5 GB × 0.148 s × $0.0000133 ≈ **$0.00000295** + request.
  50k frames/month ≈ **$0.15** compute + ~$0.01 requests → consistent with the ~$1–2/month
  stack estimate in `cloud/README.md`.

## 4. Frames never persisted (re-verified after this measurement)

- `dynamodb scan nunchi-sessions` (11 items incl. the measurement session): state-schema keys
  only — **no `jpeg`/`image`/`base64`/`/9j/` tokens**.
- CloudWatch Lambda logs (last 30 min, ~140 KB): **no image/base64 tokens**.

## Notes

- Measurement scripts were ephemeral (`/tmp`), not committed. The API key was never printed
  or written; it was read from SSM into process memory for the `X-Api-Key` header only.
- Rate kept ≤ 2.5/s so the `nunchi-api-request-spike` alarm (50k/5min) and the reserved
  concurrency (5) were never approached. Memory and env changes were reverted to the
  deployed baseline (1536 MB, original env) and verified.

---

## C10 — pose (posture buddy) impact, re-measured 2026-10-22

After the V10 redeploy (head pose `overlay.pose` + session-state schema 3.0), warm
server-side `result.latency_ms` was re-measured against the live API Gateway endpoint
(real face sample `messi5.jpg`, 5 warm-up + 30 measured run frames, same 1536 MB baseline).

| run | n | median | p95 | p99 | min | max |
|---|---|---|---|---|---|---|
| C10 run 1 | 30 | 280.6 ms | 288.6 ms | 361.9 ms | 272.4 | 361.9 |
| C10 run 2 | 30 | 281.6 ms | 288.8 ms | 290.2 ms | 272.4 | 290.2 |

### Pose impact (vs the C8 baseline above)

| version | warm median | warm p95 |
|---|---|---|
| C8 (pre-pose) | 148.2 ms | 157.4 ms |
| C10 (with pose) | ~281 ms | ~289 ms |

- Pose adds **~133 ms / frame (~1.9×)**: the posture buddy derives head yaw/pitch/roll +
  depth from the 478-point face mesh and smooths them (EMA + median), on top of the prior
  EAR/MAR work. Still comfortably within the 2 fps live budget (≈ 500 ms/frame) and the
  15 s Lambda timeout; cold start is unchanged (dominated by import/model load, not pose).

> **정정 (C11, 2026-10-22): 위 "pose가 +133ms / 2× 원인"은 사실이 아니다.** V11 로컬 A/B에서
> pose 델타는 +0.43ms, C11 Lambda A/B(아래)에서 `NUNCHI_DISABLE_POSE` on/off 차이는 **+1.6ms**
> 뿐이었다. C8(148ms)↔C10(281ms) 2배는 pose가 아니라 **실행 호스트(Graviton CPU 세대/이웃
> 경합) 변동**이다(같은 코드가 같은 날 같은 입력으로 178~299ms 범위). 자세한 근거는 아래 C11 절.
- Cost delta per frame @ 1536 MB, 281 ms: 1.5 GB × 0.281 s × $0.0000133 ≈ **$0.0000056**
  (≈ 1.9× the pre-pose per-frame compute); 50k frames/month ≈ **$0.28** compute — still
  inside the ~$1–2/month stack estimate.
- `overlay.pose` is numeric only (`{yaw_deg,pitch_deg,roll_deg,depth,conf}`) and present in
  the frame **response**; it is NOT in DynamoDB (`overlay`/`yaw_deg` keys absent — the
  persisted state holds only calibration/smoothing angles per CONTRACTS §4) nor in the trace
  (JSONL scanned: no `overlay`/`yaw_deg`/`image`/`base64`/`landmark`/`points`). No images or
  raw landmark points anywhere.

---

## C11 — latency 2× A/B on Lambda (root cause), 2026-10-22

V11 (`docs/eval/LATENCY_REGRESSION.md`) exonerated pose locally (+0.43 ms) and asked the
cloud tab to A/B the 2× (C8 148 ms → C10 281 ms) on real Lambda. Redeployed V11 (adds the
`NUNCHI_DISABLE_POSE` runtime switch; hot path otherwise unchanged), then measured warm
server-side `result.latency_ms` (30 run frames after 5 warm-up, sample `messi5.jpg`, same
API endpoint). Runtime Version `python:3.12.mainlinev2.v43`, Max Memory ~290 MB.

### A — same conditions, repeated 3× (variance check), ~3 min apart, baseline 1536 MB

| run | n | median | p95 | p99 | pose frames |
|---|---|---|---|---|---|
| baseline r1 | 30 | 177.4 ms | 185.3 | 185.8 | 30/30 |
| baseline r2 | 30 | 177.6 ms | 184.2 | 184.3 | 30/30 |
| baseline r3 | 30 | 178.6 ms | 188.3 | 202.6 | 30/30 |

→ **Within one warm host, extremely stable ~178 ms.** Neither C8's 148 ms nor C10's 281 ms
reproduced today — today's host sits in between.

### B — pose A/B (`NUNCHI_DISABLE_POSE`), each change lands on a fresh host

| config | n | median | p95 | pose frames |
|---|---|---|---|---|
| pose OFF (`=1`) | 30 | 282.0 ms | 292.7 | 0/30 (switch verified) |
| pose ON (cleared) | 30 | 283.6 ms | 301.5 | 30/30 |

→ **pose delta = +1.6 ms** on Lambda. Confirms V11: **pose is NOT the cause** (and the switch
works — 0/30 pose frames when disabled, response schema unchanged). Note both runs are ~282 ms,
not ~178 ms: the config update spawned a new, slower execution host.

### C — thread A/B (`OMP_NUM_THREADS` + `OPENCV_FOR_THREADS_NUM`), fresh host each

| config | n | median | p95 |
|---|---|---|---|
| threads = 1 | 30 | 296.8 ms | 309.8 |
| threads = 2 | 30 | 299.0 ms | 311.6 |

→ Forcing threads to 1 did **not** reduce latency (296.8 vs 299.0, both ≥ the no-thread-var
runs). **Thread over-subscription is NOT the cause** either; no engine thread-cap change is
warranted. (The service sets no OpenCV threads in code — confirmed by read-only grep.)

### D — memory A/B (optional): 1769 MB = exactly 1 full vCPU per AWS docs

| memory | n | median | p95 | note |
|---|---|---|---|---|
| 1769 MB (1 vCPU) | 30 | 247.1 ms | 256.9 | ~34 ms faster than 1536 on same era host |
| 1536 MB (recheck) | 30 | 281.2 ms | 297.5 | back on a hot host |

→ More vCPU helps modestly (CPU-bound vision), but cannot explain a 2× swing, and the 1536
recheck (281 ms) is far from the early 178 ms on identical config — again **host-dependent**.
AWS: full vCPU at ~1769 MB (<https://docs.aws.amazon.com/lambda/latest/dg/configuration-memory.html>).

### Conclusion

- **Cause of the 148↔281 "2×": execution-environment (host) variance, not code.** The same
  code, same input, same day produced 178 / 247 / 282 / 297 ms purely by landing on different
  Graviton execution hosts (CPU generation / neighbour contention / warm-vs-fresh). Every
  config change forces a new host, which is why B/C/D runs cluster at ~282–299 ms while the
  untouched warm host (A) held ~178 ms.
- **pose: innocent** (Lambda +1.6 ms, local +0.43 ms). **threads: innocent** (1 vs 2 flat).
  **memory: minor lever** (~34 ms per vCPU step, not a 2× factor).
- **Representative value to quote (proposal; conductor confirms):** warm server-side analyze
  **≈ 178–282 ms depending on host; 3× same-host median ~178 ms** at the 1536 MB baseline.
  Avoid a single "148 ms" or "281 ms" headline — state the host-variance range.

### Cost (re-stated, host-independent)

- arm64 $0.0000133/GB-s + $0.20/1M req. At 1536 MB: 178 ms ≈ $0.00000355/frame, 282 ms ≈
  $0.00000562/frame; 50k frames/month ≈ $0.18–0.28 compute → still within the ~$1–2/month
  stack estimate (`cloud/README.md`). 1769 MB trades ~15% more $/s for ~1 vCPU (not adopted;
  baseline restored to 1536 MB).

### Uncertainty / honesty

- I could not pin the host identity to a number (Lambda doesn't expose CPU model to the
  function); the host-variance conclusion rests on the pattern: config-change → new host →
  different stable latency, with pose/threads flat across the change.
- All env vars and memory were **restored to the deployed baseline** (1536 MB; 5 original env
  vars, no thread/pose vars) and verified equal to the pre-C11 snapshot; reserved concurrency
  (5) and the cost alarm were untouched. `/healthz` 200, no-key 401 after restore.
