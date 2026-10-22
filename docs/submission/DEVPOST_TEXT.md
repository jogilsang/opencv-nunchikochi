<!--
Devpost submission text for Nunchikochi (agent tab, A8).
Paste the sections below into the matching Devpost fields. HTML comments carry the
evidence path for every number; delete the comments before pasting if the field
strips them. Do NOT paste secrets, account ids, or API keys. Posture-buddy claim is
held at the end until it lands.
Word count (sections 1-10, excluding this comment, headings, tags, links): ~1,150.
-->

# 1. Tagline + short description

**Tagline** (<=80 chars):
Nunchikochi — a webcam coach that reads your posture and knows when to stay quiet.

**Short description** (~300 chars):
Nunchikochi watches your own desk habits through the laptop webcam with OpenCV 5 —
forward lean, head tilt, deep blinks, yawns, stepping away, forgetting to drink — and
an agent decides each frame whether to nudge, look again, or stay silent. Video is
never stored. "Nunchi" (눈치) is the Korean sense of reading a room; this reads you.

---

# 2. Inspiration — the problem and who it's for

People in long focused desk sessions drift into habits they never notice: leaning toward
the screen, a tilted head, long "deep" blinks, yawning, forgetting to drink water, or
stepping away. Each is a small cumulative ergonomic signal. Existing tools either ignore
them or over-correct with constant, context-blind alerts that users mute within a day.

Nunchikochi is for the individual knowledge worker who wants gentle, private
self-feedback on their own machine — not an employer dashboard, not a wellness score.
The hard problem is not detection; it is restraint. A signal is not a reason to
interrupt. The interesting question was **when to stay quiet** — which is why judgement
is a separate, testable agent rather than an if-statement on the detector.

---

# 3. What it does

Nunchikochi runs a perceive → decide → act loop on each webcam frame:

- **Six self-awareness signals** from OpenCV: forward lean (posture), head tilt,
  blink / sustained "deep" blink, yawn, stepping **away**, and hand-to-mouth **drink**
  reminders. <!-- src/nunchi/contracts.py BehaviorType; src/nunchi/vision -->
- **An agent decides, not a threshold.** Each frame it chooses to nudge, confirm with
  the person, re-analyse the same frame a different way ("look again"), or stay silent —
  suppressing nudges during do-not-disturb, when you are away, or in a focus block.
  <!-- src/nunchi/agent/policy.py; docs/eval/AGENT_EVAL.md -->
- **Human in the loop.** Before asking anything, OpenCV looks again (`second_look`); on
  a low-confidence signal it asks yes/no, and if you say a signal was wrong it raises
  its threshold so it stops asking.
  <!-- tests/agent/test_guardrails_deep.py::test_denial_raises_threshold_and_persists_across_frames -->
- **An end-of-session report** of aggregate habits (no video, no per-frame data),
  written with an optional Amazon Bedrock call and a template fallback.
- **On-screen, keyboard-first UI** with an explicit consent modal and an
  always-visible camera-on indicator. <!-- docs/eval/WEB_E2E.md -->
- **A posture buddy** — a pastel clay head avatar that mirrors your head pitch/yaw/roll
  and screen distance in real time (3-axis view, ghost of your calibrated pose, in-browser
  session rewind), driven by five numbers only (never an image).
  <!-- src/nunchi/vision/headpose.py; docs/CONTRACTS.md overlay.pose; docs/screenshots/w10-buddy-*.png -->

---

# 4. How we built it

**OpenCV 5 (all vision).** Pinned to `opencv-python-headless==5.0.0.93`, no external
inference framework. Face detection is YuNet via `cv2.FaceDetectorYN`; landmarks are a
478-point FaceMesh ONNX model through `cv2.dnn`; an optional MediaPipe palm ONNX
powers the hand-to-mouth "drink" cue (centre only, no skeleton). The posture buddy's
head yaw/pitch/roll + depth come from six Face Mesh points through **`cv2.solvePnP`**
(roll from the steadier eye-line metric). Eye- and mouth-aspect-ratio and face scale are
all OpenCV + NumPy. A deterministic largest-face picker stops a passer-by from hijacking
the frame. The agent's "look again" calls `analyze_variant` to re-read the *same* frame
with CLAHE + gamma, a face crop-and-zoom, or stricter thresholds — state is never mutated
by a variant. <!-- docs/report/TECHNICAL_REPORT.md §4; src/nunchi/vision/headpose.py -->

