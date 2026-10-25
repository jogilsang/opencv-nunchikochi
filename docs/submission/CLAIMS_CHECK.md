# Claims check (A13)

Every claim in the submission docs, tagged **Measured / Estimated / Not measured**, with
the evidence file. A claim with no evidence file is removed, not kept. "Measured" means a
test or a run produced the number; "Estimated" means a synthetic or pricing model, not
real-use data; "Not measured" means we explicitly do not claim it yet.

| Claim | Evidence | Status |
|---|---|---|
| Frames never persist: a marked JPEG appears 0× across 5 surfaces (files, logs, DynamoDB state, EMF, trace), 5 tests pass | `tests/service/test_no_persist.py`, `tests/review/test_privacy_no_frame_leak.py` (ran: 5 passed) | **Measured** |
| 320 automated tests pass | `uv run pytest -q` → 320 passed (2026-10-22) | **Measured** |
| Web e2e 87/87, buddy unit 6/6, axe 0 hard violations | `docs/eval/WEB_E2E.md` (W18) | **Measured** (per doc) |
| Per-frame OpenCV ~178–282 ms on Graviton (stable ~178 ms per warm host), ~2.5 s cold Init | `docs/cloud/LATENCY.md`, `docs/eval/LATENCY_REGRESSION.md` | **Measured** (one deployed stack, host-variance range) |
| `second_look` changed the decision in 3/7 ambiguous moments (42.9%) | `docs/eval/AGENT_EVAL.md` | **Measured** (stub harness, synthetic) |
| Calming cut interruptions 9 → 5 over a 1-hour session; first alert unchanged (180 s); first repeat nudge delayed 600 s; held alerts counted | `docs/eval/ALERT_CALMING.md`, `eval/agent/alert_calming.py`, `tests/agent/test_alert_calming.py` | **Estimated** (synthetic session, not real use) |
| Bad-posture timeline (5/10/30/60-min buckets + hour-rate); multi-session trend over ≤5 sessions (improving/same/worsening) | `src/nunchi/agent/summary.py`, `tests/agent/test_timeline.py`, `docs/eval/timeline_sample.json` | **Measured** (logic, deterministic); live non-"na" trend proven by unit test only |
| Vision measures, code decides, LLM proposes, person is final authority | `src/nunchi/vision`, `src/nunchi/agent/policy.py`, `src/nunchi/agent/guardrails.py`, `tests/agent/test_guardrails_deep.py` | **Measured** (code + tests) |
| Head yaw/pitch/roll + depth via `cv2.solvePnP` (roll from eye-line) | `src/nunchi/vision/headpose.py` | **Measured** (pipeline runs); angles are relative, not absolute |
| Synthetic head-pose error ~3–5° yaw/pitch, ~2–3° roll under jitter | `docs/eval/VISION_EVAL.md` §6 | **Estimated** (synthetic rotation) |
| `drink` typing/chin-rest false-positive paths rejected by a vertical + rise-trajectory gate | `docs/eval/DRINK_FEASIBILITY.md` §6-7, `tests/vision/test_events.py`, `tests/vision/test_hands.py` | **Estimated** (synthetic geometry) |
| `drink` real-clip accuracy; it is a hand-position estimate (palm near mouth), cup not detected | `docs/eval/DRINK_FEASIBILITY.md` §4, §8 | **Not measured** |
| Buddy neck/torso/shoulders are estimated from head+hand, not measured body pose | `web/buddy-kinematics.js`, `docs/eval/BODY_POSE_FEASIBILITY.md` | **Not measured** (body pose); estimation is labelled in the UI |
| Quiet mode on by default; nudge ≈20-min cooldown, ≤3/hour; confirm ≤2/hour, no same kind in a row; 30-s quality debounce | `web/app.js` (`quiet:true`), `src/nunchi/agent/context.py` (`PolicyConfig`), `src/nunchi/agent/policy.py` | **Measured** (code + `tests/agent/test_calm_alerts.py`) |
| Multi-session comparison keyed to an anonymous per-browser id; does not follow across browsers/devices | `docs/CONTRACTS.md` §2 (CONTRACT-CHANGE), W17 `X-Anon-Id` | **Measured** (mechanism); longitudinal value **Not measured** |
| Lambda arm64 / API Gateway / S3+CloudFront OAC / DynamoDB TTL / SSM SecureString / CloudWatch EMF / Bedrock | `docs/cloud/ENDPOINT.md`, `docs/report/TECHNICAL_REPORT.md` §5 | **Measured** (deployed) |
| Org SCP blocked the Function URL (403) → API Gateway HTTP API swap → health 200 | `docs/cloud/ENDPOINT.md` | **Measured** |
| No-diagnosis guardrail blocks health claims in EN + KO | `src/nunchi/agent/guardrails.py`, `tests/agent/test_guardrails_deep.py` | **Measured** |
| Cost ~$1–2/month at demo scale, idle ≈ $0, $20 budget alarm | `docs/report/TECHNICAL_REPORT.md` §5, `cloud/README.md` | **Estimated** (public pricing, not a bill) |
| 22 deterministic + 9 adversarial agent scenarios; LLM metrics smoke-level | `docs/eval/AGENT_EVAL.md`, `docs/submission/AGENTIC_VISION.md` | **Measured** (stub/self-written); not a generalisation claim |

## Notes for the conductor

- **Web e2e count**: the owned source `docs/eval/WEB_E2E.md` now records **87/87** (W18),
  so the submission docs cite 87/87. (In A13 the doc still said 60/60; W18 re-counted it.)
- Python suite count 320 was obtained directly via `uv run pytest -q`.
