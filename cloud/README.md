# cloud — nunchikochi service + infrastructure (C tab)

FastAPI service implementing the HTTP API (docs/CONTRACTS.md §3). Runs locally with
uvicorn and ships to AWS as a **Lambda arm64 zip** (Mangum over FastAPI) behind an
**API Gateway HTTP API**, with the web static site on S3 + CloudFront. vision/agent are pulled in
by dependency injection; when absent the service serves deterministic stubs so other
tabs can integrate (`/healthz` reports `"stubs": true`).

- C1: service skeleton, session-state store, no-persist proof, tests.
- C2 (this): CloudFormation stack + one-command deploy/destroy + arm64 zip packaging.
  **Author + static validation only — no real resources are created here** (that is C3).

## Deploy / destroy (one command each)

Scripts default to **dry-run** (print every mutating command, run nothing). Add
`--apply` to actually execute — reserved for C3.

```bash
# preview everything (safe; only read-only sts is called)
cloud/deploy.sh  --dry-run
cloud/destroy.sh --dry-run

# C3 only — real deploy / teardown
cloud/deploy.sh  --apply --profile captain --region us-east-1 --stack nunchi
cloud/destroy.sh --apply --profile captain --region us-east-1 --stack nunchi
```

`deploy.sh` runs: package zip → upload to a code bucket → ensure the SSM SecureString
api key exists → `cloudformation deploy` (change-set based create/update) → upload
`web/` static → write `web/config.json` with `apiBase` from the stack output. The
**X-Api-Key is never written to a file** — it lives in SSM; set it in the client config
manually. `destroy.sh` empties the web bucket, deletes the stack (everything else goes
with it), then removes the out-of-stack code bucket. The api-key parameter is kept
unless `--purge-key` is passed.

Everything carries the required tags `project=nunchikochi` and
`delete-after=2026-11-30` (RULES). The account id is masked (`***NNNN`) in all script
output.

## Packaging — arm64 zip (strategy a)

See `docs/ARCHITECTURE.md` "Lambda 패키징". `cloud/package.sh` installs arm64 manylinux
wheels (`--python-platform aarch64-manylinux2014 --only-binary=:all:`), adds the service
package + ONNX models, strips tests/pyc/dist-info, and zips. **No docker needed.**

- Measured size: deps unzipped **140 MB** (→ **130 MB** after stripping) + models ~5 MB
  + app code ≈ **~135 MB**, well under the Lambda **250 MB unzipped** limit.
- `boto3` is excluded (the Lambda runtime provides it). `numpy` is a range `>=1.26,<3`
  resolving to 2.2.6 — 2.5.x has no aarch64 manylinux wheel so a hard pin fails.
- `package.sh` aborts with a clear error if unzipped > 250 MB (then switch to a
  container, strategy b — only needed if COOL/C4 is container-only).

```bash
cloud/package.sh cloud/build/nunchi-service.zip   # prints unzipped + zip MB
```

## Stack (single CloudFormation template, `cloud/template.yaml`)

| resource | notes |
|---|---|
| S3 web bucket (private) + CloudFront + **OAC** | static site; bucket blocks all public access, only CloudFront reads it |
| Lambda `nunchi-service` (arm64, python3.12) | `Code` from S3 zip; 1536 MB / 15 s timeout; **ReservedConcurrency 5** (cost + abuse ceiling) |
| **API Gateway HTTP API** `nunchi-api` (public entry) | `$default` route → Lambda AWS_PROXY (payload 2.0); throttle rate 20 / burst 40; CORS = CloudFront domain + localhost; app-level `X-Api-Key` is the real auth. (Replaced the public Lambda Function URL, which an org SCP blocks on this member account — see docs/cloud/DEPLOY_LOG.md.) |
| DynamoDB `nunchi-sessions` | on-demand (PAY_PER_REQUEST), **TTL** on session expiry |
| CloudWatch log group | **14-day** retention (Lambda + API Gateway access logs, minimal fields) |
| SSM SecureString `/nunchi/api-key` | api key read at runtime; **never** in template/logs/config.json |
| Cost guard | AWS Budgets `$20` is payer-only → default off (`EnableBudget`); on a member account a **CloudWatch alarm** `nunchi-api-request-spike` (API Gateway request Sum) + optional SNS email is the proxy |

