# Web e2e & accessibility — WEB_E2E.md

Owner: web tab (W5). Results are recorded **as-is** (pass and fail), with the exact
commands to reproduce. No real camera and no real server are used for the main suite: it
drives the app in demo (`?demo=1`) / mock (`?mock=1`) mode with a fake media-stream flag.

**These results are from the LOCAL SOURCE in `web/`** (run on this machine), not from the
deployed CloudFront build. Re-run after any deploy (C15) to confirm the deployed bundle
matches. The one exception is the live-integration run (§4b, §5), which drives the real local
FastAPI service started by `scripts/run_local.sh`.

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

Command: `npm run e2e` → `web/e2e/run.mjs`. Last run: **87 / 87 passed, 0 failed**
(ran 3× consecutively, 0 failures). Count grew 60 → 76 (W16) → 83 (W17) → 87 (W19):
W16 added quiet mode + the posture-record timeline + the earlier-session comparison; W17
added the real server-field mapping (`report.trend`, `history`) + the anonymous `X-Anon-Id`
continuity checks; W19 added the short-session posture-record cases (count shown even when the
hourly rate is withheld).

Unit tests: `npm run test:unit` → `node --test buddy-kinematics.test.mjs` — **6 / 6 passed**
(the pure posture→rig mapping: neutral base, 1.5× exaggerate + clamp, monotonic torso lean +
cap, low-confidence hold, drink→right arm, NaN/undefined input).

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
| quiet mode (W16) | quiet mode ON by default: toggle checked + calm status chip shown | ✅ |
| quiet mode (W16) | in quiet mode a nudge does NOT toast — it counts on the chip instead | ✅ |
| quiet mode (W16) | turning quiet OFF then a nudge shows exactly one toast | ✅ |
| quiet mode (W16) | same-kind nudge during cooldown merges as "+N more" (queue stays 1) | ✅ |
| quiet mode (W16) | no uncaught page errors in the quiet-mode flow | ✅ |
| timeline (W16) | posture-record card shows an hourly rate + a bar chart | ✅ |
| timeline (W16) | tabs switch the slice (5m → 30m) | ✅ |
| timeline (W16) | chart is accessible (role=img + non-empty aria-label) | ✅ |
| timeline (W16) | table-view toggle reveals an equivalent table | ✅ |
| comparison (W16) | demo comparison shows improving trend + "Example data" label | ✅ |
| comparison (W16) | demo mode does NOT write rates to localStorage (sample stays sample) | ✅ |
| comparison (W16) | no uncaught page errors in the timeline/comparison report | ✅ |
| storage (W16) | real (mock) mode stored this session's hourly rate (numbers only) | ✅ |
| storage (W16) | clear-stored button empties the saved numbers | ✅ |
| storage (W16) | first record (nothing stored) shows "no earlier sessions" guidance | ✅ |
| storage (W16) | no uncaught page errors in the storage/empty-state flow | ✅ |
| real fields (W17) | comparison renders the server trend sentence (`report.trend.line_*`) | ✅ |
| real fields (W17) | mock mode stored this session's rate; "Example data" label NOT shown | ✅ |
| real fields (W17) | no uncaught page errors in the real-trend flow | ✅ |
| anon id (W17) | live mode sends `X-Anon-Id` (32-hex) and `X-Api-Key` on the service probe | ✅ |
| anon id (W17) | the anon id persists in localStorage (numbers-only continuity) | ✅ |
| anon id (W17) | clearing saved numbers re-issues a NEW anon id | ✅ |
| demo strip (W17) | demo strip does not overlap the comparison card's example note | ✅ |
| short session (W19) | rate null + 2 events → draws a bar + a "N bad-posture moment(s)" count sentence | ✅ |
| short session (W19) | zero-event short session → "no bad posture detected", no bars | ✅ |
| short session (W19) | short session + earlier records → "too short to compare" + earlier bars only (today not fabricated) | ✅ |
| short session (W19) | no uncaught page errors | ✅ |
| posture buddy (W10) | 3D/2D init, pose track, exaggeration 1.5×, rewind scrub | ✅ (10 checks) |
| sitting buddy (W14) | parts match the active render mode (3D figure or 2D fallback) + triangle budget ≤ 4000 when 3D | ✅ |
| sitting buddy (W14) | honesty line shown: head+hand measured, neck+torso estimated, no legs | ✅ |
| sitting buddy (W14) | accessibility: canvas role=img with a live aria-label (either mode) | ✅ |
| sitting buddy (W14) | measured drink event raises the right arm, then it falls | ✅ |
| sitting buddy (W14) | forward-head leans the estimated torso; aria names it an estimate | ✅ |
| sitting buddy (W14) | low confidence holds the figure still ("tracking unsure") | ✅ |
| sitting buddy (W14) | good-posture ghost toggles; keyboard rotate; no console errors | ✅ |
| sitting buddy (W14) | mobile 390px: figure + honesty line visible, no h-scroll | ✅ |
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
report. **Hard (non-contrast serious/critical) violations: 0. Contrast advisories: 0.**

