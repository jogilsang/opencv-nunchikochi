# Web e2e & accessibility — WEB_E2E.md

Owner: web tab (W5). Results are recorded **as-is** (pass and fail), with the exact
commands to reproduce. No real camera and no real server are used: the suite drives
the app in demo (`?demo=1`) / mock (`?mock=1`) mode with a fake media-stream flag.

## How to run

```bash
# browser e2e (starts its own static server on :8099, then runs the suite)
cd opencv_nunchikochi/web
npm run e2e                       # == node e2e/serve-and-run.mjs

# accessibility scan (axe-core); point AXE_PATH at a local axe build, serve web/ first
python3 -m http.server 8099 --directory web &
AXE_PATH=/path/to/axe-core/axe.min.js BASE=http://localhost:8099 node web/e2e/axe-run.mjs

# before/after screenshots for the three W5 fixes
BASE=http://localhost:8099 OUT=../docs/screenshots node web/e2e/capture-w5.mjs
```

Playwright and axe-core are **not vendored** into the repo. They are installed ad hoc
(e.g. a global `playwright` + `npx playwright install chromium`, and `npm i axe-core`).
If Playwright is missing, the runner throws Playwright's own "install browsers" message;
install chromium and re-run.

## 1. Browser e2e (Playwright, chromium)

Command: `npm run e2e` → `web/e2e/run.mjs`. Last run: **50 / 50 passed, 0 failed.**

| Group | Check | Result |
|---|---|---|
| core flow (demo, desktop) | reaches run screen | ✅ |
| core flow | demo badge + corner marker visible | ✅ |
| core flow | overlay toggle hides/shows overlay canvas | ✅ |
| core flow | a nudge or confirm toast appears during demo | ✅ |
| core flow | **W5①** toasts never exceed 2 and don't cover metric cards | ✅ |
| core flow | agent panel opens and lists decisions (aria-expanded) | ✅ |
| core flow | session ends and report renders | ✅ |
| core flow | no uncaught page errors | ✅ |
| i18n | default is EN | ✅ |
| i18n | switch to KO updates `html lang` + Start label | ✅ |
| i18n | switch back to EN | ✅ |
| privacy | modal opens and closes with keyboard (Escape) | ✅ |
| mode select (W6) | both mode cards present (radiogroup) | ✅ |
| mode select (W6) | no mode chosen → Start disabled with a pick hint | ✅ |
| mode select (W6) | Live reveals a password access-key field | ✅ |
| mode select (W6) | Live + consent but empty key → Start stays disabled | ✅ |
| mode select (W6) | Demo + consent → Start enabled | ✅ |
| mode select (W6) | access key never lands in localStorage / sessionStorage / URL | ✅ |
| mode + pacing (W13) | before mode select: access key hidden AND demo strip hidden | ✅ |
| mode + pacing (W13) | Demo selected → strip visible, access key hidden | ✅ |
| mode + pacing (W13) | Live selected → access key visible, demo strip hidden (honest) | ✅ |
| mode + pacing (W13) | `[hidden]` attribute truly forces `display:none` on display-styled elements | ✅ |
| mode + pacing (W13) | default demo shows "Skip to report" + realtime progress controls | ✅ |
| mode + pacing (W13) | default demo stays on run screen (no ~7s auto-advance; 60–90s window) | ✅ |
| mode + pacing (W13) | default demo "Skip to report" ends the session on demand | ✅ |
| posture buddy (W10) | 3D/2D init, pose track, exaggeration 1.5×, rewind scrub | ✅ (10 checks) |
| demo strip (W11) | full-width bottom strip, no overlap, no clip @390/360px | ✅ (6 checks) |
| error states | `denied` (camera refused) → recoverable screen + retry | ✅ |
| error states | `server` (server error) → recoverable screen + retry | ✅ |
| error states | `offline` (network drop) → recoverable screen + retry | ✅ |
| error states | `errorKindFromStatus` maps 500→server, 401→unauthorized, 429→rate_limited | ✅ |
| layout | desktop 1280px: no horizontal scroll on run | ✅ |
| layout | mobile 390px: no horizontal scroll on run | ✅ |
| layout | mobile 390px: demo corner within viewport | ✅ |
| keyboard only | consent + start reachable by Tab/Space/Enter → run | ✅ |
| keyboard only | visible focus indicator (focus-visible outline) present | ✅ |

Flow covered end to end (demo): first screen → start → calibrate → run → overlay toggle
→ nudge/confirm → agent panel → end session → report. Error states exercised via the
`window.__nunchi.showError(kind)` test hook (no real failures needed). Three error kinds
required by the brief — camera refused (`denied`), server error (`server`), network drop
(`offline`) — all land on the single recoverable error screen with a retry action.