**AWS.** The workload runs on a single **AWS Lambda function, arm64 (Graviton),
Python 3.12** (FastAPI under Mangum) as a pip zip. Public traffic enters through
**Amazon API Gateway** → Lambda; the static web is **Amazon S3** (private) +
**Amazon CloudFront** (Origin Access Control); session state is **Amazon DynamoDB**
(on-demand, TTL) — aggregate numbers only, never images. The API key is an
**AWS Systems Manager** SecureString read at runtime, never in the repo/template/logs;
if unresolvable the service fails closed. **Amazon CloudWatch** Embedded Metric Format
emits numbers and bounded labels only (no image bytes, bodies, keys, or ids). The
optional report planner uses **Amazon Bedrock** (Claude Haiku-class).
<!-- docs/cloud/ENDPOINT.md; docs/report/TECHNICAL_REPORT.md §5 -->

**Agent design.** Perception (OpenCV) and judgement (agent) are separate components
joined only by a typed, image-free contract. The agent has seven tools, a guardrail
layer that rejects any LLM-proposed action/tool/argument outside a whitelist, and a
JSONL trace with no image data or coordinates. Normal frames take the zero-cost rules
path; Bedrock is called only on ambiguous moments, bounded by a per-frame latency
budget with a rules fallback. <!-- src/nunchi/agent/ -->

---

# 5. Why this is Agentic Vision

<!-- docs/submission/AGENTIC_VISION.md; docs/submission/traces/ -->
The **visual result changes the next decision, tool call, and approval request** —
shown as runnable traces, not slides:

- A dark frame → OpenCV `second_look(enhance)` clears it → decision flips to silent.
- Low confidence → `second_look(zoom_face)`; if still unsure, ask the human.
- An LLM proposing a forbidden action → guardrail rejects it → rules decide.
- A real Bedrock call over the frame budget (2.8 s) → rules fallback.
- A human "no" → the agent raises its threshold and stops asking.

Evidence: five demo traces (`docs/submission/traces/`), a workflow spec
(`docs/diagrams/AGENT_WORKFLOW_SPEC.md`), and 22 deterministic + 9 adversarial scenarios
— every workflow branch mapped to a trace or test.

---

# 6. Challenges we ran into

- **An org SCP blocked our public endpoint.** The Lambda Function URL (AuthType NONE)
  was denied (403) by an organization Service Control Policy. We swapped the public entry
  point to an API Gateway HTTP API (same stack, region, tags) and health checks returned
  200. <!-- docs/cloud/ENDPOINT.md -->
- **A state-restore defect, caught by e2e before deploy.** End-to-end checks surfaced two
  mismatches in how session state restored across Lambda instances; we fixed them before
  the real deploy, not in production. <!-- docs/STATUS.md 지휘자 검증 row -->
- **Blink is hard at ~2 fps.** A 200 ms blink often falls between frames, so single-frame
  counting undercounts. We report a PERCLOS-like eyes-closed fraction and only claim
  sustained closure (deep blink). <!-- docs/report/TECHNICAL_REPORT.md §7 -->
- **Synthetic evaluation is not real-world evaluation.** Robustness numbers come from
  public samples + synthetic transforms; we did not tune thresholds on them or present
  them as accuracy. Real-clip accuracy is still pending.

---

# 7. Accomplishments / what we learned

- **286 automated tests pass** across vision, agent, cloud, and web, including a test
  that proves frames are never persisted. <!-- `uv run pytest tests -q` = 286 passed, 2026-10-22 -->
- **Measured on real AWS Graviton**, not just a laptop: the per-frame OpenCV analysis is
  **~178–282 ms depending on the execution host** (stable ~178 ms within one warm host),
  with a **~2.5 s median cold-start Init**. We A/B-tested on Lambda and cleared head pose
  (+1.6 ms) and thread count as causes; the honest conclusion is a host-variance *range*,
  not a single headline number. <!-- docs/cloud/LATENCY.md C8/C10/C11; docs/eval/LATENCY_REGRESSION.md -->