| Screen | Hard violations | Contrast advisories |
|---|---|---|
| start | 0 | 0 |
| privacy-modal | 0 | 0 |
| run | 0 | 0 |
| run + agent panel | 0 | 0 |
| report | 0 | 0 |

Notes recorded as-is:
- The scan waits for each screen's fade-in to settle (opacity ≈ 1) before measuring.
  Measuring mid-animation makes axe read the body gradient through the still-transparent
  card and report a *false* low-contrast; waiting removes that.
- Position-fixed pills (`#demo-corner`, `#toast-host`) are hidden during the scan because,
  when they overlap flow text, axe cannot resolve the real background and falls back to
  white.
- The footer `<span data-i18n="discardNote">` contrast advisory seen through W14–W16 is
  **resolved in W17**: the footer now has a solid `background: var(--bg)` (and its own
  stacking context) so axe can always resolve the background instead of falling back to
  white, and the text colour was brightened to `#c3d0e2`. All five screens now report 0
  advisories as well as 0 hard violations.

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

## 3c. W14 sitting posture buddy (measured vs estimated)

The posture buddy was reworked from a sphere+capsule into a low-poly **seated upper-body
figure** (head, neck, level shoulders, chest/belly, upper arms, forearms, hands at a simple
desk; **legs not drawn**). Honesty is the point and is enforced in code + tests:

- We MEASURE only the head angles (`overlay.pose` yaw/pitch/roll/depth) + the `drink` event.
  The neck, torso and arms are a **model estimate** produced by the pure `buddy-kinematics.js`
  (`estimated: true` on every output), unit-tested (`npm run test:unit`, 6/6).
- A panel line states it on screen (EN/KO): *"Head and hand are measured; neck and torso are a
  model estimate. Legs are not drawn."* The aria state appends *"— torso is estimated"* when
  the figure leans, so a screen-reader user hears the distinction too (not visual-only).
- The head follows the measured angles (1.5× exaggerated, clamped); `depth>1` leans the
  estimated torso (capped 18°) and pushes the head forward; `roll` tilts head + upper neck only
  (shoulders stay level — shoulder tilt is not measured); the measured drink event raises the
  right arm toward the mouth over ~1.5s. Low confidence holds the last stable rig.
- Low-poly: ≈ 3.2k triangles (≤ 4k budget), vendored three.js (no new bundle), hand-rolled
  rotation, 30fps cap, breathing idle off under `prefers-reduced-motion`, 2D fallback intact.
- Ghost (faint sky-blue good-posture outline), 3-axis rotation, session rewind, and the demo
  fixture (now with a drink span) all carry over. e2e group "sitting buddy (W14)" (§1) plus the
  unit tests cover parts, triangle budget, the honesty line, the drink arm, the estimated lean,
  the low-confidence hold, ghost, keyboard rotation, and the mobile 390px layout.

### 3c-flaky. W15 stabilization (intermittent e2e failure — recorded, not hidden)

**Symptom.** `npm run e2e` passed 59/60 about once per ~10–20 runs; otherwise 60/60.

**Failing check (named).** `sitting buddy (W14) › figure has the sitting upper-body parts` —
error `2D fallback should report head2d (got head,neck,shoulders,chest,rightArm,leftArm,hand,desk)`.