## 2. Accessibility (axe-core, WCAG 2 A/AA)

Command: `node web/e2e/axe-run.mjs`. Scanned: start, privacy modal, run, run+agent-panel,
report. **Hard (non-contrast serious/critical) violations: 0.**

| Screen | Hard violations | Contrast advisories |
|---|---|---|
| start | 0 | 0 |
| privacy-modal | 0 | 0 |
| run | 0 | 0 |
| run + agent panel | 0 | 1 (see note) |
| report | 0 | 1 (see note) |

Notes recorded as-is:
- The scan waits for each screen's fade-in to settle (opacity ≈ 1) before measuring.
  Measuring mid-animation makes axe read the body gradient through the still-transparent
  card and report a *false* low-contrast; waiting removes that.
- Position-fixed pills (`#demo-corner`, `#toast-host`) are hidden during the scan because,
  when they overlap flow text, axe cannot resolve the real background and falls back to
  white.
- The two remaining **contrast advisories** are both the footer `<span data-i18n="discardNote">`.
  At scan time that footer span measures as a zero-area box (the run screen pushes it off
  the measured area), so axe falls back to a white background and reports a false ~2:1.
  The element's real colours are `--muted #a9b8cc` on the dark panel/background, which
  computes to **7.4:1 (panel) – 9.2:1 (page bg)** — comfortably above the AA 4.5:1 floor.
  Verified by hand (relative-luminance contrast calc), so these are advisory, not failures.

Manual a11y checklist (from the e2e + inspection):
- Keyboard-only: whole demo flow reachable; `:focus-visible` outline on controls. ✅
- ARIA: toasts `role=status`, confirm `role=alertdialog`, agent toggle `aria-expanded`,
  modal focus trap + Escape, `aria-live` on event/temp-error regions. ✅
- Reduced motion: `@media (prefers-reduced-motion: reduce)` disables non-essential
  animation (fade, pulse, shimmer, demo pulse). ✅
- No horizontal scroll at 390px and 1280px on the run screen. ✅
- Colour is never the only signal (icons/labels alongside colour on toasts, agent rows,
  trends). ✅

## 3. W5 defect fixes (before / after)

All three defects seen in the W4 screenshots are fixed; before/after pairs are in
`docs/screenshots/`.

| # | Defect | Fix | Before → After |
|---|---|---|---|
| ① | With the agent panel open, up to 3 top-right toasts covered the EAR / HEAD TILT / FACE DISTANCE metric cards. | Toast stack moved to **bottom-right**, newest on top, **capped to 2** (oldest dismissible evicted; human-in-the-loop confirm prompts are never evicted). Sits clear of the right-column metrics and above the demo corner. | `w5-01a-toast-before.png` → `w5-01b-toast-after.png` |
| ② | The "Demo playback — not a real camera" corner marker sat bottom-right and, at narrow widths, wrapped over body text / the toast area. | Pinned **bottom-left**, single line (`nowrap` + ellipsis) with its own opaque pill background, `max-width: calc(100vw - 28px)`; clear of the bottom-right toast stack. | `w5-02a-democorner-before.png` → `w5-02b-democorner-after.png` (viewport 360px) |
| ③ | The on-screen preview is CSS-mirrored (`scaleX(-1)`), so the "mock preview" label rendered reversed. | The label is **counter-flipped** on the canvas (`translate(W,0); scale(-1,1)`) so it reads left-to-right after the outer mirror. The preview image itself stays mirrored. | `w5-03a-label-before.png` → `w5-03b-label-after.png` |

The combined result is also visible in the refreshed demo frame
`docs/screenshots/demo-05-run-toast.png` (2 toasts bottom-right, all metric cards
visible, demo corner bottom-left, label reads normally).

## 3b. W13 defect fixes (deployed-screen inspection)

Four defects reproduced on the deployed site (desktop 1280 / mobile 390) are fixed; the
run and start screenshots in `docs/screenshots/` are refreshed to match.

