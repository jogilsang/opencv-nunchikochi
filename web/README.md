# Nunchikochi — web client

Static web UI (no bundler, no CDN, no tracking). Plain HTML + ES modules + CSS.
The whole flow runs with **no backend and no camera** via mock mode, so it never waits on other tabs.

## Run locally

```bash
cd web
python3 -m http.server 8080
```

Then open:

- **Mock mode (no camera, no server):** <http://localhost:8080/?mock=1>
- **Demo playback (recorded session, for the video / judges):** <http://localhost:8080/?demo=1>
- **Live (needs the cloud tab's API + a camera over HTTPS/localhost):** <http://localhost:8080/>
- Korean: add `&lang=ko` (e.g. `?mock=1&lang=ko`)

> **Demo mode** (`?demo=1`) replays a pre-recorded synthetic session
> (`assets/demo-session.json`, image-free `FrameResult`/`Decision` steps) through the *same code
> path* as live — only the data source is swapped (`DemoApi`). Overlay, agent panel, nudges,
> confirmation, and report all play with no camera and no server. A persistent
> "Demo playback — not a real camera" marker is always on screen; nothing is presented as a real
> measurement. Playback auto-ends into the report. Capture screenshots with `web/tools/capture.py`
> (see `docs/video/ASSETS.md`).

> Cameras need HTTPS or `localhost`. Over plain HTTP on a remote host the app shows a
> "secure connection required" screen with a one-click fallback to mock mode.

## Flow

`start (consent) → calibrate (5s) → live → report`

- **Live:** metrics (EAR / head tilt / face distance) with bars, event chips, a quality
  banner, and an **overlay** on the preview showing *what OpenCV sees* (face box + landmark
  points from `FrameResult.overlay`). The overlay can be toggled off (checkbox label is literal:
  *checked = shown*). While image quality is poor (e.g. too dark / no face), the metric panel
  shows a **"Measuring…" skeleton** instead of empty values. Nudges and the human-in-the-loop
  **confirmation** (Yes / Not now) appear as top-right toasts that never cover the live content.
- **Agent activity panel** (Agentic Vision evidence): a timeline of what the coach *did* after
  each frame — `action`, `reason`, localized `tool_calls`, and whether it needed you. Frames
  where the agent **re-checked with OpenCV before asking you** (`second_look`) and
  human-in-the-loop `ask_confirmation` are highlighted with "OpenCV re-checked before asking you".
  Quiet (`none`) frames are hidden behind a "Show quiet frames" filter. The panel is closable and
  becomes a bottom sheet on small screens. Raw coords/images are never shown.
- **Report:** number cards, the server's narrative (`report.text_en/ko`), up to 3 highlights,
  a **"compared to yesterday"** row (observational, from `GET /v1/summary` `summary`/`previous`),
  a per-behaviour breakdown table, a **share card** (canvas → PNG download, numbers only), and
  copy-summary. First-ever session shows a "first record" state instead of a comparison.

Camera failures and bad/temporary API responses are shown as friendly, recoverable states
(**cause + next action in one line**) — the demo never dead-ends. See *Error states* below.

## Error states

All route to one recoverable screen with a one-line "cause + next action":

| trigger | shown as | next action |
|---|---|---|
| camera permission denied | "Camera permission needed" | Retry / Try mock mode |
| no camera | "No camera found" | Retry / Try mock mode |
| not HTTPS/localhost | "Secure connection required" | Retry / Try mock mode |
| camera in use by another app | "Camera in use" | Retry / Try mock mode |
| offline (no network) | "You're offline" | Retry |
| server slow | "Server is slow" (auto-retry w/ backoff) | — (backoff) |
| 401/403 key rejected | "Access key rejected — update web/config.json" | Retry |
| 429 rate limited | "Too many requests" | — (slows + retries) |
| 5xx server error | "Server error" | Retry |
| session expired (404/410) | "Session expired" | Restart |

Transient blips (offline/5xx/429 mid-session) keep the session running and surface a small
reconnecting banner while the capture pump applies exponential backoff; hard errors
(key rejected, session expired) take over the full screen.

## Config

Copy the example and fill in the deployed API (do **not** commit `config.json` — it is gitignored):

```bash
cp config.example.json config.json
```

```json
{ "apiBase": "https://<function-url>", "apiKey": "<key>", "lang": "en", "fps": 2 }
```

`config.json` is optional; mock mode ignores it. Add `?dev=1` to show a frame-throughput
(KB/s) indicator on the preview.

## Privacy

There is a **Privacy & data** modal (header link) describing what is sent (low-res JPEG + session
token), what the server does (analysed in memory on AWS, then discarded), what is stored
(aggregate numbers only, ~30-day TTL), and that this is not a diagnosis. It has a
**"Delete my session data"** button.

> **TODO(contract):** the delete button is UI-only — there is no `DELETE` endpoint in the
> contract yet. Suggested: `DELETE /v1/summary?date=YYYY-MM-DD` (or per-session) so it actually
> removes the stored aggregates. Currently it only shows a done acknowledgement.

- The camera turns on only during a session. Frames are 320×240 JPEG, sent at ≤ 2 fps, and
  **analysed in memory on AWS and discarded immediately** — nothing is recorded or stored.
  Only aggregate numbers go into the report. (The app makes no "on-device only" claim: analysis
  runs on AWS; the honest promise is *no video is kept*.)
- A persistent "camera on" badge and discard notes are shown wherever the preview appears.
- The overlay is display-only geometry (0–1 coords); no image leaves the preview view.
- The share card contains numbers only — no face, no image.
- This is a wellbeing nudge, not a medical or emotional diagnosis.

## Accessibility (manual checklist)

Checked manually in a real browser (no CDN `axe`); automated audit is a follow-up.

- **Keyboard-only full flow — PASS.** Tab to consent, Space to toggle, Tab to Start, Enter →
  calibrate → run → End → report. Agent panel and privacy modal open/close by keyboard;
  **Escape** closes the modal; focus is trapped inside the modal and returns to the opener on close.
  Confirmation toast moves focus to its first button and restores focus on answer.
- **Focus visible — PASS.** Global `:focus-visible` outline (3px accent, 2px offset) on all
  interactive elements.
- **ARIA live regions — PASS.** Quality/temp-error banners are `role="status"` (polite); the
  confirmation prompt is `role="alertdialog"`; the error card is `role="alertdialog"`.
- **Not colour-only — PASS.** Trends show a word ("more/less than yesterday") not just colour;
  agent rows carry a text action label + icon; error states have text, not colour alone.
- **Contrast (WCAG AA, computed):** body text 14.2:1, muted text 7.4–8.2:1, accent on panel
  6.0:1, success 8.2:1, warning 9.4:1, primary-button text on accent 6.8:1 — all ≥ 4.5:1.
- **Reduced motion — PASS.** `prefers-reduced-motion: reduce` disables the LED pulse, skeleton
  shimmer, screen fades, and toast slide.
- **Zoom / responsive — PASS.** Layout holds at 200% zoom and down to 360px width (agent panel
  becomes a bottom sheet; no horizontal overflow, verified in-browser).

### Known limitations

- No automated `axe` run (offline, no CDN allowed) — checklist is manual.
- Screen-reader announcement wording not verified with an actual screen reader.
- The preview/overlay canvases are `aria-hidden` (decorative); the metrics panel is the
  accessible representation of what the camera sees.

## Size

First-load JS (uncompressed, all modules): **≈ 66 KB** (< 100 KB budget). Per file: app.js 30.4,
i18n.js 14.0, mock.js 9.3, capture.js 4.8, sharecard.js 3.8, overlay.js 3.0, api.js 2.7 KB.
No external libraries or fonts. (`mock.js` is dev/demo only and could be dropped from a
production build.)

## Files

| file | role |
|---|---|
| `index.html` | screen shells (start / error / calibrate / run + agent panel / report) + privacy modal |
| `app.js` | state machine, wiring, agent activity log, error routing, privacy modal, dev stats |
| `api.js` | HTTP client for CONTRACTS §3 (`Api`, incl. `GET /v1/summary`) |
| `mock.js` | fake server with the same surface (`MockApi`): scripted run scenario incl. two `second_look` beats, fake `overlay`, today+yesterday `summary` |
| `capture.js` | getUserMedia → 320×240 JPEG ≤ 2 fps, tab-hidden pause, exponential backoff; canvas fake-video for mock |
| `overlay.js` | draws the face box + landmark points over the mirrored preview (mirrors x, clamps out-of-range coords) |
| `sharecard.js` | renders a numbers-only share card to a PNG blob + triggers download |
| `i18n.js` | all user-facing strings (EN primary, KO) |
| `styles.css` | calm/trust visual design, focus/contrast/reduced-motion, responsive to 360px |
| `config.example.json` | template for `config.json` (gitignored) |

## Contract alignment

Response shapes match `docs/CONTRACTS.md` §1/§2/§3 and `tests/fixtures/*.json`
(`FrameResult` incl. `overlay`, `Decision` incl. `tool_calls`/`needs_human`, `SessionSummary`
from `src/nunchi/contracts.py`). The agent panel reads `decision.tool_calls[{tool,args,result_summary}]`
and highlights the `second_look` tool. Mock data mirrors those fixtures. If the server omits
`overlay` (null), the preview simply draws nothing.
