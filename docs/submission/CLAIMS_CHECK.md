# Claims check (A15)

Every claim in the submission docs, tagged **Measured / Estimated / Not measured**, with
the evidence file. A claim with no evidence file is removed, not kept. "Measured" means a
test or a run produced the number; "Estimated" means a synthetic or pricing model, not
real-use data; "Not measured" means we explicitly do not claim it yet.

| Claim | Evidence | Status |
|---|---|---|
| Frames never persist: a marked JPEG appears 0× across 5 surfaces (files, logs, DynamoDB state, EMF, trace), 5 tests pass | `tests/service/test_no_persist.py`, `tests/review/test_privacy_no_frame_leak.py` (ran: 5 passed) | **Measured** |
| 361 automated tests pass | `uv run pytest -q` → 361 passed (2026-10-25) | **Measured** |
| Web e2e 97/97, buddy unit 7/7, axe 0 hard violations | `docs/eval/WEB_E2E.md` (W21) | **Measured** (per doc) |
| Per-frame OpenCV ~178–282 ms on Graviton (stable ~178 ms per warm host), ~2.5 s cold Init | `docs/cloud/LATENCY.md`, `docs/eval/LATENCY_REGRESSION.md` | **Measured** (one deployed stack, host-variance range) |
| `second_look` changed the decision in 3/7 ambiguous moments (42.9%) | `docs/eval/AGENT_EVAL.md` | **Measured** (stub harness, synthetic) |
| Calming cut interruptions 9 → 5 over a 1-hour session; first alert unchanged (180 s); first repeat nudge delayed 600 s; held alerts counted | `docs/eval/ALERT_CALMING.md`, `eval/agent/alert_calming.py`, `tests/agent/test_alert_calming.py` | **Estimated** (synthetic session, not real use) |
| Bad-posture timeline (5/10/30/60-min buckets + hour-rate); multi-session trend over ≤5 sessions (improving/same/worsening) | `src/nunchi/agent/summary.py`, `tests/agent/test_timeline.py`, `docs/eval/timeline_sample.json` | **Measured** (logic, deterministic); live non-"na" trend proven by unit test only |
| Vision measures, code decides, LLM proposes, person is final authority | `src/nunchi/vision`, `src/nunchi/agent/policy.py`, `src/nunchi/agent/guardrails.py`, `tests/agent/test_guardrails_deep.py` | **Measured** (code + tests) |
| Head yaw/pitch/roll + depth via `cv2.solvePnP` (roll from eye-line) | `src/nunchi/vision/headpose.py` | **Measured** (pipeline runs); angles are relative, not absolute |
| Posture buddy is a **face + neck** figure (no body/arms/desk); head pose + facial expression are measured, the neck is an estimate from the measured head angles | `web/buddy-kinematics.js` (W20 header), `web/buddy.js`, `docs/eval/WEB_E2E.md` (W20 face+neck checks) | **Measured** (head + expression drive the rig; buddy unit 7/7); neck is a labelled **estimate** |
| Facial expression channels (eyes/mouth/smile/brows) are **measured face movement, not emotion inference**; `drink` shows a small cup near the mouth during the measured event (no arm) | `web/buddy-kinematics.js`, `web/buddy.js` (cup icon + "taking a sip" chip), `docs/eval/FACE_EXPRESSION.md` | **Measured** (face movement); explicitly **not** an emotion claim |
| Synthetic head-pose error ~3–5° yaw/pitch, ~2–3° roll under jitter | `docs/eval/VISION_EVAL.md` §6 | **Estimated** (synthetic rotation) |
| `drink` typing/chin-rest false-positive paths rejected by a vertical + rise-trajectory gate | `docs/eval/DRINK_FEASIBILITY.md` §6-7, `tests/vision/test_events.py`, `tests/vision/test_hands.py` | **Estimated** (synthetic geometry) |
| `drink` real-clip accuracy; it is a hand-position estimate (palm near mouth), cup not detected | `docs/eval/DRINK_FEASIBILITY.md` §4, §8 | **Not measured** |
| Buddy neck is estimated from the measured head angles, not measured body pose; no body/shoulders/torso/legs are drawn | `web/buddy-kinematics.js`, `docs/eval/BODY_POSE_FEASIBILITY.md` | **Not measured** (body pose); the estimate is labelled in the UI |
| Live mode uses a one-button 30-minute trial key issued from the page; per-IP 3/day, 6/day global; no shared key passed to judges | `web/index.html` (#btn-trial-key), `web/api.js` (createTrialKey), `cloud/template.yaml` (NUNCHI_KEY_ISSUING, NUNCHI_KEY_IP_DAILY=3, NUNCHI_KEY_GLOBAL_DAILY=6), `web/e2e/run.mjs` (trial-key group W21) | **Measured** (mechanism + e2e); 6/day global is a config value, not a load test |
| Trial-key per-IP limit stores only a keyed hash of the client IP for 48 h; raw IP never stored and removed from access logs | `cloud/template.yaml` (§5 privacy comment; HMAC salt SSM SecureString), `web/i18n.js` (trialKeyIpNote) | **Measured** (template config + UI note); not an external audit |
| Quiet mode on by default; nudge ≈20-min cooldown, ≤3/hour; confirm ≤2/hour, no same kind in a row; 30-s quality debounce | `web/app.js` (`quiet:true`), `src/nunchi/agent/context.py` (`PolicyConfig`), `src/nunchi/agent/policy.py` | **Measured** (code + `tests/agent/test_calm_alerts.py`) |
| Multi-session comparison keyed to an anonymous per-browser id; does not follow across browsers/devices | `docs/CONTRACTS.md` §2 (CONTRACT-CHANGE), W17 `X-Anon-Id` | **Measured** (mechanism); longitudinal value **Not measured** |
| Lambda arm64 / API Gateway / S3+CloudFront OAC / DynamoDB TTL / SSM SecureString / CloudWatch EMF / Bedrock | `docs/cloud/ENDPOINT.md`, `docs/report/TECHNICAL_REPORT.md` §5 | **Measured** (deployed) |
| Org SCP blocked the Function URL (403) → API Gateway HTTP API swap → health 200 | `docs/cloud/ENDPOINT.md` | **Measured** |
| No-diagnosis guardrail blocks health claims in EN + KO | `src/nunchi/agent/guardrails.py`, `tests/agent/test_guardrails_deep.py` | **Measured** |
| Cost ~$1–2/month at demo scale, idle ≈ $0, $20 budget alarm | `docs/report/TECHNICAL_REPORT.md` §5, `cloud/README.md` | **Estimated** (public pricing, not a bill) |
| 22 deterministic + 9 adversarial agent scenarios; LLM metrics smoke-level | `docs/eval/AGENT_EVAL.md`, `docs/submission/AGENTIC_VISION.md` | **Measured** (stub/self-written); not a generalisation claim |

## Notes for the conductor

- **Python suite count**: obtained directly via `uv run pytest -q` → **361 passed** (2026-10-25).
- **Web e2e count**: `docs/eval/WEB_E2E.md` records **97/97** (W21; grew 60 → 76 → 83 → 87 → 89 → 90 → 97).
- **Posture buddy**: as of W20 the figure is a **face + neck** (no body, arms, hands or desk);
  W22 redrew the face so expressions read. The drink gesture is a small cup near the mouth,
  not an arm lift. Any older "seated upper-body / torso / arm raise" wording is stale.
- **Trial key (W21)**: judges need no shared key — the live page issues a 30-minute key on
  one click, limited per IP (3/day) and globally (6/day, user decision 2026-10-25). The
  per-IP check uses a keyed IP hash kept 48 h; raw IP is not stored.
- **Public-repo hygiene**: docs refer to the AWS profile as `<aws-profile>` (the C/cloud tab
  runs deploys); code may still carry `profile="<aws-profile>"` and is out of this tab's scope.
