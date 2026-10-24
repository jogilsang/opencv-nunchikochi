<!--
Devpost submission text for Nunchikochi (agent tab, A10 = v2).
v2 reorders to the winning-entry shape (meta block -> try-it -> one scene -> one
headline number + reproduction -> who-decides-what -> product -> build -> limits).
Paste the sections below into the matching Devpost fields. HTML comments carry the
evidence path for every number; delete the comments before pasting if the field
strips them. Do NOT paste secrets, account ids, or API keys.
Word count (sections 1-13, excluding this comment, headings, tags, links): ~1,180.
-->

# 0. Meta block (put at the very top of the project page)

- **Theme**: self-awareness coaching with OpenCV 5 on AWS
- **Special prize**: Agentic Vision
- **Live (no key needed)**: https://dhys8dgxlvbgx.cloudfront.net/?demo=1
- **Code**: https://github.com/jogilsang/opencv-nunchikochi
- **Built with**: OpenCV 5 · AWS Lambda (Graviton/arm64) · API Gateway · CloudFront+S3 · DynamoDB · Bedrock · FastAPI · ONNX · NumPy · JavaScript

---

# 1. Try it in one minute (judges, start here)

Open **https://dhys8dgxlvbgx.cloudfront.net/?demo=1** — no camera, no key, no sign-up.
A short recorded session plays automatically (a 60–90 s window; "Skip to report" ends
it on demand). <!-- docs/eval/WEB_E2E.md W13 row "60–90s window"; web/app.js ?demo -->

Three things to watch:
1. the **overlay** drawing the detected face landmarks and behaviours,
2. the **posture buddy** — a clay upper-body avatar that mirrors your head angle and
   screen distance (head + drink are measured; neck/torso are estimated and the UI says so),
3. the **agent activity panel** listing each frame's decision (nudge / confirm / look
   again / stay silent). <!-- docs/eval/WEB_E2E.md core-flow + posture-buddy rows -->

**Live mode** (your own webcam) needs an access key supplied with the submission note;
everything that matters is visible in demo mode without it.

---

# 2. One desk, 2:40 PM (an illustrative day — not a real user)

It's 2:40 PM and Mina has been heads-down for two hours. Her head has drifted toward the
screen, her chin is dropping, and her blinks are getting longer and slower. She doesn't
notice any of it — that's the point of a habit. A blunt tool would have buzzed her
twelve times by now and she'd have muted it before lunch.

**Nunchikochi** watches her own desk habits through the laptop webcam with OpenCV 5 —
forward lean, head tilt, deep blinks, yawns, stepping away, forgetting to drink — and an
agent decides *each frame* whether to nudge, look again, or **stay quiet**. The video is
never stored. "Nunchi" (눈치) is the Korean sense of reading a room; this reads you.

---

# 3. The number that is the product

**You can send a frame, and it leaves no trace — proven by a counterexample, not a
promise.** A test uploads a JPEG carrying a unique marker, runs it through the live
perceive→decide path, then searches every surface the frame could leak into — new files
on disk, every captured log line, the persisted DynamoDB session state, the CloudWatch
EMF metric stream, and the `/v1/trace` response — in raw, hex, **and** base64. The
marker is found **0 times across all five surfaces**; 5 counterexample tests pass.
<!-- tests/service/test_no_persist.py; tests/review/test_privacy_no_frame_leak.py -->

Reproduce it:

```bash
uv run --group service --group dev pytest \
  tests/service/test_no_persist.py tests/review/test_privacy_no_frame_leak.py -q
# -> 5 passed
```

Restraint is measured too: across the agent harness, `second_look` (OpenCV re-reading the
same frame) **changed the decision in 3 of 7 ambiguous moments (42.9%)** — e.g. a dark
frame cleared to "stay silent", or a low-confidence signal that zoomed in and dismissed
itself instead of interrupting. (Stub-driven; see Limitations.)
<!-- docs/eval/AGENT_EVAL.md "second_look 후 결정 변경 비율 3/7" -->

---

# 4. Who decides what

> **The vision pipeline measures, the code decides, the model only proposes.**

