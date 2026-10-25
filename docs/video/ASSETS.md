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

Judges can also use **Live (your camera)** mode. These shots were captured against a
real **local** service (started like `scripts/run_local.sh`) with a **Playwright fake camera**
— still no real face, no AWS, no account IDs or keys on screen. Live mode needs **no shared
key**: the page issues a 30-minute key with the **"Get a trial key (30 min)"** button, so
there is no key field to blur.

| file | screen | what it shows |
|---|---|---|
| `live-01-select-nokey.png` | Start → Live selected | mode cards (Demo / Live), the **"Get a trial key (30 min)"** button + its IP note, memory-only hint |
| `live-02-connected-ready.png` | Live, connected, ready | trial key active, honest status line **"Connected · Running on arm64 · opencv · OpenCV 5.0.0"** read from `/healthz`, consent checked, Start enabled |
| `live-03-running-fakecam.png` | Live session running | fake-camera stream in the preview, run UI (metrics "Measuring…" because the test pattern has no face), "Away" event + a real agent confirmation toast — the actual decision loop, not a replay |

```bash
# bring the stack up locally (service + static web), then:
SVC=http://127.0.0.1:8000 KEY=<local dummy key> BASE=http://localhost:8099 \
  OUT=docs/screenshots node web/e2e/capture-w6.mjs
```

The status string is only shown when `/healthz` actually returns those fields; if a field is
missing it is omitted (never invented). `web/config.json` is written for the capture and
removed afterwards (it is gitignored; only `web/config.example.json` is committed).

## Trial-key assets (`docs/screenshots/w21-*.png`) — W21

Live mode is unlocked from the page itself: one click on **"Get a trial key (30 min)"**
issues a 30-minute key (same IP 3×/day, 6/day across the whole service). No key is passed to
judges, and nothing needs to be hidden on screen. The per-IP limit uses only a **keyed hash**
of the client IP kept for 48 h (the raw IP is never stored, and it is removed from access logs).

| file | what it shows (video beat) |
|---|---|
| `w21-button.png` | Live selected, the "Get a trial key (30 min)" button + the IP note ("used only to check the 3-per-day limit, stored as an encrypted value for 48 hours") |
| `w21-countdown.png` | a trial key active, the "Trial key: mm:ss left" status counting down |
| `w21-expired.png` | the key expired state ("get a new key, or use Demo mode — no key needed") |
| `w21-429.png` | the limit-reached message when keys are used up (fall back to Demo mode) |
| `w21-mobile.png` | mobile 390px — the button + IP note render at narrow width with no horizontal scroll |

```bash
# healthz key_issuing:true drives the button; demo/mock, no real server:
BASE=http://localhost:8099 node web/e2e/capture-w21.mjs   # → docs/screenshots/w21-*.png
```

## Posture-buddy assets (`docs/screenshots/w22-*.png`, `w20-buddy-drink.png`) — W20/W22

The **posture buddy / 자세 인형** is a soft pastel-clay **face + neck** (W20; the body, arms,
hands and desk were removed — people said "the face is the point"). What it draws: the
**head follows the measured angles** (`FrameResult.overlay.pose`: yaw/pitch/roll/depth/conf,
numbers only) and the **face mirrors your measured expression** (`overlay.expr`: eyes, mouth,
smile, brows — measured face movement, **not** an emotion guess); the **neck is a labelled
model estimate** from the head angles (`web/buddy-kinematics.js`), and **no body is drawn**.
A measured **drink event** shows a small cup near the mouth (no arm). A panel line states it:
"Head pose and expression are measured; the neck is an estimate. No body is drawn." While
vision hasn't shipped real pose it plays a synthetic fixture (`web/assets/pose-fixture.json`,
numbers only, with a drink span) — DEMO playback, never a real measurement. Rendered with
vendored three.js (`web/vendor/`, MIT, pinned r158, no CDN); drag/arrow rotation is
hand-rolled; movement is shown ~1.5× with an on-screen label; 2D fallback if WebGL is
unavailable (same honesty line). W22 redrew the face so expressions read clearly.

