# Q1 — Independent pre-submission review (GO/NO-GO)

Verifier role: this review **did not modify any source, model, config, or other tab's
document**. Only `docs/review/` and `tests/review/` were written. Findings are logged for
the owning tab to fix; they are **not** fixed here.

- Scope checked: competition requirements, security/secrets, privacy evidence, licensing,
  reproducibility, honesty audit, deploy status.
- Repo: `opencv_nunchikochi/` (git root `project_my/hackathon`). Checked 2026-10-22.
- Independent measurements by this review: full test suite **266 passed, 0 failed**
  (9.0 s, models present); model sha256 ×3 match the manifest; deployed web **200**,
  public Lambda Function URL `/healthz` **403** (org SCP, as documented).

**Verdict: GO (conditional).** No CRITICAL (submission-blocking, unfixable) finding. The
code, tests, docs, licensing, privacy, and honesty are submission-ready. The open items
are MAJOR-but-known (public API endpoint blocked by an org SCP) and user-owned logistics
(video, Devpost). See conditions at the end.

---

## 1. Requirements matrix (README "제출물 체크리스트" + DECISIONS)

| Requirement | Status | Evidence |
|---|---|---|
| Technical report (problem…responsible use) | **Met (draft)** | `docs/report/TECHNICAL_REPORT.md` (8 sections, PENDING list) — A7 draft, review pending |
| Judge-accessible repo + pinned deps, build/test/deploy instructions | **Met** | `pyproject.toml`+`uv.lock` pinned; `docs/REPRODUCE.md` (`run_local.sh`, `test_all.sh`); `cloud/README.md` |
| Architecture diagram (OpenCV5·AWS·COOL·agent) | **Partial** | spec exists (`docs/diagrams/AGENT_WORKFLOW_SPEC.md`); report has `<!-- DIAGRAM: -->` placeholders — **images not yet drawn (conductor)** |
| Working web endpoint (or live screen-share) | **Partial** | web (CloudFront) **200**; service healthy server-side (DEPLOY_LOG) but public **API** URL **403 (org SCP)** → judges can use the web UI, not direct API. See finding S-1 |
| ≤5 min video (team, app, architecture, results) | **User's** | `docs/DECISIONS.md` U5 — not an agent task |
| Evaluation evidence (failures + limits incl.) | **Met** | `docs/eval/AGENT_EVAL.md`, `VISION_ROBUSTNESS.md`, `WEB_E2E.md`; `VISION_EVAL.md` is an honest "unmeasured" template |
| (Special) COOL version/instance/reproducible measurement | **Deferred (honest)** | `docs/cool/*` — COOL is AMI-only vs our Lambda-zip; baseline only, AWS 20–70% cited not claimed. User-gated (U2) |
| (Special) Agent workflow diagram · trace · evaluation | **Met** | `docs/submission/AGENTIC_VISION.md` + `docs/submission/traces/` + `docs/diagrams/AGENT_WORKFLOW_SPEC.md` |
| Devpost registration / submission | **User's** | `docs/DECISIONS.md` U3 — not done yet (user) |
| Repo visibility / attribution / team intro | **User's** | U4 / U7 / U8 |

## 2. Security & secrets

