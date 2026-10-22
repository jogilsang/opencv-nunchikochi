# Demo video script — Nunchikochi (≤ 5 min)

Owner: web tab (W7). Target length **~4 min 30 s** (hard cap 5:00). English narration is
primary; Korean notes (KO) are production hints, not spoken.

**Grounding rule.** Every spoken claim is backed by a repo file or a measured number.
Where a number isn't measured yet it is written `[PENDING: …]` — do **not** read a
`[PENDING]` aloud; either drop the sentence or record it once the number lands.
Sources are listed per section. No real face is required on screen except the optional
user-presence shots (clearly marked **[USER]**).

**Honesty guardrails for the narration**
- Vision per-behaviour accuracy (P/R/F1) is **not measured yet** — do NOT state accuracy
  percentages. Speak about *what the pipeline computes*, not how accurate it is.
- "Drink" (cup/bottle toward the mouth) is **implemented conservatively** via a palm
  detector (hand-to-mouth proximity, optional model) and is **not yet validated on real
  clips** — if mentioned at all, say exactly that; never claim it works well.
- Graviton latency/cold-start is `[PENDING]`; the only latency we may state is the local
  Apple-Silicon dev number, and only if labelled as such.

Legend: **[USER]** = optional on-camera/voice by the user (they decide — U5). **[SCREEN]** =
screen capture (demo or local-live, fake camera). **[DIAGRAM]** = architecture diagram
(conductor-provided; placeholder until then).

---

## Section 1 — Problem & who it's for · ~30 s · [USER] optional
**Narration (EN):**
> "We sit at our desks for hours and slowly creep toward the screen — head forward,
> shoulders tight — and never notice until it hurts. Nunchikochi is a calm desk coach that
> reads posture and fatigue cues from your webcam — never who you are, and it never keeps
> the frames — and nudges you only when it matters."

KO 메모: 사용자가 직접 출연해 말해도 좋음(팀/사람 요건 충족). 카메라 없이 보이스오버만도 가능.
얼굴 랜드마크로 자세·피로(깜빡임·하품) 신호를 계산하되 신원 식별·인식은 하지 않음, 프레임은 저장 안 함.
[SCREEN] Start screen (`demo-01-start.png`) behind the voice.
Sources: `docs/report/TECHNICAL_REPORT.md` §1 (problem, intended users); landmark-derived
signals = `nunchi.vision`; no-persist test `tests/test_no_persist.py`.

## Section 2 — The app & the privacy promise · ~30 s · [SCREEN]
**Narration (EN):**
> "Here's the whole app. One promise up front: each frame is analysed in memory on AWS
> and discarded immediately — never recorded, never stored. Only aggregate numbers — counts
> and seconds — are kept for your daily report. It's a wellbeing nudge, not a diagnosis."

KO 메모: 시작 화면의 동의 문구와 Privacy 모달을 함께 보여 줌. "프레임 비저장"은 과장 아님(테스트가 증명).
[SCREEN] Start consent (`demo-01-start.png`) → Privacy modal (`demo-08-privacy.png`).
Sources: consent copy in `web/i18n.js`; no-persist test `tests/test_no_persist.py`
(referenced in `docs/CONTRACTS.md` §3); privacy modal.

## Section 3 — Live demo: calibrate → overlay → nudge · ~60 s · [SCREEN]
**Narration (EN):**
> "Pick Live mode, allow the camera, and it spends five seconds learning your neutral
> posture. Then it runs. Turn on 'what OpenCV sees' and you get the face box and landmark
> points — only coordinates, no image leaves the view. Lean in and hold it, and a gentle
> nudge appears: 'sit back a little.' Two at most, so it never buries the live metrics."

KO 메모: 모드 선택(`live-02`) → 보정(`demo-02`) → 오버레이(`demo-03`) → 넛지 토스트(`demo-05`).
라이브는 가짜 카메라 녹화(`live-03`)로 대체 가능. 실제 웹캠 시연은 사용자 녹화(USER_RECORDING_GUIDE).
[SCREEN] `live-02-connected-ready.png` → `demo-02-calibrate.png` → `demo-03-run-overlay.png`
→ `demo-05-run-toast.png` (or motion from `record_demo.mjs`).
Sources: overlay = `web/overlay.js` (coords only); nudge cap = `web/app.js` (MAX_TOASTS=2);
toast behaviour verified in `docs/eval/WEB_E2E.md`.

## Section 4 — What OpenCV 5 actually does · ~40 s · [SCREEN/DIAGRAM]
**Narration (EN):**
> "Under the overlay, OpenCV 5 runs the whole vision path: it detects the face, finds
> landmarks, and derives three signals — eye-openness, head tilt, and how close you are.
> It also scores image quality, and when quality is poor it can take a second look —
> re-analysing an enhanced or zoomed variant before anyone is bothered."

KO 메모: 지표 카드(EAR·HEAD TILT·FACE DISTANCE)와 품질 스켈레톤(`demo-04`)을 보여 줌.
정확도 수치는 말하지 않는다(미측정). "무엇을 계산하는지"만.
[SCREEN] `demo-03-run-overlay.png`, `demo-04-run-skeleton.png`.
Sources: `nunchi.vision` (face detect, landmarks, metrics, quality, `analyze_variant`) per
`docs/report/TECHNICAL_REPORT.md` §4; OpenCV pinned `opencv-python-headless==5.0.0.93`.
[PENDING: per-behaviour P/R/F1 — unmeasured in `docs/eval/VISION_EVAL.md`; do not claim accuracy.]