| Layer | What it owns |
|---|---|
| **OpenCV pipeline** (measures) | Face detection, 478-point mesh, eye/mouth aspect ratios, face scale, head yaw/pitch/roll + depth. Produces numbers only — never a decision, never a label. <!-- src/nunchi/vision --> |
| **Rule policy / agent** (decides) | Every frame picks nudge / confirm / look-again / silent; suppresses during do-not-disturb, away, or focus blocks. Normal frames take the zero-cost rules path. <!-- src/nunchi/agent/policy.py --> |
| **LLM — Bedrock, optional** (proposes only) | May *suggest* a report sentence or an ambiguous-frame action. A whitelist guardrail rejects any action/tool/argument outside the allowed set; a no-diagnosis guardrail blocks health claims; a latency budget falls back to rules. The model never has the last word. <!-- src/nunchi/agent/guardrails.py --> |
| **The person** (final authority) | Consent is explicit; the camera-on state is always visible. On low confidence the agent asks yes/no, and **if you say a signal was wrong it raises that threshold and stops asking**. <!-- tests/agent/test_guardrails_deep.py::test_denial_raises_threshold_and_persists_across_frames --> |

---

# 5. What it does

- **Six self-awareness signals** from OpenCV: forward lean, head tilt, blink / sustained
  "deep" blink, yawn, stepping **away**, and a hand-to-mouth **drink** reminder.
  <!-- src/nunchi/contracts.py BehaviorType -->
- **An agent decides, not a threshold** — nudge, confirm, re-analyse the same frame a
  different way ("look again"), or stay silent.
- **An end-of-session report** of aggregate habits only (no video, no per-frame data),
  written by an optional Bedrock call with a template fallback.
- **A posture buddy** avatar mirroring head pitch/yaw/roll and screen distance in real
  time, driven by five numbers only — never an image.
  <!-- src/nunchi/vision/headpose.py; docs/CONTRACTS.md overlay.pose -->
- **Keyboard-first, accessible web UI** with an explicit consent modal.

---

# 6. How we built it (short)

**OpenCV 5 does all vision**, pinned to `opencv-python-headless==5.0.0.93`, no external
inference framework: YuNet face detection (`cv2.FaceDetectorYN`), a 478-point FaceMesh
ONNX model via `cv2.dnn`, an optional palm ONNX for the "drink" cue, and head
yaw/pitch/roll from six mesh points through **`cv2.solvePnP`** (roll from the steadier
eye-line metric). A deterministic largest-face picker stops a passer-by hijacking the
frame. <!-- docs/report/TECHNICAL_REPORT.md §4 -->

**On AWS**, the workload is a single **Lambda on arm64 (Graviton), Python 3.12** (FastAPI
under Mangum); **API Gateway** fronts it, **S3 + CloudFront (OAC)** serve the static web,
**DynamoDB** (on-demand, TTL) holds aggregate numbers only, the API key lives in **SSM**
SecureString (fail-closed), and **CloudWatch EMF** emits numbers and bounded labels only.
The optional report planner uses **Bedrock** (Claude Haiku-class).
<!-- docs/cloud/ENDPOINT.md; docs/report/TECHNICAL_REPORT.md §5 -->

**One build note (this is a coding-agent hackathon):** perception and judgement were
built as separate components joined only by a typed, image-free contract, developed in
parallel tabs with an independent reviewer tab that may not touch source — which is why
each half is testable on its own.

---

# 7. Why this is Agentic Vision

The **visual result changes the next decision, tool call, and approval request** — shown
as runnable traces, not slides: a dark frame cleared by `second_look` flips to silent; a
low-confidence signal zooms in and, if still unsure, asks the human; a forbidden LLM
action is rejected and rules decide; a real Bedrock call over the 2.8 s budget falls back
to rules; a human "no" raises the threshold. Evidence: five demo traces
(`docs/submission/traces/`), a workflow spec, and 22 deterministic + 9 adversarial
scenarios — every branch mapped to a trace or test.
<!-- docs/submission/AGENTIC_VISION.md -->

---

