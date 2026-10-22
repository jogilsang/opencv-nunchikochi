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

`web/tools/capture.py` drives `?demo=1`, walks the whole flow, and writes the PNGs below.
If Playwright is unavailable it prints install guidance and exits non-zero (captures nothing).

## Screenshots (`docs/screenshots/`)

| file | screen | what it shows (video beat) |
|---|---|---|
| `demo-01-start.png` | Start / consent | value prop, privacy summary, consent gate, DEMO badge |
| `demo-02-calibrate.png` | Calibrate | 5-second neutral-posture countdown + progress |
| `demo-03-run-overlay.png` | Live + overlay | metrics (EAR / head tilt / face distance) + "what OpenCV sees" overlay (face box + landmark points) |
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

Record the demo screen (e.g. the browser tab) while `?demo=1` plays — the recorded session runs
on a fixed 0.5s/frame cadence and auto-advances start → calibrate → live beats → report, so a
single screen recording yields the motion clips without any camera. (No GIF is committed here to
keep the repo light; capture from the live demo for the final edit.)

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

