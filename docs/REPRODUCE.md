# Reproduce nunchikochi locally (judge guide)

> 한 줄 요약(KO): AWS 없이 `scripts/run_local.sh` 하나로 서비스+웹을 띄우고, `scripts/test_all.sh` 하나로 전체 테스트를 재현합니다. 모델은 자동 내려받아 체크섬 검증합니다.

nunchikochi is OpenCV 5 computer vision + an AWS "Agentic Vision" decision loop. **You do
not need an AWS account to run or test it** — everything below runs locally with an
in-memory store and the deterministic agent (no cloud, no LLM calls).

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** (Python package manager) — the only hard requirement.
  Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Python **3.11 or 3.12** — uv fetches it automatically from `pyproject.toml` if absent.
- OS: macOS or Linux, arm64 or x86_64.
- `curl` (for the health check). A modern browser for the web UI (camera permission for
  live use).
- No API keys, no AWS credentials.

Dependencies are **pinned** (`pyproject.toml` + `uv.lock`); `uv sync --locked` reproduces
the exact environment.

## 1. Run it (≈5 minutes, first run downloads models)

```bash
scripts/run_local.sh
```

This: checks `uv` → syncs pinned deps → downloads + **sha256-verifies** the ONNX models
(`models/download_models.py`) → starts the FastAPI service (uvicorn, in-memory state) →
serves the web static files → prints the URLs. A **local dummy API key** is generated and
printed (it is not a secret — the service is local and in-memory). `Ctrl-C` tears
everything down.

When it's up:
- Web UI:  `http://127.0.0.1:8099`
- Service: `http://127.0.0.1:8000` — e.g. `curl http://127.0.0.1:8000/healthz` → `{"ok":true,...}`

Ports are configurable: `NUNCHI_SVC_PORT`, `NUNCHI_WEB_PORT`. Exit codes: `10` uv missing,
`11` port in use, `12` model download/verify failed.

## 2. Run the tests

```bash
scripts/test_all.sh
```

Runs the whole suite (vision + agent + service + end-to-end) on pinned deps. The e2e tests
drive the **real** OpenCV engine, so if the models are missing the script **fails with
guidance** (it never silently skips). First run ≈1–2 min; it prints the elapsed time.

Cloud-only unit tests (CloudFormation template, packaging) don't need AWS:

```bash
uv run pytest tests/service tests/e2e -q     # service + integration
uv run cfn-lint cloud/template.yaml          # infra template lints clean (0 errors)
```

## 3. Reproduce the evaluation harnesses

Both run offline and prove the pipeline end to end (synthetic/public-sample numbers only
prove "the pipeline works"; real metrics need your own labelled clips — see `eval/README.md`):

```bash
# vision eval — synthetic self-test (per-behavior precision/recall table)
uv run python eval/run_vision_eval.py --self-test

# agentic decision eval — 22 deterministic scenarios + adversarial holds
uv run python eval/agent/run_eval.py
```

## 4. Deploy to AWS (optional, summary)

Not required for judging. The full one-command deploy/destroy, the single CloudFormation
stack (S3+CloudFront OAC web, Lambda arm64 zip + Function URL, DynamoDB, CloudWatch
dashboard/alarms, $20 budget), the arm64 packaging, and the estimated monthly cost table
(**≈ $1–2/month** at demo scale, ~$0 idle) are documented in **[`cloud/README.md`](../cloud/README.md)**.
Scripts default to dry-run; `--apply` performs the real deploy. No account IDs or keys
appear in this repo.

## Known limitations

- **Cold start**: the Lambda loads the ONNX models at init (once per instance); a measured
  cold-start figure is deferred to a real deploy. The warm `analyze` baseline is in
  `docs/cool/RESULTS_local.md` (Apple Silicon dev baseline — **not** AWS Graviton).
- **COOL** (Cloud-Optimized OpenCV, Graviton): ships as an AMI only, so it can't drop into
  the Lambda zip; the "Best Use of COOL" track is a conditional stretch goal (see
  `docs/cool/LISTING_NOTES.md`). The default build is pip `opencv-python-headless`.
- **Request size** is capped at 200 KB per frame (`413`), with a server-side per-session
  frame-rate limit (`429`) as abuse defense.
- Vision/agent eval numbers from `--self-test` are pipeline checks, not accuracy claims.

## Privacy note

Frame bytes live only inside a request handler's local scope — never written to disk, logs,
traces, metrics, or session state. Only aggregate summaries are persisted. This invariant is
enforced by tests (`tests/service/test_no_persist.py`, the e2e privacy test).
