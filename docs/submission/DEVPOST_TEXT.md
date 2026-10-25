<!--
Devpost submission text for Nunchikochi (agent tab, A15 = v5).
v5 keeps the readable length (target 1,400–1,550 words, comments excluded) and syncs to
the current build: 361 Python tests, web e2e 97/97; the posture buddy is now a FACE + NECK
figure (no body); Live mode is unlocked by a one-button 30-minute trial key issued from the
page itself (no shared key passed to judges). Structure unchanged: meta -> try-it -> one
scene -> headline number -> who-decides -> product -> build -> limits.
Paste the sections below into the matching Devpost fields. HTML comments carry the
evidence path for every number; delete the comments before pasting if the field
strips them. Do NOT paste secrets, account ids, or API keys.
-->

# 0. Meta block (top of the project page)

- **Theme**: self-awareness coaching with OpenCV 5 on AWS
- **Special prize**: Agentic Vision
- **Live (no key needed)**: https://dhys8dgxlvbgx.cloudfront.net/?demo=1
- **Code**: https://github.com/jogilsang/opencv-nunchikochi
- **Built with**: OpenCV 5 · AWS Lambda (Graviton/arm64) · API Gateway · CloudFront+S3 · DynamoDB · Bedrock · FastAPI · ONNX · NumPy · JavaScript

---

# 1. Try it in one minute (judges, start here)

Open **https://dhys8dgxlvbgx.cloudfront.net/?demo=1** — no camera or key needed.
A short recorded session plays (a 60–90 s window; "Skip to report" ends it).
<!-- docs/eval/WEB_E2E.md W13 row "60–90s window"; web/app.js ?demo -->

Three things to watch:
1. the **overlay** drawing the detected landmarks and behaviours,
2. the **posture buddy** — a clay **face + neck** mirroring your head angle and facial
   movement (head pose + expression measured; neck a labelled estimate, no body; a measured
   sip shows a small cup at the mouth),
3. the **agent activity panel** — each frame's nudge / confirm / look-again / silent
   decision, **quiet mode on by default** (posture still recorded, alerts held and counted).
   <!-- web/app.js quiet:true (W16); docs/eval/WEB_E2E.md -->

**Live mode** (your own webcam) needs no shared key: pick Live and press **"Get a trial
key (30 min)"** on the page — one click issues a 30-minute key (same IP 3×/day, 6/day
across the service; if used up, key-free demo mode still shows everything that matters).
<!-- web/index.html #btn-trial-key; cloud/template.yaml NUNCHI_KEY_IP_DAILY=3, NUNCHI_KEY_GLOBAL_DAILY=6 -->

---

# 2. One desk, 2:40 PM (an illustrative day — not a real user)

It's 2:40 PM and Mina has been heads-down for two hours — head drifting toward the screen,
chin dropping, blinks slowing — and she notices none of it, because that's what a habit is.
A blunt tool would have buzzed her a dozen times and been muted before lunch.

**Nunchikochi** reads your own desk habits through the laptop webcam with OpenCV 5 —
forward lean, head tilt, deep blinks, yawns, stepping away, forgetting to drink — and an
agent decides *each frame* whether to nudge, look again, or **stay quiet**. The video is
never stored. "Nunchi" (눈치) is the Korean sense of reading a room; this reads you.---

# 3. The number that is the product

**You can send a frame, and it leaves no trace — proven by a counterexample, not a
promise.** A test uploads a JPEG with a unique marker, runs the live perceive→decide path,
then searches every surface it could leak into — files, logs, the DynamoDB state, the
CloudWatch EMF stream, and the `/v1/trace` response — in raw, hex, **and** base64. The
marker is found **0 times across all five surfaces**; 5 counterexample tests pass
(`test_no_persist.py` + `test_privacy_no_frame_leak.py`).
<!-- tests/service/test_no_persist.py; tests/review/test_privacy_no_frame_leak.py -->

Restraint is measured too: in the agent harness, `second_look` (OpenCV re-reading the same
frame) **changed the decision in 3 of 7 ambiguous moments** — a dark frame cleared to
silent, a low-confidence signal zoomed in and dismissed itself. (Stub-driven; see
Limitations.) <!-- docs/eval/AGENT_EVAL.md "second_look 후 결정 변경 비율 3/7" -->

---

# 4. Who decides what

> **The vision pipeline measures, the code decides, the model only proposes.**