| file | what it shows (video beat) |
|---|---|
| `w22-buddy-neutral.png` | front view, neutral — the face + neck at rest, calm green, honesty line visible |
| `w22-buddy-smile.png` | a measured **smile** (mouth + cheeks) following `overlay.expr.smile` |
| `w22-buddy-mouth-open.png` | a measured **open mouth** (e.g. a yawn) following `overlay.expr.mouth_open` |
| `w22-buddy-eyes-closed.png` | measured **eyes closed** (blink / deep blink) following `overlay.expr.eye_*` |
| `w22-buddy-wink.png` | a measured **wink** — one eye closed (asymmetric `eye_l` / `eye_r`) |
| `w22-buddy-brows-up.png` | measured **raised brows** following `overlay.expr.brow_raise` |
| `w22-buddy-forward.png` | **forward-head** — head leans forward/chin-down (measured) while the neck gives an estimated bow; colour warms to amber |
| `w22-buddy-side.png` | side view of a head tilt — forward-head creep reads clearly |
| `w20-buddy-drink.png` | the **measured drink event** — a small cup appears near the mouth (no arm) |
| `w22-buddy-mobile.png` | mobile 390px — the figure + honesty line render at narrow width with no horizontal scroll |

```bash
# demo mode only (no camera, no server), software WebGL for headless capture:
BASE=http://localhost:8099 node web/e2e/capture-w22.mjs   # → docs/screenshots/w22-buddy-*.png
BASE=http://localhost:8099 node web/e2e/capture-w20.mjs   # → docs/screenshots/w20-buddy-*.png
```

### Screen recording for the buddy scene (SCRIPT §6 / SHOTLIST scene 6)

- **Demo-mode buddy playback (auto):** `web/tools/record_demo.mjs` (demo mode `?demo=1&fast=1`,
  **no fake camera**) includes a buddy beat — it scrolls the face + neck into view and drives
  expressions → forward-head (estimated bow) → drink cup → side view + sky-blue ghost → rewind
  scrub, so the buddy motion is captured without any camera. Output webm is gitignored
  (`docs/video/recordings/`, never committed).
  ```bash
  python3 -m http.server 8099 --directory web
  node web/tools/record_demo.mjs --base http://localhost:8099 --out docs/video/recordings
  ```
- **Live buddy short clip ([USER] — user's job):** a short clip of the buddy following a real
  webcam (expressions → lean forward → sit up → rewind) is recorded by the user per
  `USER_RECORDING_GUIDE.md` step 3.5. Optional; the demo recording already covers the beat.

### Suggested video beat (SCRIPT §6, ~40 s, after the agent panel)

> "You can also see yourself as a calm clay face and neck. The honest part is on screen: the
> head pose and your facial movement are measured; the neck is a model estimate, and no body
> is drawn. Smile, blink, raise your brows — measured face movement, not an emotion guess;
> lean in and the neck gives an estimated bow; a measured sip shows a small cup at the mouth.
> Rotate it, compare to the faint sky-blue good-posture ghost, and scrub the timeline to see
> exactly when your head crept forward. Movement is exaggerated ~1.5×."

### Rules honoured (W20 / W22)

- Numbers only: the buddy never touches images or raw landmark points (privacy modal states this).
- Head + expression measured; the **neck is estimated** and **no body is drawn** (body pose deferred — `docs/eval/BODY_POSE_FEASIBILITY.md`); the narration says so, and expression is measured face movement, not emotion.
- Child-friendly: rounded clay face, no bones/skeleton; calm green→amber, never red/fear colours.
- Honest: the ~1.5× exaggeration is labelled on screen; low confidence holds still and says so; no accuracy claim.
- Accessible: canvas is `role="img"` with a spoken aria-label, state is also shown as text
  (never colour-only); ghost has a text legend; EN/KO throughout; axe violations stay at 0 (hard).
- Resilient: three.js or WebGL unavailable → a simple 2D angle view; console errors stay at 0.
- Memory only: the rewind track is a browser-memory ring buffer — never saved, sent, URL'd, or
  localStorage'd. The demo marker stays visible as a full-width bottom strip (W11).
