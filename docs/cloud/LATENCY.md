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