| Layer | What it owns |
|---|---|
| **OpenCV pipeline** (measures) | Face detect, 478-point mesh, eye/mouth ratios, face scale, head yaw/pitch/roll + depth. Numbers only, never a decision. <!-- src/nunchi/vision --> |
| **Rule policy / agent** (decides) | Each frame: nudge / confirm / look-again / silent; suppresses on do-not-disturb, away, focus. Normal frames take the zero-cost rules path. <!-- src/nunchi/agent/policy.py --> |
| **LLM — Bedrock, optional** (proposes) | May suggest a report sentence or an action; a whitelist + no-diagnosis guardrail and a latency budget fall back to rules. Never the last word. <!-- src/nunchi/agent/guardrails.py --> |
| **The person** (final authority) | Explicit consent, camera-on visible; on low confidence it asks yes/no, and **a "no" raises that threshold and stops asking**. <!-- tests/agent/test_guardrails_deep.py --> |

---

# 5. What it does

- **Six self-awareness signals** from OpenCV: forward lean, head tilt, blink / sustained
  "deep" blink, yawn, stepping **away**, and a **drink** cue.
  <!-- src/nunchi/contracts.py BehaviorType -->
- **An agent decides, not a threshold** — nudge, confirm, "look again", or stay silent.
- **Quiet by default, and quieter on purpose.** Nudges for the same posture are capped
  (≈20-min cooldown, ≤3/hour), confirm toasts are rare (≤2/hour, no same kind in a row),
  and a brief quality blip waits out a 30-s debounce. Held alerts are counted, not dropped.
  <!-- src/nunchi/agent/policy.py; docs/eval/ALERT_CALMING.md -->
- **A posture record you can track.** The end-of-session report (aggregate habits only, no
  video; optional Bedrock with a template fallback) buckets bad posture into 5 / 10 / 30 /
  60-minute windows and, at 10+ minutes, an hour-rate plus an improving / same / worsening
  trend vs recent sessions — anonymous per-browser id, numbers only.
  <!-- src/nunchi/agent/summary.py; docs/eval/timeline_sample.json -->
- **A posture buddy** avatar — a **face + neck** mirroring your head angle, distance, and
  facial movement from numbers only (never an image); the neck is a labelled estimate, no
  body drawn. <!-- src/nunchi/vision/headpose.py; web/buddy-kinematics.js; docs/CONTRACTS.md overlay.pose -->
- **Keyboard-first, accessible web UI** with an explicit consent modal.

---

# 6. How we built it (short)

**OpenCV 5 does all vision**, pinned to `opencv-python-headless==5.0.0.93`, no external
inference framework: YuNet face detection, a 478-point FaceMesh ONNX via `cv2.dnn`, an
optional palm ONNX for the "drink" cue, and head yaw/pitch/roll from six mesh points via
**`cv2.solvePnP`**. <!-- docs/report/TECHNICAL_REPORT.md §4 -->

**On AWS** it is one **Lambda on arm64 (Graviton)** behind **API Gateway**; **S3 +
CloudFront (OAC)** serve the web, **DynamoDB** (TTL) holds aggregate numbers only, the API
key is an **SSM** SecureString (fail-closed), **CloudWatch EMF** emits numbers only, and
the optional report planner uses **Bedrock**. <!-- docs/cloud/ENDPOINT.md; docs/report/TECHNICAL_REPORT.md §5 -->

**Build note (coding-agent hackathon):** perception and judgement are separate components
joined only by a typed, image-free contract — so each half is testable on its own.

---

# 7. Why this is Agentic Vision

The **visual result changes the next decision, tool call, and approval request** — shown
as runnable traces, not slides: `second_look` flips a dark frame to silent; a low-confidence
signal zooms in and, if still unsure, asks the human; a forbidden LLM action is rejected and
rules decide; an over-budget Bedrock call falls back to rules; a human "no" raises the
threshold. Evidence: five demo traces, a workflow spec, and 22 deterministic + 9 adversarial
scenarios — every branch mapped to a trace or test.
<!-- docs/submission/AGENTIC_VISION.md -->

---

# 8. Built / Measured / Not measured (honest)