Parameters let you tune memory (1024–3008), timeout (3–29 s), and reserved concurrency
without editing the template. All tunables carry a `Description` with the rationale.

**AWS references** (limits that shaped the design):
- API Gateway HTTP API (public entry, payload 2.0): <https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api.html>
- Lambda Function URLs & AuthType (why the SCP blocked the original public URL): <https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html>
- Lambda deployment package / 250 MB unzipped limit: <https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html>
- CloudFront Origin Access Control (OAC): <https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html>

## Operations — observability, abuse defense, cold start

**Observability (EMF, no PutMetricData, no extra IAM).** The service prints CloudWatch
[Embedded Metric Format](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html)
records (`src/nunchi/service/metrics.py`, namespace `nunchikochi`):

| metric | dimension | meaning |
|---|---|---|
| `FrameLatencyMs` | — | vision wall time per frame (p50/p95 on the dashboard) |
| `Decisions` | `Decision` | count by agent action (nudge/suppress/…) |
| `Errors` | `ErrorCode` | count by stable error code |
| `RateLimited` | — | server-side frame-rate throttle hits |
| `Sessions` | `Event` (create\|end) | session lifecycle |

Metrics carry **numbers + bounded labels only** — never image bytes, response bodies,
API keys, headers, or session ids (privacy invariant, enforced by a test). Set
`NUNCHI_METRICS=0` to silence them. The template defines a dashboard `nunchi-service`
(latency, decisions/sessions, errors+rate-limit, Lambda throttles/errors) and three
alarms: `nunchi-throttles` (Lambda hits the concurrency ceiling), `nunchi-fn-errors`
(invocation errors), `nunchi-app-errors` (EMF error-code flood).

**Abuse defense (defense in depth):**
- **Reserved concurrency = 5** (template param) — a hard ceiling; excess invocations are
  throttled, not scaled, capping both cost and blast radius.
- **API key** via `X-Api-Key`; the value is read at runtime from the SSM SecureString
  `/nunchi/api-key` (never in the template/logs/config.json). If the param is set but
  can't be resolved, the service **fails closed** (503 `auth_unavailable`), never open.
- **Request size cap 200 KB** → `413 payload_too_large` before any session work
  (CONTRACTS §3 hard contract).
- **Per-session frame-rate limit** (server-side, wall-clock sliding window, default
  `NUNCHI_RATE_MAX=6` per `NUNCHI_RATE_WINDOW_S=1.0s`, i.e. room for a small burst above
  the ~2 fps client cap) → `429 rate_limited`. The frame bytes are dropped, only the
  `RateLimited` metric increments; the body never echoes the upload.
- **Cost guard**: AWS Budgets is payer-only (this is a member account), so by default a
  **CloudWatch alarm** `nunchi-api-request-spike` (API Gateway request Sum > 50k/5min) +
  optional SNS email (`--budget-email`) stands in — a request-volume ceiling is the cost
  proxy. On a payer account, deploy with `EnableBudget=true` for the real $20 budget.
- **Cost cap estimate**: at the API Gateway throttle (rate 20 req/s) the worst-case is
  ~20 × 86400 ≈ 1.7M req/day; realistic demo is far lower. HTTP API is $1.00/million requests,
  Lambda ~$0.30/50k frames → even a sustained abusive day stays in the low tens of dollars,
  which the request-spike alarm flags. Idle cost ~$0.
- CORS restricted to the CloudFront domain (+ localhost dev origin); all resources tagged
  `project=nunchikochi` / `delete-after=2026-11-30`.

Error codes are bilingual-ready and body-safe: `{"error":{"code","message"}}`, never the
uploaded bytes.

**Cold start.** The Lambda loads the ONNX models once at **module import** (handler
init), not per request, so the model-load cost is paid on the cold start only; warm
invocations skip it. **Measured on the real deploy (C3b)**: cold-start Init Duration
≈ 2.0 s (median), warm Billed Duration ≈ 44 ms (median) — see `docs/cloud/DEPLOY_LOG.md`.
The local warm `analyze` baseline is in `docs/cool/RESULTS_local.md`.

## Estimated monthly cost (us-east-1, demo scale)

Assumes a demo: ~**50k** frame invocations/month, 1536 MB, ~300 ms avg billed each;
small DynamoDB traffic; a few GB CloudFront egress; public traffic via API Gateway.
Order-of-magnitude, not a quote — the `nunchi-api-request-spike` CloudWatch alarm is the
backstop (AWS Budgets is payer-only on this member account).