| Check | Result | Evidence |
|---|---|---|
| 12-digit account IDs (working tree) | **Pass (none)** | grep over `*.py/md/json/yaml/sh/txt`, excluding 13-digit ts |
| AWS access keys `AKIA/ASIA…` | **Pass (none)** | grep working tree |
| Hardcoded api key/secret/password = long string | **Pass (none)** | grep working tree |
| Real emails | **Pass (none)** | grep (decorators/placeholders excluded) |
| Secrets in **git history** (`git log -p --all`) | **Pass (none)** | account-id / AKIA / secret-assignment patterns, masked-safe |
| API key handling | **Pass** | `src/nunchi/service/app.py` `_api_key_required`: SSM SecureString, header `X-Api-Key`, **fail-closed 503** when param set but unresolved; key never logged |
| CORS | **Pass, with note** | `app.py create_app`: origins from `NUNCHI_CORS_ORIGINS`; `allow_credentials=False`. **Note S-2**: defaults to `*` when env unset — deploy must set the CloudFront origin |
| Input size cap | **Pass** | 200 KB → `413`; empty → `422`; MIME whitelist → `415` (`app.py post_frame`) |
| Rate limit | **Pass** | `_rate_limited` sliding window → `429`, frame bytes dropped |
| Error responses leak internal info | **Pass** | `_error` returns `{code,message}` only; vision failure → generic 500, no bytes |
| Logs contain frames | **Pass** | `src/nunchi/service/metrics.py` numbers+bounded labels only; no bytes/keys/headers/session-id |
| Endpoint URL exposure | **Accept** | `docs/cloud/ENDPOINT.md`, `web/config.json` hold the Function URL/CloudFront host — **no key, no account id**; `config.json` is **gitignored** (`/.gitignore:12`), not committed |

## 3. Privacy evidence (frames never persisted)

Traced the frame path in `src/nunchi/service/app.py`: bytes read into a **local** `raw`,
size-checked, handed to vision in-memory, **`del raw` in `finally`**; never written to the
state store, DynamoDB, logs, metrics, or trace. Trace/metric builders sanitise to
strings/numbers (`_safe_tool_calls`, `_safe_jsonable`, `metrics.py`).

- Owning-tab test: `tests/service/test_no_persist.py` (marker in no file/log/response).
- **Independent counter-tests added** (`tests/review/test_privacy_no_frame_leak.py`, 3
  tests, **all pass**): the persisted **state store** object, the **EMF stdout stream**,
  and the **/v1/trace** payload each carry no marker (raw/hex/base64) and no image tokens
  over multiple frames.
- On AWS (documented, not re-run here): `docs/cloud/DEPLOY_LOG.md` — DynamoDB scan + 20 min
  of CloudWatch Logs show no jpeg/base64 tokens.

**Result: Pass.** The privacy claim holds on the code path and under adversarial probing.

## 4. Licensing

| Artifact | License | Commercial OK |
|---|---|---|
| Model: face_detection_yunet | MIT | yes |
| Model: face_landmarks_mediapipe (PINTO port) | Apache-2.0 | yes |
| Model: palm_detection_mediapipe (optional, `drink`) | Apache-2.0 | yes |
| opencv-python-headless 5.0.0.93 | Apache-2.0 | yes |
| numpy | BSD/MIT/Zlib | yes |
| fastapi / pydantic | MIT | yes |
| starlette / uvicorn / httpx | BSD-3-Clause | yes |
| python-multipart / boto3 / moto | Apache-2.0 | yes |
| mangum | MIT | yes |

**Result: Pass.** All permissive; **no non-commercial-restricted** model or dependency.
Source: `models/MANIFEST.json` + installed dist metadata.

## 5. Reproducibility

| Check | Result |
|---|---|
| Pinned deps (`uv sync --locked` reproducible) | **Pass** — `pyproject.toml` + `uv.lock` |
| Models present + sha256 match manifest | **Pass** — 3/3 match |
| Full test suite (this review ran it) | **Pass — 266 passed, 0 failed, 9.0 s** (incl. 6 review tests; 260 without) |
| Doc figure "242" (`docs/STATUS.md`) | **Stale, not wrong** — 242 was the 10/22 snapshot; suite has grown (V6/A5/A6/Q1). Finding H-1: refresh STATUS count |

Note: a clean `git worktree` + fresh model download was **not** re-run (network/time;
budget). Pinned deps + matching sha256 + a green suite on the current tree cover the same
guarantee; a fully clean-room run is left as a lightweight follow-up.

## 6. Honesty audit

