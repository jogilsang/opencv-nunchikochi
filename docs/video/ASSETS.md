# Video assets — Nunchikochi web UI

Screen assets for the 5-minute submission video, captured from **demo playback** (`?demo=1`):
no camera, no AWS, no real faces — only the synthetic recorded session
(`web/assets/demo-session.json`). All numbers on screen are demo data, not a real measurement;
the UI shows a persistent "Demo playback — not a real camera" marker in every shot.

## How these were made

```bash
# serve the static web/ folder (no bundler)
python3 -m http.server 8099 --directory web

# capture (Playwright for Python; installs chromium on first run)
uv run --with playwright python -m playwright install chromium   # once
uv run --with playwright python web/tools/capture.py \
    --base http://localhost:8099 --out docs/screenshots --lang en
```

`web/tools/capture.py` drives `?demo=1` (realtime-paced demo, so the run screen stays up and
shows the progress + "Skip to report" controls), walks the whole flow, and writes the PNGs below.
If Playwright is unavailable it prints install guidance and exits non-zero (captures nothing).

## Screenshots (`docs/screenshots/`)

| file | screen | what it shows (video beat) |
|---|---|---|
| `demo-01-start.png` | Start / consent | value prop, privacy summary, consent gate, DEMO badge (demo mode only) |
| `demo-02-calibrate.png` | Calibrate | 5-second neutral-posture countdown + progress |
| `demo-03-run-overlay.png` | Live + overlay | metrics (EAR / head tilt / face distance) + "what OpenCV sees" overlay (face box + landmark points); in default demo the realtime progress bar + "Skip to report" controls are visible |
| `demo-04-run-skeleton.png` | Live, low quality | quality banner + "Measuring…" skeleton (too dark / no face → agent asks for light) |
| `demo-05-run-toast.png` | Live, nudge/confirm | sustained head-tilt nudge / human-in-the-loop confirmation toast |
| `demo-06-agent-panel.png` | Agent activity | perceive→decide→act timeline; **second_look** rows "OpenCV re-checked before asking you" |
| `demo-07-report.png` | Report | number cards, narrative, highlights, "compared to yesterday", by-behaviour table |
| `demo-08-privacy.png` | Privacy modal | what is sent / analysed on AWS / stored (aggregates, ~30-day TTL); not a diagnosis |
| `demo-09-report-ko.png` | Report (KO) | the same report in Korean (i18n) |

All 9 are 2× device-scale PNGs at 980px width (report/agent shots are full-page).

## Suggested 5-minute video flow (web portion)

1. **Hook / privacy** — Start screen: consent + "frames analysed in memory on AWS, discarded, only aggregate numbers kept" (01).
2. **Calibration** — brief neutral-posture capture (02).
3. **Live + Agentic Vision** — overlay shows what OpenCV sees (03); image quality drops and the agent asks for light instead of guessing (04); sustained head tilt → a gentle nudge, and an uncertain drink → it re-checks with OpenCV (`second_look`) before asking you (05).
4. **Evidence panel** — open Agent activity: every decision, the tools it called, and the two `second_look` moments highlighted (06).
5. **Report & trend** — session summary, honest "compared to yesterday" observations, by-behaviour breakdown, share card (07); Korean (09).
6. **Trust** — Privacy & data modal (08).

## Short clips / GIFs

Record the demo screen (e.g. the browser tab) while `?demo=1&fast=1` plays — fast mode runs the
recorded session on a fixed 0.5s/frame cadence and auto-advances start → calibrate → live beats →
report, so a single screen recording yields the motion clips without any camera. (Plain `?demo=1`
is realtime-paced ~60–90s and waits for a "Skip to report"/"End session" click instead of
auto-advancing — good for a live walkthrough; fast mode is better for an unattended recording.)
`web/tools/record_demo.mjs` uses `?demo=1&fast=1`. (No GIF is committed here to keep the repo
light; capture from the live demo for the final edit.)

## Rules honoured

- No real-face imagery; only the synthetic demo session is shown.
- No account IDs or keys appear on screen (demo uses `session_id: "demo-session"`, no config).
- "Demo playback — not a real camera" is always visible; nothing is presented as a real measurement.

## Live-mode assets (`docs/screenshots/live-*.png`) — W6

Judges can also use **Live (your camera)** mode. These three shots were captured against a
real **local** service (started like `scripts/run_local.sh`) with a **Playwright fake camera**
— still no real face, no AWS, no account IDs or keys on screen. The access key field is a
password input and the key is held in memory only (never saved to the device, URL, or logs).

| file | screen | what it shows |
|---|---|---|
| `live-01-select-nokey.png` | Start → Live selected, no key | mode cards (Demo / Live), access-key field empty, "Enter the access key to start a live session" gate, memory-only hint |
| `live-02-connected-ready.png` | Live, connected, ready | key filled (masked), honest status line **"Connected · Running on arm64 · opencv · OpenCV 5.0.0"** read from `/healthz`, consent checked, Start enabled |
| `live-03-running-fakecam.png` | Live session running | fake-camera stream in the preview, run UI (metrics "Measuring…" because the test pattern has no face), "Away" event + a real agent confirmation toast — the actual decision loop, not a replay |

```bash
# bring the stack up locally (service + static web), then:
SVC=http://127.0.0.1:8000 KEY=<local dummy key> BASE=http://localhost:8099 \
  OUT=docs/screenshots node web/e2e/capture-w6.mjs
```

