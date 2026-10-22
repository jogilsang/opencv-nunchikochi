# Deploy log — nunchi (captain / us-east-1)

First real deploy of the `nunchi` stack. Approved 2026-10-22 (captain, us-east-1, stack
`nunchi`, prefix `nunchi-`, tags project=nunchikochi + delete-after=2026-11-30, public
endpoints kept until 11/10, $20 budget). Account id is masked everywhere (`***NNNN`).

## Pre-flight

- `sts get-caller-identity`: profile=captain, user/captain (account masked). OK.
- Stack `nunchi`: did not exist (clean first deploy).
- `deploy.sh --dry-run`: resources + tags matched the approved scope — stack `nunchi`,
  prefix `nunchi`, code bucket `nunchi-code-***NNNN`, SSM key `/nunchi/api-key`,
  tags `project=nunchikochi delete-after=2026-11-30`. No out-of-scope resource.

## Steps

1. `deploy.sh --apply` (attempt 1): package zip (unzipped 135 MB, zip 52 MB) → create code
   bucket `nunchi-code-***NNNN` → upload zip → put SSM SecureString `/nunchi/api-key`
   (value never printed) → `cloudformation deploy`. **Stack create FAILED → ROLLBACK_COMPLETE.**
2. Root cause from `describe-stack-events`: **`Budget` (AWS::Budgets::Budget) AccessDenied** —
   "Account is a linked account. Access to AWS Budgets is managed at the payer account
   level." Everything else was just "creation cancelled" by the rollback.
3. Fix (owned path `cloud/template.yaml`): added parameter `EnableBudget` (default `false`)
   + condition; the Budget resource is now `Condition: EnableBudgetCond`. On a member
   account the budget is skipped (payer owner sets the $20 budget out-of-band); on a payer
   account deploy with `EnableBudget=true`. cfn-lint 0. Deleted the rolled-back stack.
4. `deploy.sh --apply` (attempt 2): **CREATE_COMPLETE.** Web static uploaded, `web/config.json`
   written with apiBase only (no key).
5. Smoke (public Function URL): `GET /healthz` → **403 AccessDeniedException**, request never
   reached the Lambda. Verified it is NOT the resource policy (canonical CLI `add-permission`
   with Principal `*` + FunctionUrlAuthType NONE still 403; removed the diagnostic statement).
   `captain` cannot list SCPs (AccessDenied). **Conclusion: org SCP blocks public Lambda
   Function URLs.** Web (CloudFront→S3) is public and 200. Out of approved scope to change →
   stopped on the public path and continued server-side verification via IAM-signed invoke.
6. Second deploy-surfaced bug (owned path): session create 500 →
   `TypeError: Float types are not supported. Use Decimal`. `DynamoStateStore` sent Python
   floats (timestamps, metric values) straight to DynamoDB. **Fix:** float↔Decimal round-trip
   on the store boundary (`_floats_to_decimal` / `_decimals_to_native`) + regression test
   (`test_dynamo_float_state_roundtrip_moto`). Repackaged, `update-function-code`, waited.

## Smoke results (server-side via IAM-signed invoke; public URL org-blocked)

| check | result |
|---|---|
| `/healthz` | 200 — OpenCV **5.0.0**, backend `opencv`, arch **aarch64** (Graviton), `stubs:false` (models loaded) |
| create session | 200 (DynamoDB-backed, after Decimal fix) |
| frame (real face JPEG) | 200 — `face_present:true`, agent decided, real engine ran on AWS |
| end session | 200 — report returned |
| summary by date | 404 — known demo limitation: `by_date`/`summaries` are in-process buffers, not persisted across Lambda instances (app.py notes this; only session STATE + DynamoDB are cross-instance) |
| trace | 200 — 1 line, full tool_calls, no bytes |
| bad key | 401 `unauthorized` |
| oversize frame (>200 KB) | 413 `payload_too_large` |
| rate limit (429) | verified in test suite (`test_rate_limit_returns_429`); NOT reproducible via sequential cold IAM invokes (each round-trip > the 1 s window, so 8 frames stayed under 6/1 s) |
| public Function URL | **403 org SCP** (see ENDPOINT.md) — web (CloudFront) is 200 |

## Latency (CloudWatch REPORT, server-side)

| metric | value |
|---|---|
| cold start Init Duration | median ~2042 ms, p95 ~2115 ms (model load + import; n=2 cold) |
| warm Billed Duration | median ~10 ms (healthz); p95 ~1972 ms skewed by the cold-invoke frames doing real analysis |

(Client-observed end-to-end was ~900 ms median, dominated by the AWS API round-trip, not
Lambda compute — the REPORT billed durations above are the real figures.)

## Frames never persisted (privacy, verified on AWS)

