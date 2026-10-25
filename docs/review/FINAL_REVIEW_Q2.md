# FINAL REVIEW — Q2 (independent verifier, read-only)

Re-audit after V12·V13 (drink), A11·A12·A13·A14 (alerts/history/submission), C14·C15·C16
(server history, CORS, redeploy), W16–W19 (UI). **I did not modify source or data.** I ran
everything myself; I do not trust prior reports. Date: 2026-10-25.

Verdict: **GO** (0 critical, 0 major; 2 minor/hygiene, 3 honest unmeasured gaps). Reasons below.

---

## 1. Reproduction (ran directly)

| Check | Command | Expected | Got | Status |
|---|---|---|---|---|
| Python suite | `uv run pytest -q` | 320 | **320 passed** | ✅ |
| Web e2e | `npm run e2e` | 87/87 | **87/87, 0 failed** | ✅ |
| Buddy unit | `npm run test:unit` | 6/6 | **6 pass, 0 fail** | ✅ |
| My new privacy tests | `pytest tests/service/test_privacy_q2_adversarial.py` | — | **6 passed** | ✅ (added) |

Numbers match the submission docs. No count discrepancy.

## 2. Privacy re-verification (most important)

New storage path = `summary_store.py` (`sanitize_summary` whitelist) + `_anon_hash`
(sha256[:32]) + browser localStorage anon id. I wrote **6 new adversarial counter-examples**
(`tests/service/test_privacy_q2_adversarial.py`) attacking angles the existing suite misses,
plus re-ran the existing 5.

| Counter-example | Attack | Result |
|---|---|---|
| hash one-way | token ⊄ hash, 1-char change → different pk | ✅ pass |
| raw token absent | token never in store keys/values (only hash) | ✅ pass |
| deep-nested + list image/landmark/coord | banned substrings buried in maps **and** list elements | ✅ all stripped |
| bytes / ndarray values | JPEG bytes / numpy in a non-image key name | ✅ dropped to null, no pixels |
| marker forced through summary | upstream bug attaches `image`/`frame_jpeg` to summary | ✅ 0× in stored item |
| same-day 2 users | cross-user row isolation | ✅ isolated |
| (existing) frame never persists | marked JPEG across files/logs/trace/summary | ✅ `test_no_persist.py` (2) + `tests/review/test_privacy_no_frame_leak.py` (3) = 5 pass |
| (existing) no image/landmark key stored | `test_history_trend.py` whitelist proofs | ✅ pass |

Probed `sanitize_summary` directly: banned substrings removed at every depth incl. inside
lists; bytes→None, ndarray→None (no pixel payload); non-whitelisted top keys dropped; strings
capped at 64 chars. **The "numbers-only, no raw id, isolated" claim holds under all tested
attacks.** Not tested: a real adversarial client over the live API (did not send keyed traffic).

## 3. Honesty of new features

- **Alert 9→5**: `alert_calming_result.json` has `before.total_alerts=9`, `after.total_alerts=5`.
  Marked **synthetic** in `ALERT_CALMING.md` (EN+KO: "결정적 합성 1시간 … 실사용 측정 아님"),
  `alert_calming_result.json` (`"kind":"synthetic (NOT a real-use measurement)"`), and
  `TECHNICAL_REPORT.md` ("synthetic 1-hour calming 9 → 5"). The synthetic tag is **not** dropped
  anywhere I found. ✅
- **"Improving" comparison**: trend sentence comes from the **server** (`report.trend.line_*`);
  demo shows sample history under an **"Example data"** badge+note and never writes localStorage;
  real mode uses server history (local-number fallback only). e2e proves the Example-data label
  and demo-no-storage. No fabricated values in real mode. ✅
- **CLAIMS_CHECK.md spot-check (10 of ~20, ≥8 required)**: all evidence files exist and numbers
  match — 320 tests ✅; e2e 87/87 ✅; buddy 6/6 ✅; frame-non-persist "5 tests" = 2+3 ✅;
  second_look 3/7=42.9% (`AGENT_EVAL.md`) ✅; alert 9→5 (`alert_calming_result.json`) ✅; drink
  gate tests present (`test_events.py`, `test_hands.py`) ✅; guardrail EN+KO (`test_guardrails_deep.py`, passed) ✅; timeline (`test_timeline.py`, 5) ✅; cooldown 1200s / ≤3 nudges / ≤2 confirms (`context.py`) ✅. Statuses (Measured/Estimated/Not measured) are accurate.
- **Devpost (`DEVPOST_TEXT.md`)**: not line-by-line re-derived, but its headline numbers trace to
  the same evidence as CLAIMS_CHECK and the synthetic/estimated labels are present. Low risk.