- **Estimated ~$1–2/month** at demo scale (~50k frames), idle ≈ $0 — all usage-priced,
  no NAT, no provisioned capacity, with a $20 budget alarm as backstop.
  <!-- docs/report/TECHNICAL_REPORT.md §5; cloud/README.md -->
- **Web is accessible**: Playwright e2e 27/27 and axe-core WCAG 2 A/AA scans with 0 hard
  violations. <!-- docs/eval/WEB_E2E.md -->
- We learned that the honest version of "smart" is a system that knows the limits of its
  own perception and asks — and that separating OpenCV from the agent made both
  independently testable.

---

# 8. Responsible use & privacy

- **No video, ever stored.** A test uploads a JPEG with a unique marker and asserts it
  appears in no new file, no debug log, and no response — raw, hex, or base64.
  <!-- tests/service/test_no_persist.py -->
- **Not a diagnosis.** The tool reports observations ("your head has been tilted for a
  while"), never a state or health claim. A deterministic no-diagnosis guardrail blocks
  such phrasings in English and Korean and is covered by tests.
  <!-- src/nunchi/agent/guardrails.py; tests/agent/test_guardrails_deep.py -->
- **No identification.** No face recognition, single-user only, not a multi-person
  monitor. Consent is explicit and the camera-on state is always visible.
- Traces carry no image data or coordinates; only aggregate numbers go to DynamoDB
  under a TTL.

---

# 9. Limitations (honest)

- **Real-clip vision accuracy is not yet measured** — recorded-clip evaluation pending;
  robustness numbers are synthetic (public samples + transforms) and do not generalise.
  <!-- docs/eval/VISION_EVAL.md; docs/report/TECHNICAL_REPORT.md §7 -->
- **`drink` is conditional**: implemented via an OpenCV palm ONNX model, emitted only
  when that optional model file is present.
- **The posture buddy tracks relative change, not absolute angles.** Intrinsics and the
  3D model are approximations (synthetic-rotation error ~3–5° yaw/pitch, ~2–3° roll under
  jitter; real-clip angle accuracy unmeasured); on-screen motion is amplified ~1.5× for
  readability (shown in the UI). Shoulder/body pose is not implemented (model-size budget).
  <!-- docs/eval/VISION_EVAL.md §6; docs/eval/BODY_POSE_FEASIBILITY.md -->
- **Blink is undercounted at low fps** (see Challenges); we report deep blinks instead.
- **Agent evaluation is stub-based** (deterministic vision/LLM stubs, self-written
  scenarios) — 100% means specification conformance, not a generalisation claim. LLM
  metrics are smoke-level.
- **Deployment numbers are one small run** (single region/client, one sample image);
  monthly cost is an estimate from public pricing, not a bill.

---

# 10. What's next

- Record real clips and publish per-behaviour precision/recall/F1 by lighting.
- Extend the posture buddy from head-only to shoulders/torso once an int8 body-pose model
  is verified under `cv2.dnn` and fits the model-size budget
  (`docs/eval/BODY_POSE_FEASIBILITY.md`).
- Tune thresholds on real data instead of conservative starting values.
- Optional multi-session trends while keeping the no-video, single-user guarantees.

---

# 11. Built with

opencv · python · aws-lambda · aws-graviton · amazon-api-gateway · amazon-cloudfront ·
amazon-s3 · amazon-dynamodb · aws-systems-manager · amazon-cloudwatch · amazon-bedrock ·
fastapi · mangum · javascript · onnx · numpy

<!-- All tags are facts: Lambda arm64 (Graviton), API Gateway HTTP API, CloudFront+S3,
DynamoDB, SSM SecureString, CloudWatch EMF, Bedrock (report path), FastAPI+Mangum,
vanilla JS web, ONNX models via cv2.dnn, NumPy. No tag for a service we do not use. -->

---

# 12. Try it out

- **Code**: https://github.com/jogilsang/opencv-nunchikochi
- **Live web**: https://dhys8dgxlvbgx.cloudfront.net
  <!-- docs/cloud/ENDPOINT.md CloudFront; kept until 2026-11-10 then destroyed -->
- **API key for the live demo**: `[ASK USER]`
  <!-- app-level X-Api-Key in SSM SecureString /nunchi/api-key — never in this repo -->

# 13. Video

`[USER: add after upload]`