- `dynamodb scan nunchi-sessions`: only state-schema keys (counts, vision filters, agent_ctx,
  frame_ts, timestamps). **No `jpeg`/`image`/`base64`/`/9j/` tokens.**
- CloudWatch Logs (last 20 min): **no frame bytes / base64 image tokens**; EMF metrics flowing
  (18 Decisions + 18 FrameLatencyMs records → observability working).

## 3 named CloudFormation resources note

The stack creates one named IAM role (`nunchi-service-role`, the Lambda execution role in
the template) under `CAPABILITY_NAMED_IAM`. This is the service's own least-privilege role
(logs + its DynamoDB table + its one SSM param), in-scope — not an account/org IAM change.

## Palm model (V7, for `drink` detection) — verified in the deployed zip

Conductor relay (V7): a hand/palm model `palm_detection_mediapipe` (required:false, onnx
gitignored) was added; it must ship in the Lambda zip for `drink` detection.
- `models/MANIFEST.json` already lists it; `download_models.py --check` → 3/3 ok (incl. palm).
- `cloud/package.sh` ships **all** `*.onnx` (glob), so palm is included with no script change.
- The zip already deployed (with the Decimal fix) contains
  `models/palm_detection_mediapipe_2023feb.onnx` (3.9 MB); unzipped 139 MB (was 135), under
  the 250 MB limit. Deployed Lambda `CodeSize` == local zip bytes → **palm is live; no extra
  redeploy needed.**

## C3b — public Function URL (org-SCP-blocked) → API Gateway HTTP API

Conductor decision: keep same stack/region/prefix/tags, change only the public entry point.