**Root cause (two parts).**
1. *Test assumption.* The check read `buddyIs3D()` and `buddyParts()` in two separate
   `page.evaluate` round-trips and branched on the first; under software GL (swiftshader) the
   buddy sometimes initialises in its **by-design 2D fallback**, so a mode read that disagreed
   with the parts read tripped the assertion. The 2D fallback is intended behaviour, not an app
   bug — the test was mode-naive.
2. *A real context leak in our code.* `_webglOK()` probed support by creating a throwaway
   `<canvas>` and getting a WebGL context **without releasing it**. Under software GL's small
   context budget, these leaked probe contexts (run buddy + report buddy) could make the real
   `WebGLRenderer` fail to initialise and fall back to 2D more often than necessary.

**Fix.**
- Test: read `{is3d, parts, tris}` **atomically in one `page.evaluate`** and assert per mode —
  3D ⇒ the upper-body parts + triangle budget ≤ 4000; 2D ⇒ the `head2d` icon. The honesty line
  and the `role="img"` + live `aria-label` accessibility are asserted **in both modes**.
- App: `_webglOK()` now loses its probe context (`WEBGL_lose_context`), and `dispose()` calls
  `renderer.forceContextLoss()` so a following buddy can get a context. The per-frame render is
  wrapped in try/catch so a transient GL hiccup skips a frame instead of surfacing as an
  uncaught page error. Buddy-ready waits widened 6s→10s for headroom under CPU contention.
- Converted a few fixed `waitForTimeout`+assert spots (forward-head aria, low-conf hold) to
  **state-based** `waitForFunction` waits.

**Result.** `npm run e2e` ran **15× consecutively with 0 failures** after the fix (unit 6/6,
axe 0 hard). The e2e count stays 60 (the standalone triangle check folded into the atomic parts
check; a role/aria accessibility check was added).

## 3d. W16 alert calming + posture-record timeline + earlier-session comparison

- **Quiet mode (default ON).** The run screen opens with a *Quiet* toggle on: no toast, no
  sound, no flashing — just a calm status chip ("Quiet · N posture note(s)"). Posture is still
  recorded; held-back nudges are counted on the chip. Turning Quiet off opts into gentle nudge
  toasts, and even then the alert queue is **capped to one** nudge toast; a same-kind nudge
  during cooldown merges as "+N more" instead of stacking. A human-in-the-loop confirm prompt
  is still shown (it needs an answer) and is never evicted by the cap.
- **Posture record (timeline).** The report shows bad-posture counts (forward-head + head-tilt)
  per **5 / 10 / 30 / 60-minute** slice as an orange bar chart, with an hourly-rate summary
  line, a tab per slice, a "show as table" accessible fallback, and a "session too short" note
  for slices with no data. Chart is `role="img"` with a full-text `aria-label` (colour is not
  the only signal).
- **Earlier-session comparison.** A small per-hour-rate bar chart across recent sessions with
  an observational trend sentence (improving / same / worsening / na). Demo mode shows sample
  sessions under an explicit **"Example data"** label and never writes to storage.

## 3e. W17 real server fields + anonymous continuity + first-screen clarity

- **Real contract wired.** The report now reads the deployed shape (verified against the local
  service, §5): `/end` → `report.trend` (`direction`, `today_rate`, `baseline_rate`, `n`,
  `line_en`, `line_ko`) and `GET /v1/summary` → `history` (most-recent ≤5, **oldest-first**,
  each carrying `timeline.per_hour_rate`). The W16 placeholder fields (`compare.latest`,
  `earlier_mean`, `history[].this_session`) were removed from `mock.js` / `demo.js` / `app.js`;
  the mock + demo now return the same shape as the server, and the trend sentence shown is the
  server's ready-made localized `line_en` / `line_ko`.
- **Anonymous id.** Live mode sends `X-Anon-Id` (a 32-hex random token in `localStorage`, with a
  `crypto.getRandomValues` fallback) on every request so the server links a user's daily
  summaries without any login or PII. Server history is the source of truth; local stored
  numbers are only a fallback when the server returns none (demo never stores). "Clear saved
  numbers" wipes the stored numbers **and** the anon id (a new id is issued next request).
  CORS on the service allows `X-Anon-Id` (confirmed by a real preflight, §5).