## Section 5 — The agent: when the view changes the decision · ~50 s · [SCREEN]
**Narration (EN):**
> "This is the Agentic Vision part. The coach doesn't act on a single frame. When it's
> uncertain, it asks OpenCV to look again — and that result changes the plan. If the second
> look clears things up, it stays quiet. If it's still unsure, it asks *you* a yes/no — and
> you're always in control. Everything the model suggests passes a guardrail; anything
> off-list is rejected and the rules decide instead."

KO 메모: 에이전트 활동 패널(`demo-06`)의 second_look 하이라이트 행을 보여 줌. 사람 확인 토스트 포함.
"시각 결과가 결정을 바꾼다"가 특별상 핵심 — trace로 뒷받침됨.
[SCREEN] `demo-06-agent-panel.png`; confirm toast from `demo-05`.
Sources: `docs/submission/AGENTIC_VISION.md` C1/C2/C3, traces
`second_look_quality_cleared`, `low_conf_ask_confirmation`, `guardrail_blocks_action`;
guardrails `src/nunchi/agent/guardrails.py`.

## Section 6 — AWS architecture · ~25 s · [DIAGRAM]
**Narration (EN):**
> "It runs on AWS: OpenCV 5 inside a single Lambda on arm64 Graviton, Python 3.12, with a
> hard concurrency cap of five as a cost and blast-radius ceiling. Session state lives in
> DynamoDB with a 24-hour expiry, not in Lambda memory. Frames are never written to disk,
> S3, or logs."

KO 메모: 지휘자 제공 아키텍처 다이어그램 자리(없으면 자리표시자). 수치는 템플릿 기준(1536MB/15s/동시성5).
[DIAGRAM] architecture placeholder (conductor) + `demo-08-privacy.png` as the trust beat.
Sources: `docs/report/TECHNICAL_REPORT.md` §3/§5; `cloud/template.yaml`.

## Section 7 — Evaluation & honest limits (incl. a failure) · ~30 s · [SCREEN]
**Narration (EN):**
> "We don't hide the limits. The agent passes twenty-two deterministic scenarios and nine
> adversarial ones — and we left one scenario failing on purpose, because the bug was in
> the test, not the agent. Watch a real failure path: in a dark room the quality warning
> fires, the second look doesn't clear it, so instead of guessing it asks you. That's the
> behaviour we want."

KO 메모: 실패 장면 = 어두운 환경 품질 경고 → second_look 미해소 → 사람에게 묻기(`demo-04` + 확인 토스트).
"22/22·9 적대·1건 의도적 FAIL"은 사실 그대로. 비전 정확도 수치는 언급 금지(미측정).
[SCREEN] `demo-04-run-skeleton.png` → confirm toast.
Sources: `docs/eval/AGENT_EVAL.md` (22 deterministic 100%, 9 adversarial 8/9, 1 intentional
FAIL); limits in `docs/submission/AGENTIC_VISION.md` §5; failure path 1c/1a.

## Section 8 — Close · ~15 s · [USER] optional
**Narration (EN):**
> "Nunchikochi — OpenCV 5 that sees, an agent that decides with you, on AWS, with your
> frames never kept. Thanks for watching."

KO 메모: 사용자가 마무리 인사를 직접 하면 사람/팀 요건을 자연스럽게 닫음.
[SCREEN] Report screen (`demo-07-report.png`) or EN/KO toggle (`demo-09-report-ko.png`).
Sources: report screen.

---

## Timing budget (target 4:30, cap 5:00)

| § | beat | target | cumulative |
|---|---|---|---|
| 1 | problem / who | 0:30 | 0:30 |
| 2 | app + privacy | 0:30 | 1:00 |
| 3 | live demo | 1:00 | 2:00 |
| 4 | OpenCV 5 | 0:40 | 2:40 |
| 5 | agent | 0:50 | 3:30 |
| 6 | AWS | 0:25 | 3:55 |
| 7 | eval + failure | 0:30 | 4:25 |
| 8 | close | 0:15 | 4:40 |

Buffer 0:20 under the 5:00 cap. If over, trim §4 and §6 first (they are the most
diagram-heavy and least narrative).

## Submission requirement checklist (map to beats)
- **Team / people**: §1 and §8 [USER] shots (user decides per U5).
- **App**: §2, §3 (screen captures / live).
- **Architecture**: §6 (+ §4 OpenCV path).
- **Results**: §7 (eval, honest limits incl. a failure).
- Public/unlisted upload per `USER_RECORDING_GUIDE.md`.

## [PENDING] items to resolve before final cut
- `[PENDING]` Graviton `analyze` latency & cold-start (C3/U6 deploy) — only if a latency
  number is spoken.
- `[PENDING]` per-behaviour vision accuracy — **not** to be spoken; kept out of the script.
- Architecture diagram asset from the conductor (placeholder until delivered).