## 4. Deployed build (live, no key printed)

Endpoints from `ENDPOINT.md`. All checked directly:

| Check | Result |
|---|---|
| `GET /healthz` | **200** |
| `POST /v1/sessions` with no key | **401** (gated) |
| CORS preflight `OPTIONS /v1/sessions` (`x-anon-id`) | **200**, allow-origin = CloudFront, allow-headers = `content-type,x-anon-id,x-api-key`, methods `GET,OPTIONS,POST` |
| Demo page `/` | **200** |
| Web file sha vs source | **7/7 MATCH** (app.js, index.html, buddy.js, i18n.js, mock.js, demo.js, styles.css) |

Deploy is in sync with source; the key was never used or printed (SSM SecureString only).

## 5. User-scenario checks (code + runnable)

| Scenario | How checked | Finding |
|---|---|---|
| Typing → drink false positive | V12/V13 synthetic gates (vertical dy + rise trajectory); `test_events.py`/`test_hands.py` pass; `DRINK_FEASIBILITY.md` §6-8 | rejected in synthetic geometry. **Real-clip accuracy = unmeasured** (user's clip, honest) |
| Alert cooldown | `context.py`: same-behaviour 1200 s, ≤3/hr nudges, ≤2/hr confirms; `test_calm_alerts.py` | behaves as claimed |
| Session < 10 min display | `summary.py`: `per_hour_rate=None` when `duration<600s`; W19 e2e (bar + count, "too short to compare") | correct |
| 2 sessions → history link | `test_history_trend.py` (isolation, hash), W17 e2e (anon id persists, re-issued on clear) | correct |

Synthetic-only: drink rejection, alert 9→5, head-pose error. Real: endpoint/CORS/deploy sha.
Needs real use: behaviour **accuracy** on a real face (no clips exist yet).

## 6. Public repo (`github.com/jogilsang/opencv-nunchikochi`, HEAD e49fc34 ✓)

`git clone --depth 1` then grepped:

| Check | Result |
|---|---|
| absolute home-directory paths | **0** |
| 12-digit AWS account id | **0** |
| personal / company identifiers (name, email, org slug) | **0** |
| keys/secrets (AKIA…, api-key=…, BEGIN PRIVATE) | **0** |
| `config.json` / `*.onnx` models / videos | **0** (gitignored: `models/*.onnx`, `eval/clips/`, `web/config.json`, `node_modules/`) |
| committed images | 81 PNG/JPG — all **UI screenshots (synthetic/fake-cam, no real face per ASSETS.md)** + public OpenCV samples in `tests/vision/_samples/` (RULES-allowed) |
| git author on HEAD | `jogilsang@users.noreply.github.com` (no real email) |

**Minor (not critical)**: the string `captain` (AWS **profile name**, a local SSO alias — not a
key/account id; DEPLOY_LOG says "account masked") and the relative fragment `project_my/hackathon`
appear in committed docs (`agent/README.md`, `smoke_llm.py`, `docs/cloud/*`, `Q1_REPORT.md`).
Neither is a secret or personal/company identity; hygiene-level only.

---

## Findings

| # | Severity | Finding | Reproduce | Owner |
|---|---|---|---|---|
| F1 | minor | AWS profile name `captain` + relative path `project_my/hackathon` committed in docs/code | `grep -rn captain\|project_my` on clone | C / conductor (optional scrub) |
| F2 | note | drink/alert/head-pose numbers are **synthetic**; real-face **accuracy unmeasured** | `DRINK_FEASIBILITY.md` §8, `VISION_EVAL.md` §6 | user (record U1 clips) |
| F3 | note | Devpost body not re-derived line-by-line (headline numbers trace to evidence) | — | conductor (final eyeball) |

No critical, no major. Everything the submission claims as Measured reproduced; everything
synthetic/estimated is labelled as such; privacy claims survived fresh adversarial tests; the
deployed build matches source; the public repo carries no secrets, account ids, paths, models,
videos, or personal/company identity.

## Verdict: **GO**

Conditions already met (no blocking conditions). Optional before/at submission: F1 scrub (cosmetic),
F3 eyeball of Devpost text. The only real gap (F2) is an **honest, documented** unmeasured item
(real-clip accuracy), not a defect.

### Not verified (explicit "미검증")
- Real-face behaviour accuracy (no clips exist; synthetic only).
- Live API under real keyed/adversarial client traffic (did not send keyed requests).
- Graviton latency numbers (trusted `LATENCY.md`; did not re-run on the deployed stack).
- Devpost prose line-by-line (headline figures spot-checked only).