7. Template change (owned `cloud/template.yaml`): removed the public `AWS::Lambda::Url` +
   its `*` permission; added `AWS::ApiGatewayV2::{Api,Integration,Route,Stage}` `nunchi-api`
   (HTTP, payload 2.0, `$default` → Lambda AWS_PROXY), a scoped `AWS::Lambda::Permission`
   (principal apigateway.amazonaws.com, SourceArn = this API's execute-api ARN only),
   an access-log group (14 days, minimal fields), and default throttle rate 20 / burst 40.
   CORS = CloudFront domain + localhost:8099. `ApiBase` output now the API Gateway URL.
8. Budget substitution: AWS Budgets is payer-only on this member account. Added an
   `AWS::SNS::Topic` (`nunchi-alerts`, conditional on an email param) + an
   `AWS::CloudWatch::Alarm` `nunchi-api-request-spike` on API Gateway `Count` (Sum>50000/5min)
   as the cost proxy (request volume drives cost here). The AWS Budgets resource stays but is
   default-off (`EnableBudget=false`), for a payer-account deploy.
9. Deploy attempt 1 FAILED → UPDATE_ROLLBACK_COMPLETE: `HttpApiStage` access-log Format must
   include `$context.requestId`. Fixed (added `rid`, still no body/headers). cfn-lint 0.
10. Deploy attempt 2: UPDATE_COMPLETE. `web/config.json` rewritten with the API Gateway
    apiBase (no key).

### C3b smoke (PUBLIC, over the internet via API Gateway)

| check | result |
|---|---|
| `GET /healthz` anonymous (no key) | **200** — OpenCV 5.0.0, aarch64 Graviton, stubs:false (real engine) |
| create session (X-Api-Key) | 200 |
| frame (real face JPEG) | 200 — face_present:true |
| end + trace | 200 / 200 (1 line, no bytes) |
| bad key | 401 `unauthorized` |
| oversize >200 KB | 413 `payload_too_large` |
| rate limit | 429 verified in test suite; live sequential curl can't trip the 1 s window (round-trip > window); a parallel burst hits the reserved-concurrency=5 ceiling first → 503 (also a valid abuse/cost guard) |

### C3b latency

| metric | value |
|---|---|
| public client end-to-end (`/healthz` ×10, from KR → us-east-1) | median ~654 ms, p95 ~689 ms (TLS + API Gateway + Lambda + network) |
| server-side Billed Duration (CloudWatch) | median ~44 ms (p95 skewed by cold starts + real-frame analysis) |

### C3b privacy (re-verified after public traffic)

- `dynamodb scan nunchi-sessions`: 8 items, state-schema only, **no jpeg/base64/image tokens**.
- API Gateway access logs (`/aws/apigw/nunchi-api`): rid/time/ip/method/path/status/len/latency
  only — **no body, no headers, no X-Api-Key**. requestId present (valid format).

## C10 — posture-buddy (V10) redeploy, 2026-10-22

Same stack `nunchi` (captain / us-east-1), no new resource kinds. Updated the Lambda code
(V10 vision: `overlay.pose` + session-state schema 3.0) and the web static (incl. vendored
three.js posture buddy).

### Steps

- Repackaged the zip (`cloud/package.sh`): **139 MB unzipped** (< 250 MB limit), 54 MB zip;
  3 ONNX models verified (`download_models.py --check`: yunet, face_landmarks, palm — all ok).
- `deploy.sh --apply`: zip uploaded; `cloudformation deploy` reported "No changes" (template
  unchanged), so the Lambda code was updated explicitly with `lambda update-function-code`
  (CodeSize 57,126,403 → 57,131,166). Web static synced + `config.json` (apiBase only, no key)
  uploaded; CloudFront `/*` invalidated.

### Smoke (live, key from SSM → process memory only; never printed)

| check | result |
|---|---|
| `GET /healthz` | 200 `{ok,cv_version:5.0.0,backend:opencv,arch:aarch64,build:dev,stubs:false}` |
| no key → `POST /v1/sessions` | 401 `unauthorized` |
| session create (keyed) | 200 |
| face frame (`messi5.jpg`) | 200; **`overlay.pose` numeric** `{yaw_deg,pitch_deg,roll_deg,depth,conf}` (floats) |
| oversize > 200 KB | 413 `payload_too_large` |
| old-schema (2.x) session reuse | 410 `session_state_invalid` (bilingual); a fresh session still works (200) |

### Web (CloudFront, `curl -I`)

- `/?demo=1` 200, `/index.html` 200, `/config.json` 200 `application/json` (apiBase only),
  `/vendor/three.module.min.js` 200 `text/javascript` 652 KB, `/vendor/three.LICENSE` 200,
  `/app.js` 200, `/buddy.js` 200.
- Playwright fake-camera live check (`web/e2e/live.mjs` against the live API): the
  connection-status line shows **arm64 · OpenCV 5.0.0** (pass), start-gate/key-in-memory/
  no-page-errors pass. The full calibrate→run→report flow fails under a *fake* camera
  (synthetic media has no real face → no calibration completes); the real-face server-side
  round-trip above already proves the pipeline. Not a deploy defect; noted honestly.

### Privacy (re-verified)

- DynamoDB item (`pk=SESSION#…`, `sk=STATE`): state-schema only — **no `overlay`/`yaw_deg`/
  `image`/`base64`/`jpeg`/`landmark`/`points`**. The `calibrator.pose_*` / `filters.pose_*`
  numeric angles are the calibration + smoothing state (CONTRACTS §4 "보정·상태"), not raw
  landmarks or pixels.
- Trace JSONL: no `overlay`/`image`/`base64`/`landmark`/`pose` tokens.

### Latency

- Warm server-side `latency_ms`: **median ~281 ms, p95 ~289 ms** (2 × 30 frames) — pose adds
  ~133 ms (~1.9×) over the C8 pre-pose baseline (148 ms). Within the 2 fps budget. Detail +
  cost delta in `docs/cloud/LATENCY.md`.
- Cost alarm (`nunchi-api-request-spike`) and reserved concurrency (5) untouched.

## C11 — latency 2× A/B + V11 switch, 2026-10-22

Same stack `nunchi` (captain / us-east-1). Redeployed V11 (adds `NUNCHI_DISABLE_POSE`
runtime switch; web untouched) via `package.sh` + `lambda update-function-code`
(CodeSize 57,131,468). `/healthz` 200 (arm64 · OpenCV 5.0.0), no-key 401 after deploy.

A/B of the C8→C10 2× (details + tables in `docs/cloud/LATENCY.md` C11):

| test | result |
|---|---|
| 3× repeat (baseline, same host) | 177.4 / 177.6 / 178.6 ms median — stable, neither 148 nor 281 reproduced |
| pose off vs on (`NUNCHI_DISABLE_POSE`) | 282.0 vs 283.6 ms → **+1.6 ms** (pose innocent; switch verified 0/30 pose frames when off) |
| threads 1 vs 2 (`OMP_NUM_THREADS`,`OPENCV_FOR_THREADS_NUM`) | 296.8 vs 299.0 ms → flat (thread over-subscription NOT the cause) |
| memory 1769 (1 vCPU) vs 1536 | 247.1 vs 281.2 ms → minor vCPU lever, not a 2× factor |

**Conclusion: execution-host (Graviton) variance, not code.** Same code/input/day gave
178–299 ms by landing on different hosts; every config change forces a fresh host. pose and
threads are flat across the change. Corrected the earlier C10 "pose +133 ms" claim in
`LATENCY.md` (kept the text, added a 정정 note).

**Cleanup verified:** all env vars + memory restored to the pre-C11 baseline (1536 MB; 5
original env vars, no thread/pose vars) and confirmed equal via `get-function-configuration`;
reserved concurrency (5) and cost alarm untouched; `/healthz` 200, no-key 401 post-restore.