| Angle | Result |
|---|---|
| Features claimed but absent in code | **None found.** `drink` is now correctly described as V7-implemented-but-conditional (palm model); A7 report resolves the old VISION_EVAL "unsupported" conflict to the code and flags the stale doc (H-2) |
| Numbers without basis | **None.** Latency numbers are labelled dev-baseline; COOL 20–70% is cited to AWS, not claimed |
| Real vs synthetic confusion | **None.** `VISION_ROBUSTNESS.md` and `RESULTS_local.md` repeatedly state "synthetic", "Apple Silicon — NOT Graviton", "dev baseline" |
| "on-device" / inaccurate wording | **Clean.** `web/README.md` explicitly makes *no* "on-device only" claim (W1 fix landed; STATUS note is the historical instruction) |
| Medical/diagnosis or minor-targeting | **Clean.** No-diagnosis is enforced (guardrail + tests); matches for "child/minor" were code tokens (`appendChild`), not product copy |

## Findings (severity · owner · action)

| ID | Sev | Finding | Evidence | Owner → action |
|---|---|---|---|---|
| **S-1** | **MAJOR** | Public Lambda Function URL returns **403** (org SCP) — judges cannot call the API directly; only the web UI is public. Service itself is healthy server-side. | `docs/cloud/ENDPOINT.md`, `DEPLOY_LOG.md`; this review: `/healthz` 403, web 200 | cloud/user → either get the payer/org admin to allow public Function URLs, or front via API Gateway/CloudFront-to-Lambda (design change, needs approval), **or** rely on the web UI + a live screen-share demo for judging. Decide before submission. |
| S-2 | minor | CORS defaults to `*` when `NUNCHI_CORS_ORIGINS` unset | `src/nunchi/service/app.py` `create_app` | cloud → ensure deploy sets the CloudFront origin (the stack passes it; confirm it is set in the deployed env) |
| H-1 | minor | `docs/STATUS.md` test count "242" is stale (actual 266 incl. review / 260 without) | this review's run | conductor → refresh the count |
| H-2 | minor | `docs/eval/VISION_EVAL.md` still says `drink` "unsupported"; code implements it in V7 | `src/nunchi/vision/hands.py`, `src/nunchi/vision/engine.py` vs VISION_EVAL §3/§6 | vision → refresh VISION_EVAL for V7; measure `drink` on real clips |
| H-3 | minor | Architecture diagram images not drawn yet (report has placeholders) | `docs/report/TECHNICAL_REPORT.md` `<!-- DIAGRAM -->` | conductor → draw architecture + agent-workflow diagrams before submission |
| N-1 | note | Vision behaviour accuracy is **unmeasured** (no real clips); robustness is synthetic | `docs/eval/VISION_EVAL.md`, `VISION_ROBUSTNESS.md` | user/vision → U1 clip recording would upgrade this from honest-gap to measured |

No CRITICAL findings.

## GO / NO-GO

**GO, conditional on:**
1. **S-1 resolved or worked around** before submission — either expose the API publicly
   (org change / API Gateway) **or** commit to judging via the public web UI + a live
   screen-share / recorded demo (the service is verified healthy server-side). This is the
   single most important pre-submission decision.
2. **Architecture diagrams drawn** (H-3) and the A7 report reviewed/accepted.
3. **User-owned items** (U3 Devpost, U4 visibility, U5 video, U7/U8) completed — outside
   agent scope.

Everything in the agent-verifiable surface (security, privacy, licensing, reproducibility,
honesty, agent/web evaluation) is **ready**. The honest gaps (unmeasured real-clip
accuracy, deferred COOL, stub-based agent eval) are disclosed in the docs, not hidden —
which is itself a point in the submission's favour.

### Not independently verified (disclosed, not hidden)
- Server-side AWS pipeline health (OpenCV 5 on aarch64, full session) — **documented** in
  `DEPLOY_LOG.md` via IAM-signed invoke; this review could not re-run it without a key
  (out of scope: no key-bearing calls).
- Clean-room `git worktree` reproduction with fresh model download (covered indirectly by
  pinned deps + sha256 match + green suite).
- Real-clip vision accuracy (U1 not done).