| service | basis | est. / month |
|---|---|---|
| Lambda (arm64) | 50k × 0.3 s × 1.5 GB ≈ 22.5k GB-s; arm64 $0.0000133/GB-s + $0.20/M req | **≈ $0.30** |
| API Gateway HTTP API | ~50k requests × $1.00/M | **≈ $0.05** |
| DynamoDB on-demand | ~100k R/W units + <1 GB stored, TTL auto-expires rows | **≈ $0.20** |
| CloudFront | ~5 GB egress + requests (first 1 TB $0.085/GB) | **≈ $0.50** |
| S3 (web + code) | <1 GB stored + minimal requests | **≈ $0.05** |
| CloudWatch Logs + alarm | <1 GB ingest, 14-day retention; alarms first 10 free | **≈ $0.50** |
| SSM | Standard params free | **$0** |
| **total** | | **≈ $1–2 / month** |

Idle cost is ~$0 (all usage-priced; no NAT, no provisioned capacity). Free-tier may
absorb most of this.

## Run locally

```bash
uv sync --group service --group dev
uv run uvicorn nunchi.service.app:app        # http://127.0.0.1:8000
```

Environment:

| var | default | meaning |
|---|---|---|
| `NUNCHI_STATE_BACKEND` | `memory` | `memory` (local/tests) or `dynamo` |
| `NUNCHI_TABLE` | `nunchi-sessions` | DynamoDB table (when backend=dynamo) |
| `NUNCHI_API_KEY` | *(unset)* | direct key value; if set every request needs `X-Api-Key` |
| `NUNCHI_API_KEY_PARAM` | *(unset)* | SSM SecureString name to read the key from (deploy path) |
| `NUNCHI_CORS_ORIGINS` | *(unset → `*`)* | comma-separated web origins allowed by CORS |
| `NUNCHI_MODELS_DIR` | `models` | where real vision loads ONNX models |
| `NUNCHI_FORCE_STUB` | *(unset)* | `1` forces stub vision+agent (used by service tests) |
| `NUNCHI_BUILD_SHA` | `dev` | surfaced at `/healthz.build` |

**Key resolution & fail-closed:** `NUNCHI_API_KEY` (direct) wins; else
`NUNCHI_API_KEY_PARAM` is read from SSM once and cached. If `NUNCHI_API_KEY_PARAM` is
set but cannot be resolved, requests get **503 `auth_unavailable`** (never fail-open).
With neither set (local only), auth is skipped.

## Endpoints (CONTRACTS §3)

`GET /healthz` · `POST /v1/sessions` · `POST /v1/frames` (multipart) ·
`POST /v1/sessions/{id}/end` · `GET /v1/summary?date=` · `GET /v1/trace/{id}`

Input validation: frame ≤ 200 KB (`413 payload_too_large`), MIME in
`{image/jpeg, image/jpg, application/octet-stream}` (`415 unsupported_media`),
`t` in `[0, 86400]` and `phase ∈ {calibrate, run}` (`422 bad_request`),
unknown/expired session (`404 session_not_found`), bad key (`401 unauthorized`).
Error body is always `{"error":{"code","message"}}` and never echoes frame bytes.

## Tests

```bash
uv run --group service --group dev pytest tests/service -q   # 18 tests
```

Covers contract shapes, validation, auth (including SSM read + fail-closed), memory +
dynamo(moto) state, and the no-persist proof. `tests/service/test_no_persist.py` uploads
a JPEG with a unique marker and asserts the marker — raw, hex and base64 — appears in
**no** new file, **no** captured DEBUG log, and **no** summary/trace response (the
privacy guarantee made executable).

## Session state — see docs/ARCHITECTURE.md "세션 상태"

DynamoDB state record (not a signed client token). Local dev uses an in-memory adapter.

## Container (optional / fallback)

`cloud/Dockerfile` builds the same service as a Lambda arm64 **container** image. It is
**not** the default path — the zip above is. Keep it for the strategy-(b) fallback if
C4/COOL turns out to require a container or AMI. No local docker build is run in C2
(the dev laptop's docker daemon is off); a real image build would go through CodeBuild
(arm64) → ECR.
