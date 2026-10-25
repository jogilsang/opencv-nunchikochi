# Nunchikochi (눈치코치)

- **Theme**: self-awareness coaching with OpenCV 5 on AWS · **Special prize**: Agentic Vision
- **Live (no key)**: https://dhys8dgxlvbgx.cloudfront.net/?demo=1 · **Code**: this repo
- **Built with**: OpenCV 5 · AWS Lambda (Graviton) · API Gateway · CloudFront+S3 · DynamoDB · Bedrock · FastAPI · ONNX · NumPy · JavaScript

It's 2:40 PM and Mina has been heads-down for two hours — her head drifting toward the screen, chin dropping, blinks getting long and slow. She notices none of it; that's what a habit is. A blunt tool would have buzzed her twelve times and been muted before lunch. *(An illustrative day — not a real user.)*

*Nunchikochi is a calm desk coach that reads your own posture and fatigue cues with **OpenCV 5** and lets an **agent decide** whether to nudge, stay quiet, or look again — for the OpenCV AI Competition 2026.* The browser webcam sends a small JPEG about twice a second; an AWS Lambda on **arm64 (Graviton)** analyses it in memory and discards it. **Frames are never stored** — only aggregates and filter state (≤ 8 KB, 24 h TTL) are kept.

## Try it in one minute

Open **https://dhys8dgxlvbgx.cloudfront.net/?demo=1** — no camera, no key, no sign-up. A short recorded session plays (a 60–90 s window; "Skip to report" ends it). Watch three things: the **overlay** (detected landmarks/behaviours), the **posture buddy** (head angle + distance avatar), and the **agent activity panel** (each frame's nudge / confirm / look-again / silent decision) with **quiet mode on by default** — posture is still recorded, alerts are held and counted. The **report** shows your bad-posture record per 5 / 10 / 30 / 60 min plus an hour-rate, and compares today with your recent sessions on a repeat visit. **Live** mode uses your webcam and needs an access key supplied with the submission note — everything core is visible in demo mode without it.

## The number that is the product

**A frame leaves no trace — proven by a counterexample, not a promise.** A test uploads a JPEG with a unique marker, runs the real perceive→decide path, then searches every surface it could leak into — new files, every log line, the DynamoDB session state, the CloudWatch EMF stream, and the `/v1/trace` response — in raw, hex, **and** base64. The marker appears **0 times across all five surfaces** (5 counterexample tests).

```bash
uv run --group service --group dev pytest \
  tests/service/test_no_persist.py tests/review/test_privacy_no_frame_leak.py -q   # -> 5 passed
```

<!-- tests/service/test_no_persist.py; tests/review/test_privacy_no_frame_leak.py -->

## Who decides what

> **The vision pipeline measures, the code decides, the model only proposes.**

| Layer | What it owns |
|---|---|
| OpenCV pipeline (measures) | Face detection, 478-point mesh, eye/mouth aspect ratios, face scale, head yaw/pitch/roll + depth — numbers only, never a label |
| Rule policy / agent (decides) | Each frame: nudge / confirm / look-again / silent; suppresses during do-not-disturb, away, focus. Normal frames take the zero-cost rules path |
| LLM — Bedrock, optional (proposes) | May suggest a report sentence or ambiguous-frame action; whitelist + no-diagnosis guardrails and a latency budget fall back to rules. Never the last word |
| The person (final authority) | Explicit consent, always-visible camera indicator; on low confidence it asks yes/no, and a "no" raises that threshold and stops asking |

![Architecture](docs/diagrams/aws_architecture.png)

## What is agentic here

The vision result changes what the agent plans, which tools it calls, and when it asks a human. When quality is poor or confidence is borderline, the agent calls `second_look` (re-analyses the same in-memory frame with `enhance`, `zoom_face` or `strict`) *before* bothering anyone; a human "no" raises that behaviour's threshold and it persists. An optional Bedrock planner (Claude Haiku) can only propose; whitelist, no-diagnosis and length guardrails plus a timeout fall back to rules. The agent is **quiet by default**: nudges for the same posture are capped (≈20-min cooldown, ≤3/hour), confirm toasts ≤2/hour and never the same kind twice in a row, and a brief quality blip waits out a 30-s debounce — held alerts are counted in the report, not dropped ([`ALERT_CALMING.md`](docs/eval/ALERT_CALMING.md)).

![Agent workflow](docs/diagrams/agent_workflow_compact.png)

Evidence for the claims (traces, tests, reproduction commands): [`docs/submission/AGENTIC_VISION.md`](docs/submission/AGENTIC_VISION.md), full diagram [`docs/diagrams/agent_workflow.png`](docs/diagrams/agent_workflow.png).

## Run it locally (no AWS needed)