The status string is only shown when `/healthz` actually returns those fields; if a field is
missing it is omitted (never invented). `web/config.json` is written for the capture and
removed afterwards (it is gitignored; only `web/config.example.json` is committed).


## Posture-buddy assets (`docs/screenshots/w14-*.png`) — W14

The **posture buddy / 자세 인형** is a soft pastel-clay **seated upper-body figure** (head,
neck, level shoulders, chest/belly in a plain solid top, upper arms, forearms, hands — no
bones, no skeleton, gender/ethnicity-neutral). **Legs are not drawn** (hidden under a simple
desk + keyboard; an optional chair-back silhouette sits behind). Honesty is on screen: the
**head follows the measured angles** (`FrameResult.overlay.pose`: yaw/pitch/roll/depth/conf,
numbers only) and the **drink event** raises the right arm; the **neck, torso and arms are a
labelled model estimate** (`web/buddy-kinematics.js`) — we do not measure shoulders/torso/legs.
A panel line states it: "Head and hand are measured; neck and torso are a model estimate. Legs
are not drawn." While vision hasn't shipped real pose it plays a synthetic fixture
(`web/assets/pose-fixture.json`, numbers only, with a drink span) — DEMO playback, never a real
measurement. Rendered with vendored three.js (`web/vendor/`, MIT, pinned r158, no CDN); low-poly
(~3.2k triangles, ≤ 4k budget); drag/arrow rotation is hand-rolled; movement is shown ~1.5×
with an on-screen label; 2D angle-icon fallback if WebGL is unavailable (same honesty line).

| file | what it shows (video beat) |
|---|---|
| `w14-buddy-front-neutral.png` | front view, neutral — the seated figure at rest with forearms resting forward on the desk (hands near the keyboard), calm green, honesty line visible, state "Head level and centered" |
| `w14-buddy-front-forward.png` | forward-head — head leans forward/chin-down (measured) while the body gives an estimated bow; colour warms to amber; state ends "— torso is estimated" |
| `w14-buddy-drinking.png` | the **measured drink event** raises the right arm so the hand/cup reaches mouth height (apex frame, pinned via a test hook) |
| `w14-buddy-drinking-side.png` | the same drink apex from the side — elbow down, forearm folded up to the face (anatomically natural) |
| `w14-buddy-side.png` | side view of a head tilt — the seated profile (desk/keyboard visible); forward-head creep reads clearly |
| `w14-buddy-top.png` | top view — looking down on the seated figure (chin-down + forward) |
| `w14-buddy-ghost.png` | **faint sky-blue good-posture ghost** overlaid on a forward-leaning buddy (toggle) + legend "Faint sky-blue outline = good posture" (distinct colour family + thin outline, not a wireframe) |
| `w14-buddy-mobile.png` | mobile 390px — the figure + honesty line render at narrow width with no horizontal scroll |

```bash
# demo mode only (no camera, no server), software WebGL for headless capture:
BASE=http://localhost:8099 node web/e2e/capture-w14.mjs   # → docs/screenshots/w14-buddy-*.png
```

### Screen recording for the buddy scene (SCRIPT §6 / SHOTLIST scene 6)

- **Demo-mode buddy playback (auto):** `web/tools/record_demo.mjs` (demo mode `?demo=1&fast=1`,
  **no fake camera**) includes a buddy beat — it scrolls the seated figure into view and drives
  tilt → forward-head (estimated bow) → side view + sky-blue ghost → rewind scrub, so the buddy
  motion is captured without any camera. The fixture also carries a drink span that raises the
  arm. Output webm is gitignored (`docs/video/recordings/`, never committed).
  ```bash
  python3 -m http.server 8099 --directory web
  node web/tools/record_demo.mjs --base http://localhost:8099 --out docs/video/recordings
  ```
- **Live buddy short clip ([USER] — user's job):** a short clip of the buddy following a real
  webcam (head tilt → lean forward → sit up → rewind) is recorded by the user per
  `USER_RECORDING_GUIDE.md` step 3.5. Optional; the demo recording already covers the beat.

### Suggested video beat (SCRIPT §6, ~40 s, after the agent panel)

> "You can also see yourself as a calm, seated posture buddy. The honest part is on screen: the
> head and the drink are measured; the neck and torso are a model estimate, and the legs aren't
> drawn. Lean in and the body gives an estimated bow; take a sip and the measured drink event
> raises its arm. Rotate it, compare to the faint sky-blue good-posture ghost, and scrub the
> timeline to see exactly when your head crept forward. Movement is exaggerated ~1.5×."

### Rules honoured (W10 / W11)

- Numbers only: the buddy never touches images or raw landmark points (privacy modal states this).
- Head only: shoulders/torso are **not** estimated (body pose deferred — `docs/eval/BODY_POSE_FEASIBILITY.md`); the narration says so.
- Child-friendly: rounded clay figure, no bones/skeleton; calm green→amber, never red/fear colours.
- Honest: the ~1.5× exaggeration is labelled on screen; low confidence holds still and says so; no accuracy claim.
- Accessible: canvas is `role="img"` with a spoken aria-label, state is also shown as text
  (never colour-only); ghost has a text legend; EN/KO throughout; axe violations stay at 0 (hard).
- Resilient: three.js or WebGL unavailable → a simple 2D angle view; console errors stay at 0.
- Memory only: the rewind track is a browser-memory ring buffer — never saved, sent, URL'd, or
  localStorage'd. The demo marker stays visible as a full-width bottom strip (W11).