- **First-screen clarity.** The start screen leads with a one-sentence value + what it won't do
  ("frames … thrown away instantly, never recorded"); the **Demo (no camera, no key)** card is
  first and labelled as the instant, keyless path.

## 3f. W18 live two-session check (real local service, fake camera)

Ran the full **Live** path twice in the **same browser context** against the real local
service (`scripts/run_local.sh`, dummy key, Playwright fake camera), screenshotting the
report's posture-record and comparison cards each time:
`docs/screenshots/w18-live-report-{1,2}-{timeline,comparison}.png`.

Recorded **as-is** (both sessions, 0 uncaught page errors, anon id persisted across both):

- Each session was only ~11 s (a quick fake-camera run), so `timeline.per_hour_rate` is
  `null` (the <10-min rule) and the posture-record card honestly shows *"Session too short to
  estimate an hourly rate"* + *"Not enough data yet"* — no fabricated bars.
- The comparison card on the 2nd run shows the server trend `direction: "na"` with its line
  *"No earlier sessions to compare with yet."* **Why, confirmed against the service:**
  `GET /v1/summary` *did* return a `history` entry for session 1 (the anon id linked them —
  numbers only, `duration_s≈11`, `timeline` present), but that entry's `per_hour_rate` is
  `null` (short session) and the fake camera produced 0 forward-head/head-tilt events, so there
  is no per-hour rate to chart or compare. This is correct, honest behaviour: **history is
  linked and returned, but a short, event-free session yields no plottable trend.** A real
  ≥10-min session with posture events would populate both the timeline bars and the trend.
- The live path otherwise worked end to end: Live gate → key → calibrate → run (overlay +
  metrics from the real OpenCV backend, `stubs:false`) → End → report, with no demo
  strip/badge (honesty) and no console errors.

**W18 polish fix (1).** On a short session the posture-record card used to leave a tall empty
bar area above the "not enough data" note; the chart box is now collapsed (`hidden`) when a
slice has no data, so the card reads cleanly. Other minor items noted but left as-is: the live
~11 s fake-camera run can't exercise a real trend (needs a ≥10-min session), and the comparison
"na" copy is intentionally the server's wording.

## 3g. W19 short session still shows a meaningful posture record

W18's live run surfaced a real usability gap: an ~11 s session has `per_hour_rate: null` (the
server withholds an hourly rate under 10 minutes — not statistically meaningful), so the
posture-record card only said *"session too short"* and looked empty. W19 keeps the server's
10-minute rule but **shows the raw count**:

- **Timeline.** Even with `per_hour_rate` null, if `timeline.bad_posture` has events the bars are
  drawn (5-min slices, as far as the session reached), and the summary line reads *"This session
  (N min): M bad-posture moment(s). Hourly rate shows from 10 minutes."* (session length from
  `summary.duration_s`). Zero events → *"No bad posture detected this session."* and the empty
  chart stays collapsed. The hourly-rate wording ("About N per hour") is unchanged for ≥10-min
  sessions.
- **Comparison.** When this session's rate is null but the history has ≥1 session with a rate,
  the card shows *"This session is still short to compare. Use it for 10+ minutes to compare with
  your earlier records."* and draws **only the earlier bars** — today's value is never fabricated.
  First-record (no earlier rates) still shows the "no earlier sessions" guidance.
- Demo data unchanged. EN/KO copy in `i18n.js`. Covered by the "short session posture record
  (W19)" e2e group (§1, 4 checks) and screenshots `docs/screenshots/w19-{short-count,no-events,
  compare-tooshort,short-count-mobile}.png`; axe stays 0/0 and 390px has no horizontal scroll.

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
Last `live.mjs` run against a local `uvicorn nunchi.service.app` on `:8000` with a **Playwright
fake camera**: **7 / 7 passed, 0 failed.** (W18 additionally ran two full live sessions through
the report screen against `scripts/run_local.sh` — see §3f.)

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