| Status | What |
|---|---|
| **Built & measured** | 361 Python tests pass (`uv run pytest -q`); web e2e 97/97 + buddy unit 7/7, axe WCAG 2 A/AA 0 hard violations; per-frame OpenCV **~178–282 ms** on real Graviton (~178 ms per warm host), ~2.5 s cold Init; frame non-storage proven by the 5 tests above; a synthetic 1-hour session cut interruptions **9 → 5**. <!-- uv run pytest -q = 361; docs/eval/WEB_E2E.md 97/97 + buddy 7/7; docs/cloud/LATENCY.md; docs/eval/ALERT_CALMING.md --> |
| **Synthetic baseline** | Vision robustness = public samples + synthetic transforms (**not** tuned, **not** accuracy); head-pose error ~3–5° yaw/pitch, ~2–3° roll; typing/chin-rest `drink` false-positive paths rejected by a synthetic vertical+rise gate. <!-- docs/eval/VISION_EVAL.md §6; docs/eval/DRINK_FEASIBILITY.md §6-7 --> |
| **Not measured** | Real-clip accuracy; `drink` is a hand-position estimate (palm near mouth), so real-clip false/missed detections are unmeasured; the buddy's neck is **estimated** from the measured head angles, not measured body pose, and no body is drawn. <!-- docs/eval/DRINK_FEASIBILITY.md §8; docs/eval/BODY_POSE_FEASIBILITY.md --> |
| **On hold** | Best Use of COOL (an AWS Marketplace AMI; this service is a Lambda zip). |

Blink is undercounted at ~2 fps, so we report an eyes-closed fraction and only claim
sustained closure. The multi-session comparison is keyed to an **anonymous per-browser
id** — it does not follow you across browsers or devices, and a live non-"na" trend is
proven only by a unit test. The alert-reduction figure is synthetic; agent evaluation is
stub-based. Cost **~$1–2/month** at demo scale, idle ≈ $0, is a public-pricing estimate — not a bill.
<!-- docs/eval/ALERT_CALMING.md; docs/CONTRACTS.md §4; docs/report/TECHNICAL_REPORT.md §5,§7 -->

---

# 9. Challenges we ran into

- **An org SCP blocked our public endpoint.** The Lambda Function URL (AuthType NONE) was
  denied (403) by an org SCP; we swapped to API Gateway HTTP API and health returned 200.
  <!-- docs/cloud/ENDPOINT.md -->
- **A state-restore defect, caught by e2e before deploy** — session state restored wrong
  across Lambda instances; fixed before deploy.
- **A single latency number was a lie.** Warm per-frame time swung ~178↔282 ms; A/B tests
  cleared head pose (+1.6 ms), so we report a host-variance range.
  <!-- docs/cloud/LATENCY.md; docs/eval/LATENCY_REGRESSION.md -->

---

# 10. What's next

- Record real clips, publish per-behaviour precision/recall/F1 by lighting, and validate
  the `drink` cue on real footage.
- Replace the buddy's estimated neck with a real int8 body-pose model within the model-size
  budget. <!-- docs/eval/BODY_POSE_FEASIBILITY.md -->
- Tune thresholds on real sessions and confirm the multi-session trend on real data.

---

# 11. Responsible use & privacy

No video stored (proven above); not a diagnosis (a deterministic guardrail blocks health
claims in English and Korean); no face recognition, single-user only. Traces carry no
image data or coordinates; only aggregate numbers go to DynamoDB under a TTL. The Live-mode
trial key is issued per request from the page (no shared key); its per-IP 3/day limit uses
only a **keyed hash** of the IP kept 48 hours — the raw IP is never stored and is removed
from access logs. Keys are capped at 6/day total, so they can run out; demo mode needs none.
<!-- src/nunchi/agent/guardrails.py; tests/service/test_no_persist.py; cloud/template.yaml §5 privacy -->

---

# 12. Built with (tags)

opencv · python · aws-lambda · aws-graviton · amazon-api-gateway · amazon-cloudfront ·
amazon-s3 · amazon-dynamodb · aws-systems-manager · amazon-cloudwatch · amazon-bedrock ·
fastapi · mangum · javascript · onnx · numpy
<!-- same as the meta "Built with" line; paste into Devpost's Built-with field -->

---

# 13. Links

- **Code**: https://github.com/jogilsang/opencv-nunchikochi
- **Live demo (no key)**: https://dhys8dgxlvbgx.cloudfront.net/?demo=1
  <!-- docs/cloud/ENDPOINT.md CloudFront; kept until 2026-11-10 -->
- **Live mode**: same URL → pick Live → "Get a trial key (30 min)" (no shared key; 3/day per IP, 6/day total)
- **Video**: `[USER: add after upload]`