| # | Defect (reproduced) | Fix |
|---|---|---|
| 1 | The `hidden` attribute was overridden by elements that set an explicit `display` (only `.modal-backdrop[hidden]` had a guard), so `hidden` silently did nothing on `.demo-corner`, `.live-panel`, `.field`, etc. | Global **`[hidden] { display: none !important; }`** in `styles.css`. Audited every `hidden`-toggled element; `.demo-corner` (flex) and `.live-panel` (grid) are the two that were leaking — both now respect the attribute. Class-based `.hidden` toggles (overlay canvas) are unaffected. |
| 2 | The "Demo playback — not a real camera" strip showed on the first screen **and in Live mode** (before/after both visible), mislabelling a real camera session as playback. | The strip + DEMO badge are shown **only in demo mode** (`?demo=1` or the Demo card). Selecting Live (or starting a live/mock session) calls `hideDemoStrip()` and releases the reserved `body.has-demo-strip` space. e2e asserts the strip is hidden in the live run (`live.mjs`) and across the mode matrix (`run.mjs`). |
| 3 | The access-key field showed before a mode was chosen (intended only for Live). | Fixed by defect 1: `#live-panel[hidden]` now truly hides. `selectMode` sets `livePanel.hidden = mode !== "live"`, so the key appears only for Live and is hidden for Demo / before any pick. |
| 4 | The demo run auto-advanced to the report in ~7s (13 steps × 0.5s), too fast for a judge to see the overlay, buddy, agent panel, toasts. | Default demo now runs at **realtime speed for ~75s** (within the brief's 60–90s) with a **progress bar**, a **"Skip to report"** button, and the always-present **"End session"**; it never auto-advances — `DemoApi` loops the recorded steps until the judge ends it. The quick pre-W13 behaviour is preserved under **`?demo=1&fast=1`**, which the e2e suite and `record_demo.mjs` use. |

Regression coverage for all four lives in the "mode + pacing (W13)" group (§1) plus the live
no-strip check (§4b).

## 4. W6 live mode (Demo / Live, access key, service status)

### 4a. Start-screen mode select & key safety (self-contained e2e)

Covered by the "mode select (W6)" group above (6 checks, no service needed). Confirms the
Demo / Live radiogroup, that Start is gated until a mode is chosen (and, for Live, a key is
entered), the key field is `type=password`, and — the key never reaches `localStorage`,
`sessionStorage`, or the URL (asserted by injecting a value and scanning all three). The key
is held in a module-level variable in `app.js` and is never written to `state`, storage, the
URL, or logs.

### 4b. Live integration against a local service

Command: `node web/e2e/live.mjs` (needs a running service + static web server; use
`scripts/run_local.sh`, or start the service any other way and pass `SVC`/`KEY`/`BASE`).
Last run against a local `uvicorn nunchi.service.app` on `:8000` with a **Playwright fake
camera**: **7 / 7 passed, 0 failed.**

| Check | Result |
|---|---|
| start gate blocks Live with no key | ✅ |
| service status shows real runtime (arch / OpenCV) from `/healthz` | ✅ (`Running on arm64 · opencv · OpenCV 5.0.0`) |
| key + consent enables Start; key stays in memory only (no localStorage / sessionStorage / URL leak) | ✅ |
| live session runs: calibrate → run with overlay + metrics | ✅ |
| live run shows **no** demo strip/badge/skip/progress (honesty — W13) | ✅ |
| end session → report renders | ✅ |
| no uncaught page errors during the live run | ✅ |

`web/config.json` is written for the run (dummy local key) and removed afterwards; it is
gitignored (only `web/config.example.json` is committed). The service URL is **never**
hardcoded in the web code — `api.js`/`app.js` read `apiBase` only from `config.json`.

### 4c. config.json present vs absent

- **Absent** (default): the self-contained suite (`npm run e2e`) runs with no `config.json`;
  `state.cfg.apiBase` falls back to the example default and the demo path needs no server.
  Live mode then shows its status line / "no service" guidance instead of crashing.
- **Present**: `live.mjs` and `capture-w6.mjs` write a `config.json` pointing at the local
  service; the status line reflects the real `/healthz`, and the live session runs.

### 4d. Connection status / runtime honesty

The status line is built only from fields `/healthz` actually returns
(`arch`, `backend`, `cv_version`). Missing fields are omitted — nothing is invented. When the
service is unreachable it shows an "unreachable — try Demo" message and keeps Start disabled.

### 4e. Error mapping for live

`errorKindFromStatus` (covered in §1) maps the live failure modes the brief calls out:
401 → `unauthorized` (rejected key), 0/offline → `offline`, ≥500 → `server`, 429 →
`rate_limited`, 404/410 → `expired` (session gone). Each lands on the single recoverable
error screen with EN/KO copy and a retry/switch-to-demo action.

### 4f. Live-mode screenshots (fake camera)

`docs/screenshots/live-01-select-nokey.png`, `live-02-connected-ready.png`,
`live-03-running-fakecam.png` — see `docs/video/ASSETS.md`. No real face, no AWS, no key or
account ID on screen.

## Known limitations

- `fullPage` screenshots render position-fixed pills at their scroll position, so a
  tall capture can look like the demo corner sits mid-page; in the real 360/390px
  viewport it is pinned to the bottom edge (see the viewport-only `w5-02*` shots).
- axe cannot resolve contrast for zero-area / gradient-backed elements; those are
  reported as advisories with the hand-verified true ratios above rather than hidden.
- The suite needs a browser; there is no camera or AWS dependency.