# 8. Built / Measured / Not measured (honest)

| Status | What |
|---|---|
| **Built & measured** | 286 automated tests pass (`uv run pytest tests -q`); web e2e 60/60 + buddy unit 6/6, axe WCAG 2 A/AA with 0 hard violations; per-frame OpenCV **~178–282 ms** on real Graviton (stable ~178 ms within one warm host), ~2.5 s cold Init; frame non-storage proven by the 5 counterexample tests above. <!-- docs/eval/WEB_E2E.md; docs/cloud/LATENCY.md; tests/service/test_no_persist.py --> |
| **Synthetic baseline** | Vision robustness is from public sample images + synthetic transforms; thresholds were **not** tuned on them and these are **not** accuracy. Synthetic head-pose error ~3–5° yaw/pitch, ~2–3° roll under jitter. <!-- docs/eval/VISION_EVAL.md §6 --> |
| **Not measured** | Per-behaviour accuracy on real recorded clips; `drink` validation on real clips; the buddy's neck/torso/shoulders are **estimated** from head+hand, not measured body pose. <!-- docs/eval/BODY_POSE_FEASIBILITY.md --> |
| **On hold** | Best Use of COOL (COOL is an AWS Marketplace AMI; this service is a Lambda zip). |

Blink is undercounted at ~2 fps (a 200 ms blink falls between frames), so we report a
PERCLOS-like eyes-closed fraction and only claim sustained closure. Agent evaluation is
stub-based: 100% means specification conformance, not generalisation; LLM metrics are
smoke-level. Cost **~$1–2/month** at demo scale (~50k frames), idle ≈ $0, is an estimate
from public pricing with a $20 budget alarm — not a bill.
<!-- docs/report/TECHNICAL_REPORT.md §5,§7 -->

---

# 9. Challenges we ran into

- **An org SCP blocked our public endpoint.** The Lambda Function URL (AuthType NONE) was
  denied (403) by an organization Service Control Policy; we swapped the public entry
  point to an API Gateway HTTP API (same stack/region/tags) and health checks returned 200.
  <!-- docs/cloud/ENDPOINT.md -->
- **A state-restore defect, caught by e2e before deploy**, in how session state restored
  across Lambda instances — fixed before the real deploy, not in production.
- **A single latency number was a lie.** The warm per-frame time swung ~178↔282 ms between
  runs; we A/B-tested on Lambda, cleared head pose (+1.6 ms) and thread count as causes,
  and now report a host-variance *range*. <!-- docs/cloud/LATENCY.md; docs/eval/LATENCY_REGRESSION.md -->

---

# 10. What's next

- Record real clips and publish per-behaviour precision/recall/F1 by lighting.
- Replace the buddy's estimated neck/torso with a real int8 body-pose model once it is
  verified under `cv2.dnn` and fits the model-size budget.
  <!-- docs/eval/BODY_POSE_FEASIBILITY.md -->
- Tune thresholds on real data instead of conservative starting values.

---

# 11. Responsible use & privacy

No video ever stored (proven above); not a diagnosis (a deterministic no-diagnosis
guardrail blocks health claims in English and Korean); no face recognition, single-user
only. Traces carry no image data or coordinates; only aggregate numbers go to DynamoDB
under a TTL. <!-- src/nunchi/agent/guardrails.py; tests/service/test_no_persist.py -->

---

# 12. Built with (tags)

opencv · python · aws-lambda · aws-graviton · amazon-api-gateway · amazon-cloudfront ·
amazon-s3 · amazon-dynamodb · aws-systems-manager · amazon-cloudwatch · amazon-bedrock ·
fastapi · mangum · javascript · onnx · numpy

---

# 13. Links

- **Code**: https://github.com/jogilsang/opencv-nunchikochi
- **Live demo (no key)**: https://dhys8dgxlvbgx.cloudfront.net/?demo=1
  <!-- docs/cloud/ENDPOINT.md CloudFront; kept until 2026-11-10 then destroyed -->
- **API key for Live mode**: `[ASK USER — supply in submission note, never in repo]`
- **Video**: `[USER: add after upload]`