The hosted demo above needs no setup. To run the whole stack yourself:

```bash
scripts/run_local.sh      # uv environment, model download + checksum, service, web
scripts/test_all.sh       # vision + agent + service + e2e tests
```

The live review deployment is kept until 2026-11-10: see [`docs/cloud/ENDPOINT.md`](docs/cloud/ENDPOINT.md). Details, prerequisites and the AWS deployment procedure: [`docs/REPRODUCE.md`](docs/REPRODUCE.md), [`cloud/README.md`](cloud/README.md). Dependencies are pinned in `pyproject.toml` / `uv.lock` (OpenCV `opencv-python-headless==5.0.0.93`).

## Repository map

| path | what |
|---|---|
| `src/nunchi/vision` | OpenCV 5 pipeline: YuNet face detection, FaceMesh landmarks, quality checks, calibration, behaviour state machines, palm detector, head pose (`solvePnP`) for the posture buddy |
| `src/nunchi/agent` | decision loop, tools (`second_look` etc.), guardrails, optional Bedrock planner, image-free trace |
| `src/nunchi/service` | FastAPI service (HTTP API in `docs/CONTRACTS.md`), session state, metrics, rate limits |
| `web/` | static web app (Demo/Live modes, overlay, agent panel, report), Playwright e2e |
| `cloud/` | CloudFormation template, one-command deploy/destroy (dry-run by default), arm64 zip packaging |
| `eval/`, `docs/eval/` | evaluation harnesses and reports (vision, robustness, agent, web) |
| `models/` | model manifest with licences and SHA-256 (weights are downloaded, not committed) |
| `docs/report/TECHNICAL_REPORT.md` | technical report |

## Built / Measured / Not measured (honest)

| Status | What |
|---|---|
| **Built & measured** | 320 tests pass (`uv run pytest -q`); web e2e 87/87 + buddy unit 6/6, axe WCAG 2 A/AA 0 hard violations; engine analysis **~178–282 ms/frame** on real Graviton (stable ~178 ms within one warm host), cold Init ~2.5 s; frame non-storage proven by 5 counterexample tests. A synthetic 1-hour session shows calming cut interruptions **9 → 5** (first alert unchanged; first repeat nudge ~10 min later). ([`LATENCY.md`](docs/cloud/LATENCY.md), [`WEB_E2E.md`](docs/eval/WEB_E2E.md), [`ALERT_CALMING.md`](docs/eval/ALERT_CALMING.md)) |
| **Synthetic baseline** | Vision robustness is from public samples + synthetic transforms, **not** tuned on and **not** accuracy; head-pose error ~3–5° yaw/pitch, ~2–3° roll under jitter. A synthetic-geometry test rejects the typing/chin-rest `drink` false-positive paths (vertical + rise gate), not real-clip accuracy. ([`VISION_EVAL.md`](docs/eval/VISION_EVAL.md), [`DRINK_FEASIBILITY.md`](docs/eval/DRINK_FEASIBILITY.md)) |
| **Not measured** | Per-behaviour accuracy on real recorded clips; `drink` is a hand-position estimate (palm near mouth) so real-clip false/missed detections are unmeasured; the buddy's neck/torso/shoulders are **estimated** from head+hand, not measured body pose. ([`BODY_POSE_FEASIBILITY.md`](docs/eval/BODY_POSE_FEASIBILITY.md)) |
| **On hold** | Best Use of COOL (COOL is an AWS Marketplace AMI; this service is a Lambda zip). |

Blink is undercounted at ~2 fps, so we report an eyes-closed fraction and only claim sustained closure. The posture buddy tracks **relative change from the calibrated pose, not absolute angles** (approximate intrinsics/3D model); on-screen motion is amplified ~1.5× for readability. The multi-session comparison is keyed to an **anonymous per-browser id** — it does not follow you across browsers/devices, and a live non-"na" trend is proven only by a unit test. The alert-reduction figure is from a **synthetic** session, not real use. Agent evaluation uses deterministic stubs and scenarios written by us; failures are kept in the report.

License: MIT (code). Third-party model weights keep their own licences, see `models/MANIFEST.json`.

## Responsible use

Wellbeing coaching only: no medical diagnosis, no identification or recognition of people, no frame storage. The only stored data is aggregate numbers (no images/landmarks), keyed to an anonymous per-browser id for the multi-session comparison — no login, no personal identifiers, and nothing shared between users. See the privacy page in the web app and `docs/report/TECHNICAL_REPORT.md` section 8.

## Documents

[Architecture](docs/ARCHITECTURE.md) · [Contracts](docs/CONTRACTS.md) · [Decisions](docs/DECISIONS.md) · [Reproduce](docs/REPRODUCE.md) · [Independent review](docs/review/Q1_REPORT.md)
