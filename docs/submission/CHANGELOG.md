# Submission text changelog

## v2 (A10) — reshaped to the Zero-to-Shipped winning-entry pattern

v1 baseline commits: DEVPOST_TEXT.md `bb55def`, README.md `c6652e9`.

- Reordered both DEVPOST_TEXT and README top to: meta block → try-it-in-one-minute → one illustrative scene → one headline number → who-decides-what → product → build (short) → limits.
- Added an **illustrative scene** ("2:40 PM, Mina") explicitly labelled *not a real user*.
- Picked one **headline number**: frame non-storage proven by a counterexample (marker found 0× across 5 surfaces), with the reproduction command inline.
- Added a **Who decides what** table + the line "the vision pipeline measures, the code decides, the model only proposes" (DEVPOST, README, TECHNICAL_REPORT §3).
- Replaced the limits bullet list with a **Built / Measured / Not measured / On hold** table (DEVPOST §8, README, TECHNICAL_REPORT §7).
- Moved **code link + meta block** to the very top (Category / Agentic Vision / Live `?demo=1` / Code / Built with).
- Corrected web e2e to the current **60/60** (+ buddy unit 6/6); kept full suite at **286**; condensed the build-process narrative to one paragraph.
- Fixed the live link to the no-key demo deep link `…/?demo=1`.

## Self-check: every new/changed claim has repo evidence

| Claim (v2) | Evidence |
|---|---|
| Frames leave no trace: marker 0× across 5 surfaces, 5 tests | `tests/service/test_no_persist.py`, `tests/review/test_privacy_no_frame_leak.py` (ran: 5 passed) |
| 286 tests pass | `uv run pytest tests -q` → 286 passed (2026-10-22) |
| Web e2e 60/60, buddy unit 6/6, axe 0 hard | `docs/eval/WEB_E2E.md` |
| Demo deep link `?demo=1`, 60–90 s window, "Skip to report" | `web/app.js` (?demo), `docs/eval/WEB_E2E.md` W13 row |
| Three panels: overlay, posture buddy, agent activity | `docs/eval/WEB_E2E.md` core-flow + posture-buddy rows |
| second_look changed decision 3/7 (42.9%), stub-based | `docs/eval/AGENT_EVAL.md` |
| Vision measures, code decides, LLM proposes; person final | `src/nunchi/vision`, `src/nunchi/agent/policy.py`, `src/nunchi/agent/guardrails.py`, `tests/agent/test_guardrails_deep.py` |
| Head yaw/pitch/roll via solvePnP, roll from eye-line | `src/nunchi/vision/headpose.py` |
| Latency ~178–282 ms host-variance range, +1.6 ms pose | `docs/cloud/LATENCY.md`, `docs/eval/LATENCY_REGRESSION.md` |
| Synthetic head-pose error ~3–5°/~2–3° | `docs/eval/VISION_EVAL.md` §6 |
| Buddy = face + neck; head pose + expression measured, neck estimated, no body drawn | `web/buddy-kinematics.js`, `docs/eval/BODY_POSE_FEASIBILITY.md` |
| Lambda arm64 / API Gateway / S3+CloudFront OAC / DynamoDB TTL / SSM / EMF / Bedrock | `docs/cloud/ENDPOINT.md`, `docs/report/TECHNICAL_REPORT.md` §5 |
| Org SCP 403 → API Gateway swap, 200 | `docs/cloud/ENDPOINT.md` |
| No-diagnosis guardrail EN+KO | `src/nunchi/agent/guardrails.py`, `tests/agent/test_guardrails_deep.py` |
| Cost ~$1–2/mo estimate, $20 alarm | `docs/report/TECHNICAL_REPORT.md` §5, `cloud/README.md` |
| 22 deterministic + 9 adversarial scenarios | `docs/eval/AGENT_EVAL.md`, `docs/submission/AGENTIC_VISION.md` |
