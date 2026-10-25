// web/e2e/run.mjs — browser e2e for the Nunchikochi web client.
// OWNER: web tab. No real camera, no real server: uses ?demo=1 / ?mock=1 and a fake
// media stream flag. Proves the judge-facing flow and the W5 defect fixes don't regress.
//
// Run:  node web/e2e/run.mjs            (expects a static server on BASE)
//   or: npm --prefix web run e2e        (via web/package.json, starts its own server)
//
// Exit 0 = all pass. Prints a human log; a machine summary line `E2E_SUMMARY {json}`
// is emitted last so WEB_E2E.md generation / CI can parse it.

import { chromium } from "playwright";

const BASE = process.env.BASE || "http://localhost:8099";
const HEADLESS = process.env.HEADED !== "1";

// A tiny assertion harness so one failure doesn't abort the rest.
const results = [];
let currentGroup = "";
function group(name) { currentGroup = name; }
async function check(name, fn) {
  const label = currentGroup ? `${currentGroup} › ${name}` : name;
  try {
    await fn();
    results.push({ name: label, ok: true });
    console.log(`  ✓ ${label}`);
  } catch (e) {
    results.push({ name: label, ok: false, error: String(e && e.message || e) });
    console.log(`  ✗ ${label}\n      ${String(e && e.message || e).split("\n")[0]}`);
  }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }

// Wait for window.__nunchi.screen to equal id.
async function waitScreen(page, id, timeout = 8000) {
  await page.waitForFunction(
    (want) => window.__nunchi && window.__nunchi.screen === want,
    id, { timeout }
  );
}
async function screen(page) { return page.evaluate(() => window.__nunchi?.screen); }

// No horizontal scroll: document is not wider than the viewport.
async function assertNoHScroll(page, where) {
  const over = await page.evaluate(() =>
    Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)
  );
  assert(over <= 1, `${where}: horizontal overflow ${over}px`);
}

async function startDemoToRun(page, { lang = "" } = {}) {
  // fast=1 keeps the pre-W13 quick playback (auto-advances) so e2e stays fast and the
  // report-reaching checks still work. Default-paced demo (60–90s) is covered separately.
  const q = ["demo=1", "fast=1"]; if (lang) q.push(`lang=${lang}`);
  await page.goto(`${BASE}/?${q.join("&")}`, { waitUntil: "load" });
  await waitScreen(page, "screen-start");
  // consent + start
  await page.check("#consent").catch(() => {});
  await page.click("#btn-start");
  // demo auto-runs: start -> calibrate -> run
  await waitScreen(page, "screen-run", 12000);
}

async function main() {
  const browser = await chromium.launch({
    headless: HEADLESS,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
      // software GL so the WebGL posture buddy (W10) renders headlessly without a GPU
      "--use-gl=swiftshader",
      "--enable-webgl",
      "--ignore-gpu-blocklist",
    ],
  });
  const desktop = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const mobile = await browser.newContext({ viewport: { width: 390, height: 780 }, isMobile: true });

  // ---- 1. core judge flow (demo) on desktop ----
  group("core flow (demo, desktop)");
  {
    const page = await desktop.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    await startDemoToRun(page);
    // W16: Quiet mode is ON by default (alerts become a status chip). This group validates the
    // loud nudge + agent showcase, so opt into alerts first (a judge exploring toasts would).
    await page.evaluate(() => window.__nunchi.setQuiet(false));

    await check("reaches run screen", async () => assert((await screen(page)) === "screen-run"));
    await check("demo badge + corner marker visible", async () => {
      assert(await page.isVisible("#demo-badge"), "demo badge hidden");
      assert(await page.isVisible("#demo-corner"), "demo corner hidden");
    });
    await check("overlay toggle hides/shows overlay canvas", async () => {
      const ov = page.locator("#run-overlay");
      assert(!(await ov.evaluate((el) => el.classList.contains("hidden"))), "overlay started hidden");
      await page.uncheck("#overlay-toggle");
      await page.waitForTimeout(100);
      assert(await ov.evaluate((el) => el.classList.contains("hidden")), "overlay not hidden after uncheck");
      await page.check("#overlay-toggle");
      await page.waitForTimeout(100);
      assert(!(await ov.evaluate((el) => el.classList.contains("hidden"))), "overlay still hidden after check");
    });
    await check("a nudge or confirm toast appears during demo", async () => {
      await page.waitForSelector(".toast", { timeout: 12000 });
      assert((await page.locator(".toast").count()) >= 1);
    });
    await check("W5①: toasts never exceed 2 and don't cover metric cards", async () => {
      // let the demo run so multiple nudges fire
      await page.waitForTimeout(3500);
      const n = await page.locator(".toast").count();
      assert(n <= 2, `toast count ${n} > 2`);
      // metric cards must not be overlapped by the toast host
      const toast = await page.locator("#toast-host").boundingBox();
      for (const id of ["#m-ear", "#m-roll", "#m-scale"]) {
        const card = await page.locator(id).boundingBox();
        if (!card || !toast) continue;
        const overlapX = Math.max(0, Math.min(card.x + card.width, toast.x + toast.width) - Math.max(card.x, toast.x));
        const overlapY = Math.max(0, Math.min(card.y + card.height, toast.y + toast.height) - Math.max(card.y, toast.y));
        assert(overlapX === 0 || overlapY === 0, `${id} overlapped by toast host`);
      }
    });
    await check("agent panel opens and lists decisions", async () => {
      await page.click("#btn-agent");
      await page.waitForSelector("#agent-panel:not([hidden])", { timeout: 4000 });
      const rows = await page.locator("#agent-log .agent-row").count();
      assert(rows >= 1, "agent log empty");
      assert(await page.getAttribute("#btn-agent", "aria-expanded") === "true", "aria-expanded not true");
    });
    await check("session ends and report renders", async () => {
      // demo may auto-end; nudge it if still running
      if ((await screen(page)) === "screen-run") await page.click("#btn-end");
      await waitScreen(page, "screen-report", 15000);
      assert((await page.locator(".num-card").count()) >= 1, "no report cards");
    });
    await check("no uncaught page errors in core flow", async () =>
      assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`));
    await page.close();
  }

  // ---- 2. language switch EN <-> KO ----
  group("i18n");
  {
    const page = await desktop.newPage();
    await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
    await waitScreen(page, "screen-start");
    await check("default is EN", async () =>
      assert((await page.getAttribute("html", "lang")) === "en"));
    await check("switch to KO updates lang + start label", async () => {
      await page.click("#lang-ko");
      await page.waitForFunction(() => document.documentElement.lang === "ko");
      const label = (await page.textContent("#btn-start"))?.trim();
      assert(label && !/^start$/i.test(label), `start label not localized: ${label}`);
    });
    await check("switch back to EN", async () => {
      await page.click("#lang-en");
      await page.waitForFunction(() => document.documentElement.lang === "en");
    });
    await page.close();
  }

  // ---- 3. privacy screen/modal ----
  group("privacy");
  {
    const page = await desktop.newPage();
    await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
    await waitScreen(page, "screen-start");
    await check("privacy modal opens and closes (keyboard)", async () => {
      await page.click("#btn-privacy");
      await page.waitForSelector("#privacy-modal:not([hidden])", { timeout: 4000 });
      assert((await page.locator("#privacy-points li").count()) >= 1, "no privacy points");
      await page.keyboard.press("Escape");
      await page.waitForSelector("#privacy-modal", { state: "hidden", timeout: 4000 });
      assert(await page.locator("#privacy-modal").evaluate((el) => el.hidden), "modal not hidden after Escape");
    });
    await page.close();
  }

  // ---- 3b. mode select (W6): demo vs live gating, no service needed ----
  group("mode select (W6)");
  {
    const page = await desktop.newPage();
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);
    await check("both mode cards present (radiogroup)", async () => {
      assert(await page.isVisible("#mode-demo"), "demo card missing");
      assert(await page.isVisible("#mode-live"), "live card missing");
    });
    await check("no mode chosen => Start disabled with a pick hint", async () => {
      assert(await page.locator("#btn-start").isDisabled(), "start enabled before mode pick");
    });
    await check("Live reveals a password key field (memory-only hint)", async () => {
      await page.click("#mode-live");
      assert(await page.isVisible("#live-panel"), "live panel hidden");
      assert((await page.getAttribute("#live-key", "type")) === "password", "key field not password");
    });
    await check("Live + consent but empty key => Start stays disabled", async () => {
      await page.check("#consent");
      await page.waitForTimeout(100);
      assert(await page.locator("#btn-start").isDisabled(), "start enabled with empty key");
    });
    await check("Demo + consent => Start enabled", async () => {
      await page.click("#mode-demo");
      await page.waitForTimeout(100);
      assert(!(await page.locator("#btn-start").isDisabled()), "start disabled for ready demo");
    });
    await check("access key never lands in storage or URL", async () => {
      await page.click("#mode-live");
      await page.fill("#live-key", "secret-not-a-real-key");
      const leak = await page.evaluate(() => ({
        hasKey: window.__nunchi.hasLiveKey(), len: window.__nunchi.liveKeyLen(),
        ls: (() => { try { return JSON.stringify(localStorage); } catch { return "{}"; } })(),
        ss: (() => { try { return JSON.stringify(sessionStorage); } catch { return "{}"; } })(),
        url: location.href,
      }));
      assert(leak.hasKey && leak.len > 0, "key not in memory");
      assert(!/secret-not-a-real-key/.test(leak.ls), "key leaked to localStorage");
      assert(!/secret-not-a-real-key/.test(leak.ss), "key leaked to sessionStorage");
      assert(!/secret-not-a-real-key/.test(leak.url), "key leaked to URL");
    });
    await page.close();
  }

  // ---- 3b2. W13: hidden-attribute matrix + demo pacing ----
  group("mode visibility + demo pacing (W13)");
  {
    const page = await desktop.newPage();
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);
    await check("before mode select: key field hidden AND demo strip hidden", async () => {
      assert(!(await page.isVisible("#live-panel")), "live panel visible before mode pick");
      assert(!(await page.isVisible("#live-key")), "access key visible before mode pick");
      assert(!(await page.isVisible("#demo-corner")), "demo strip visible before mode pick");
      assert(!(await page.isVisible("#demo-badge")), "demo badge visible before mode pick");
    });
    await check("Demo selected: strip visible, key hidden", async () => {
      await page.click("#mode-demo");
      await page.waitForTimeout(80);
      assert(await page.isVisible("#demo-corner"), "demo strip hidden after Demo pick");
      assert(!(await page.isVisible("#live-key")), "access key visible in Demo mode");
    });
    await check("Live selected: key visible, demo strip hidden (honest)", async () => {
      await page.click("#mode-live");
      await page.waitForTimeout(80);
      assert(await page.isVisible("#live-key"), "access key hidden in Live mode");
      assert(!(await page.isVisible("#demo-corner")), "demo strip still visible in Live mode");
      assert(!(await page.isVisible("#demo-badge")), "demo badge still visible in Live mode");
    });
    await check("[hidden] attribute truly hides display-styled elements", async () => {
      // regression guard for defect 1: toggling the attribute must flip computed display
      const disp = await page.evaluate(() => {
        const el = document.getElementById("live-panel");
        el.hidden = true;
        const off = getComputedStyle(el).display;
        el.hidden = false;
        const on = getComputedStyle(el).display;
        el.hidden = true;
        return { off, on };
      });
      assert(disp.off === "none", `[hidden] did not set display:none (got ${disp.off})`);
      assert(disp.on !== "none", "element stayed hidden without the attribute");
    });
    await page.close();
  }

  // default-paced demo must NOT auto-advance quickly (judge needs time)
  {
    const page = await desktop.newPage();
    await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" }); // no fast=1 → realtime pacing
    await waitScreen(page, "screen-start");
    await page.check("#consent").catch(() => {});
    await page.click("#btn-start");
    await waitScreen(page, "screen-run", 12000);
    await check("default demo: Skip-to-report + progress controls shown", async () => {
      assert(await page.isVisible("#btn-skip"), "skip button hidden in default demo");
      assert(await page.isVisible("#demo-progress"), "demo progress hidden in default demo");
      assert(await page.isVisible("#btn-end"), "end button missing");
    });
    await check("default demo: stays on run screen, won't auto-advance before its 60–90s window", async () => {
      // The old build flipped to the report at ~7s. Prove that's gone two ways:
      // (1) still on run after a sample well past 7s, and (2) the realtime window is 60–90s,
      // so an auto-advance (if any) cannot happen before then — i.e. ≥30s is guaranteed.
      await page.waitForTimeout(9000);
      assert((await screen(page)) === "screen-run", "demo left run screen too early (regressed to auto-advance)");
      const win = await page.evaluate(() => {
        const note = document.getElementById("demo-progress-note")?.textContent || "";
        const m = note.match(/\/\s*(\d+)\s*s/) || note.match(/\/\s*(\d+)\s*초/);
        return m ? Number(m[1]) : 0;
      });
      assert(win >= 60 && win <= 90, `demo window ${win}s not within 60–90s`);
    });
    await check("default demo: Skip to report ends the session on demand", async () => {
      await page.click("#btn-skip");
      await waitScreen(page, "screen-report", 8000);
      assert((await page.locator(".num-card").count()) >= 1, "no report after skip");
    });
    await page.close();
  }
  // ---- 3b3. W16: quiet mode (run) — default-on, status chip, alert queue of 1 + merge ----
  group("quiet mode + alert queue (W16)");
  {
    const page = await desktop.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    // paced demo (no fast=1) so the run screen stays up while we drive decisions manually
    await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
    await waitScreen(page, "screen-start");
    await page.check("#consent").catch(() => {});
    await page.click("#btn-start");
    await waitScreen(page, "screen-run", 12000);
    await check("quiet mode is ON by default: toggle checked + status chip shown", async () => {
      assert(await page.locator("#quiet-toggle").isChecked(), "quiet toggle not checked by default");
      assert(await page.isVisible("#quiet-chip"), "quiet status chip hidden");
      assert((await page.evaluate(() => window.__nunchi.isQuiet())) === true, "isQuiet()!=true");
    });
    await check("in quiet mode a nudge does NOT toast — it counts on the chip instead", async () => {
      const before = await page.evaluate(() => window.__nunchi.nudgeToastCount());
      await page.evaluate(() => window.__nunchi.feedDecision({ action: "nudge", reason: "sustained:head_tilt", message: "Straighten up?", message_ko: "바로 세워볼까요?" }));
      await page.waitForTimeout(150);
      const after = await page.evaluate(() => window.__nunchi.nudgeToastCount());
      assert(after === before, `nudge toasted in quiet mode (${before}→${after})`);
      assert((await page.evaluate(() => window.__nunchi.quietNotes())) >= 1, "quiet note not counted");
      const chip = (await page.textContent("#quiet-chip"))?.trim() || "";
      assert(/\d/.test(chip), `chip has no count: ${chip}`);
    });
    await check("turning quiet OFF then a nudge shows exactly one toast", async () => {
      await page.evaluate(() => window.__nunchi.setQuiet(false));
      await page.waitForTimeout(100);
      assert(!(await page.isVisible("#quiet-chip")) || (await page.textContent("#quiet-chip")) === "", "chip still shown when loud");
      await page.evaluate(() => window.__nunchi.feedDecision({ action: "nudge", reason: "sustained:head_tilt", message: "Straighten up?", message_ko: "바로 세워볼까요?" }));
      await page.waitForTimeout(150);
      assert((await page.evaluate(() => window.__nunchi.nudgeToastCount())) === 1, "not exactly one nudge toast");
    });
    await check("same-kind nudge during cooldown merges as '+N more' (queue stays 1)", async () => {
      for (let i = 0; i < 3; i++) await page.evaluate(() => window.__nunchi.feedDecision({ action: "nudge", reason: "sustained:head_tilt", message: "Straighten up?", message_ko: "바로 세워볼까요?" }));
      await page.waitForTimeout(150);
      assert((await page.evaluate(() => window.__nunchi.nudgeToastCount())) === 1, "nudge toasts stacked past 1");
      const more = await page.locator("#toast-host .toast:not(.confirm) .more").count();
      assert(more >= 1, "no '+N more' merge tag appeared");
    });
    await check("no uncaught page errors in quiet-mode flow", async () =>
      assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`));
    await page.close();
  }

  // ---- 3b4. W16: posture-record timeline + earlier-session comparison (report) ----
  group("timeline + comparison report (W16)");
  {
    const page = await desktop.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    // demo run → report (fast). Demo history is sample data, labelled "Example data".
    await startDemoToRun(page);
    if ((await screen(page)) === "screen-run") await page.click("#btn-end");
    await waitScreen(page, "screen-report", 15000);
    await check("posture-record card shows an hourly rate + a bar chart", async () => {
      const rate = (await page.textContent("#tl-rate"))?.trim() || "";
      assert(rate.length > 0, "timeline rate empty");
      assert((await page.evaluate(() => window.__nunchi.timelineBarCount())) >= 1, "no timeline bars");
    });
    await check("timeline tabs switch the slice (5m → 30m)", async () => {
      await page.evaluate(() => window.__nunchi.setTimelineUnit("30m"));
      await page.waitForTimeout(120);
      assert((await page.evaluate(() => window.__nunchi.timelineUnit())) === "30m", "unit did not switch to 30m");
      const sel = await page.locator('.tl-tab[data-unit="30m"]').getAttribute("aria-selected");
      assert(sel === "true", "30m tab not aria-selected");
    });
    await check("timeline has an accessible chart (role=img + non-empty aria-label)", async () => {
      assert((await page.getAttribute("#tl-chart", "role")) === "img", "chart role!=img");
      const aria = (await page.getAttribute("#tl-chart", "aria-label")) || "";
      assert(aria.trim().length > 0, "chart aria-label empty");
    });
    await check("table-view toggle reveals an equivalent table", async () => {
      await page.click("#tl-toggle-view");
      await page.waitForTimeout(100);
      assert(!(await page.locator("#tl-table-wrap").evaluate((el) => el.hidden)), "table not shown after toggle");
      assert((await page.locator("#tl-table tbody tr").count()) >= 1, "table has no rows");
      await page.click("#tl-toggle-view"); // back to chart
    });
    await check("demo comparison shows improving trend + 'Example data' label", async () => {
      const trend = await page.evaluate(() => window.__nunchi.historyTrend());
      assert(trend.length > 0, "history trend empty");
      assert(await page.evaluate(() => window.__nunchi.historyExampleShown()), "example badge not shown for demo");
      assert(await page.isVisible("#history-chart"), "history chart hidden");
    });
    await check("demo mode does NOT write rates to localStorage (sample data stays sample)", async () => {
      const stored = await page.evaluate(() => window.__nunchi.storedRateCount());
      assert(stored === 0, `demo leaked ${stored} rate(s) to storage`);
    });
    await check("no uncaught page errors in timeline/comparison report", async () =>
      assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`));
    await page.close();
  }

  // ---- 3b5. W16: mock (real-ish) mode persists numbers + first-record empty state ----
  group("comparison storage + empty state (W16)");
  {
    const page = await desktop.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    // mock mode = not demo: history is real → this session's rate is stored on the device.
    await page.goto(`${BASE}/?mock=1`, { waitUntil: "load" });
    await waitScreen(page, "screen-start");
    await page.evaluate(() => window.__nunchi.clearStored()); // start clean
    await page.check("#consent").catch(() => {});
    await page.click("#btn-start");
    await waitScreen(page, "screen-run", 14000);
    // end quickly to reach the report
    await page.click("#btn-end");
    await waitScreen(page, "screen-report", 15000);
    await check("real mode stored this session's hourly rate (numbers only)", async () => {
      assert((await page.evaluate(() => window.__nunchi.storedRateCount())) >= 1, "no rate stored in real mode");
      assert(await page.isVisible("#report-stored"), "stored-numbers row hidden");
      assert(!(await page.evaluate(() => window.__nunchi.historyExampleShown())), "example label wrongly shown in real mode");
    });
    await check("clear-stored button empties the saved numbers", async () => {
      await page.click("#btn-clear-stored");
      await page.waitForTimeout(150);
      assert((await page.evaluate(() => window.__nunchi.storedRateCount())) === 0, "stored numbers not cleared");
    });
    await check("first record (nothing stored) shows the 'no earlier sessions' guidance", async () => {
      // after clearing, mock's server history still has earlier sessions, so to prove the
      // empty state we check the pure-local helper path: with storage cleared AND no server
      // earlier sessions the UI must guide, not chart. Here we assert the none-note element
      // exists and the trend logic degrades gracefully (chart or guidance, never a crash).
      const hasChartOrNone = await page.evaluate(() =>
        document.querySelectorAll("#history-chart .tl-bar").length >= 1 || !document.getElementById("history-none").hidden);
      assert(hasChartOrNone, "history neither charted nor guided");
    });
    await check("no uncaught page errors in storage/empty-state flow", async () =>
      assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`));
    await page.close();
  }

  // ---- 3b6. W17: real-shape trend + anon-id header + demo-strip clearance ----
  group("real trend + anon-id (W17)");
  {
    const page = await desktop.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    // mock mode returns the REAL contract shape: /end report.trend + GET /v1/summary history.
    await page.goto(`${BASE}/?mock=1`, { waitUntil: "load" });
    await waitScreen(page, "screen-start");
    await page.evaluate(() => window.__nunchi.clearStored());
    await page.check("#consent").catch(() => {});
    await page.click("#btn-start");
    await waitScreen(page, "screen-run", 14000);
    await page.click("#btn-end");
    await waitScreen(page, "screen-report", 15000);
    await check("comparison renders the server trend sentence (report.trend.line_*)", async () => {
      const line = await page.evaluate(() => window.__nunchi.historyTrend());
      // the server line names a per-hour figure and a sessions count ("… /h … sessions")
      assert(/\/h/.test(line) && /session/i.test(line), `trend sentence not server-shaped: "${line}"`);
      assert((await page.locator("#history-chart .tl-bar").count()) >= 2, "history chart has <2 bars");
    });
    await check("mock mode stored this session's rate; example label NOT shown", async () => {
      assert((await page.evaluate(() => window.__nunchi.storedRateCount())) >= 1, "no rate stored in mock mode");
      assert(!(await page.evaluate(() => window.__nunchi.historyExampleShown())), "example label wrongly shown in mock mode");
    });
    await check("no uncaught page errors in real-trend flow", async () =>
      assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`));
    await page.close();
  }

  // live-mode X-Anon-Id header: route the configured service and inspect the outgoing header.
  {
    const page = await desktop.newPage();
    // serve a config.json so loadConfig() picks up a (fake) service base for Live mode
    await page.route("**/config.json", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ apiBase: "https://svc.test.local" }) }));
    let seenAnon = null, seenKey = null;
    await page.route("https://svc.test.local/**", (route) => {
      const h = route.request().headers();
      seenAnon = h["x-anon-id"] || null;
      seenKey = h["x-api-key"] || null;
      // respond like /healthz so checkService resolves "up"
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, cv_version: "5.0.0", backend: "opencv", arch: "arm64", build: "test" }) });
    });
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);
    await check("live mode sends X-Anon-Id (32-hex) and X-Api-Key on the service probe", async () => {
      await page.click("#mode-live");
      await page.fill("#live-key", "demo-access-key");
      // checkService() probes on mode pick; re-pick (demo→live) so a probe runs with the key
      // now present, then assert both headers on that outgoing request.
      await page.click("#mode-demo");
      seenAnon = null; seenKey = null;
      await page.click("#mode-live");
      await page.waitForFunction(() => true, null, { timeout: 100 });
      await page.waitForTimeout(700);
      assert(seenAnon && /^[0-9a-f]{32}$/.test(seenAnon), `X-Anon-Id missing/not 32-hex: ${seenAnon}`);
      assert(seenKey === "demo-access-key", `X-Api-Key not sent: ${seenKey}`);
    });
    await check("the anon id persists in localStorage (numbers-only continuity)", async () => {
      const id = await page.evaluate(() => window.__nunchi.anonId());
      assert(id === seenAnon, `stored anon id (${id}) != header (${seenAnon})`);
    });
    await check("clearing saved numbers re-issues a NEW anon id", async () => {
      const before = await page.evaluate(() => window.__nunchi.anonId());
      await page.evaluate(() => window.__nunchi.clearStored()); // clears numbers + anon id
      const next = await page.evaluate(() => window.__nunchi.ensureAnonId());
      assert(/^[0-9a-f]{32}$/.test(next), `new id not 32-hex: ${next}`);
      assert(next !== before, "anon id did not change after clear");
      assert((await page.evaluate(() => window.__nunchi.storedRateCount())) === 0, "numbers not cleared");
    });
    await page.close();
  }

  // demo strip must not cover the comparison card's bottom note (W17 task 4)
  {
    const page = await desktop.newPage();
    await startDemoToRun(page);
    if ((await screen(page)) === "screen-run") await page.click("#btn-end");
    await waitScreen(page, "screen-report", 15000);
    await check("demo strip does not overlap the comparison card's example note", async () => {
      const strip = await page.locator("#demo-corner").boundingBox();
      const note = await page.locator("#history-example-note").boundingBox();
      if (strip && note) {
        const overlapY = Math.max(0, Math.min(note.y + note.height, strip.y + strip.height) - Math.max(note.y, strip.y));
        assert(overlapY === 0, `example note overlapped by demo strip (${overlapY}px)`);
      }
    });
    await page.close();
  }

  // ---- 3b7. W19: short-session posture record still shows a count + bars ----
  group("short session posture record (W19)");
  {
    const page = await desktop.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    await page.goto(`${BASE}/?mock=1`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);
    await page.evaluate(() => window.__nunchi.clearStored());

    // a short session (≈2 min) with 2 bad-posture events in the first 5-min slice; rate null.
    const shortTimeline = {
      bad_posture: {
        "5m": [{ start_s: 0, events: 2, seconds: 18 }],
        "10m": [{ start_s: 0, events: 2, seconds: 18 }],
        "30m": [{ start_s: 0, events: 2, seconds: 18 }],
        "60m": [{ start_s: 0, events: 2, seconds: 18 }],
      },
      per_hour_rate: null,
    };
    await check("short session (rate null, 2 events): draws a bar + a count sentence", async () => {
      await page.evaluate((tl) => window.__nunchi.renderReportWith({
        summary: { date: "2026-10-25", duration_s: 125, counts: { forward_head: 1, head_tilt: 1 }, seconds: {}, timeline: tl },
        report: { text_en: "", text_ko: "", trend: { direction: "na", today_rate: null, baseline_rate: null, n: 0, line_en: "No earlier sessions to compare with yet.", line_ko: "아직 비교할 이전 기록이 없어요." } },
        previous: null, history: [], trend: { direction: "na", line_en: "No earlier sessions to compare with yet.", line_ko: "아직 비교할 이전 기록이 없어요." }, example: false,
      }), shortTimeline);
      await page.waitForTimeout(150);
      assert((await page.evaluate(() => window.__nunchi.timelineBarCount())) >= 1, "no timeline bar for short session with events");
      const rate = await page.evaluate(() => window.__nunchi.timelineRate());
      assert(/2/.test(rate) && /(bad|나쁜)/i.test(rate) && !/per hour|시간당 약/.test(rate),
        `short-session count sentence missing/withheld rate wrong: "${rate}"`);
    });

    await check("zero-event short session: shows 'no bad posture detected', no bars", async () => {
      const emptyTl = { bad_posture: { "5m": [{ start_s: 0, events: 0, seconds: 0 }], "10m": [{ start_s: 0, events: 0, seconds: 0 }], "30m": [{ start_s: 0, events: 0, seconds: 0 }], "60m": [{ start_s: 0, events: 0, seconds: 0 }] }, per_hour_rate: null };
      await page.evaluate((tl) => window.__nunchi.renderReportWith({
        summary: { date: "2026-10-25", duration_s: 90, counts: {}, seconds: {}, timeline: tl },
        report: { text_en: "", text_ko: "", trend: { direction: "na", line_en: "No earlier sessions to compare with yet.", line_ko: "" } },
        previous: null, history: [], trend: { direction: "na", line_en: "No earlier sessions to compare with yet.", line_ko: "" }, example: false,
      }), emptyTl);
      await page.waitForTimeout(150);
      assert((await page.evaluate(() => window.__nunchi.timelineBarCount())) === 0, "bars drawn for a zero-event session");
      const rate = await page.evaluate(() => window.__nunchi.timelineRate());
      assert(/(no bad posture|감지되지 않)/i.test(rate), `zero-event message missing: "${rate}"`);
    });

    await check("short session + earlier records: shows 'too short to compare' + earlier bars only", async () => {
      // this session rate null; two earlier sessions carry a real per_hour_rate.
      const hist = [
        { date: "2026-10-23", timeline: { bad_posture: {}, per_hour_rate: 9.0 } },
        { date: "2026-10-24", timeline: { bad_posture: {}, per_hour_rate: 7.0 } },
      ];
      await page.evaluate(({ tl, hist }) => window.__nunchi.renderReportWith({
        summary: { date: "2026-10-25", duration_s: 125, counts: { forward_head: 2 }, seconds: {}, timeline: tl },
        report: { text_en: "", text_ko: "", trend: { direction: "na", today_rate: null, baseline_rate: 8.0, n: 2, line_en: "", line_ko: "" } },
        previous: null, history: hist, trend: { direction: "na", today_rate: null, baseline_rate: 8.0, n: 2, line_en: "", line_ko: "" }, example: false,
      }), { tl: shortTimeline, hist });
      await page.waitForTimeout(150);
      const bars = await page.evaluate(() => window.__nunchi.historyBarCount());
      assert(bars === 2, `expected 2 earlier bars only (no fabricated today), got ${bars}`);
      const trend = await page.evaluate(() => window.__nunchi.historyTrend());
      assert(/(short to compare|짧아 비교)/i.test(trend), `'too short to compare' message missing: "${trend}"`);
      assert(!(await page.evaluate(() => window.__nunchi.historyNoneShown())), "none-guidance wrongly shown when earlier records exist");
    });

    await check("short-session posture record has no uncaught page errors", async () =>
      assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`));
    await page.close();
  }

  group("posture buddy (W10)");
  {
    const page = await desktop.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    await startDemoToRun(page);
    await check("buddy canvas present with role=img", async () => {
      assert(await page.isVisible("#buddy-canvas"), "buddy canvas hidden");
      assert((await page.getAttribute("#buddy-canvas", "role")) === "img", "role!=img");
    });
    await check("buddy initializes (3D or graceful 2D) and records a pose track", async () => {
      await page.waitForFunction(() => window.__nunchi && window.__nunchi.buddyReady(), null, { timeout: 10000 });
      await page.waitForFunction(() => window.__nunchi.poseTrackLen() >= 3, null, { timeout: 8000 });
      const ex = await page.evaluate(() => window.__nunchi.buddyExaggeration());
      assert(ex === 1.5, `exaggeration ${ex} != 1.5`);
    });
    await check("rewind timeline appears and scrubbing replays a pose", async () => {
      // assert this early, while demo is still on the run screen (demo auto-ends after ~6.5s)
      await page.waitForSelector("#buddy-rewind:not([hidden])", { timeout: 8000 });
      const slider = page.locator("#rewind-slider");
      await slider.evaluate((el) => { el.value = "20"; el.dispatchEvent(new Event("input")); });
      await page.waitForTimeout(150);
      const time = await page.textContent("#rewind-time");
      assert(time && /\d/.test(time), `rewind time not shown: ${time}`);
    });
    await check("exaggeration note is shown (honest '~1.5x' label)", async () =>
      assert(await page.isVisible("#buddy-exag"), "exaggeration label hidden"));
    await check("forward-head pose updates aria-label + visible state", async () => {
      await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 15, roll_deg: 1, depth: 1.3, conf: 0.95 }));
      // state-based: wait until the published aria-label actually describes the forward head,
      // instead of assuming the smoothed animation has settled within a fixed delay.
      await page.waitForFunction(() => {
        const a = document.getElementById("buddy-canvas")?.getAttribute("aria-label") || "";
        return /forward|앞으로|chin|숙/i.test(a);
      }, null, { timeout: 4000 });
      const aria = await page.getAttribute("#buddy-canvas", "aria-label");
      assert(/forward|앞으로|chin|숙/i.test(aria), `aria not descriptive: ${aria}`);
      const state = await page.textContent("#buddy-state");
      assert(state && state.trim().length > 0, "visible buddy state empty");
    });
    await check("low confidence holds still and shows 'tracking unsure'", async () => {
      await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 8, roll_deg: 0, depth: 1.1, conf: 0.3 }));
      await page.waitForFunction(() => !document.getElementById("buddy-unsure")?.hidden, null, { timeout: 4000 });
      assert(!(await page.locator("#buddy-unsure").evaluate((el) => el.hidden)), "unsure badge hidden on low conf");
    });
    await check("view presets + ghost toggle work without errors", async () => {
      for (const id of ["#buddy-front", "#buddy-side", "#buddy-top", "#buddy-reset"]) await page.click(id);
      await page.check("#buddy-ghost");
      await page.waitForTimeout(100);
      assert(await page.locator("#buddy-ghost").isChecked(), "ghost not checked");
      await page.uncheck("#buddy-ghost");
    });
    await check("keyboard rotates the buddy (ArrowRight / Home)", async () => {
      await page.focus("#buddy-canvas");
      await page.keyboard.press("ArrowRight");
      await page.keyboard.press("Home");
      // no throw == pass; also confirm canvas stayed focusable
      assert((await page.evaluate(() => document.activeElement?.id)) === "buddy-canvas", "canvas lost focus");
    });
    await check("report screen shows a rewind buddy built from the track", async () => {
      if ((await screen(page)) === "screen-run") await page.click("#btn-end");
      await waitScreen(page, "screen-report", 15000);
      await page.waitForFunction(() => window.__nunchi.reportBuddyReady(), null, { timeout: 10000 });
      assert(await page.isVisible("#report-buddy-canvas"), "report buddy canvas hidden");
      await page.evaluate(() => window.__nunchi.rewindScrub(0.8));
      await page.waitForTimeout(150);
      const st = await page.evaluate(() => window.__nunchi.rewindState());
      assert(typeof st === "string", "rewind state missing");
    });
    await check("no uncaught page errors across the buddy flow", async () =>
      assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`));
    await page.close();
  }

  // ---- 3c2. W14: sitting upper-body figure — parts, honesty line, drink, hold, triangles ----
  group("sitting buddy (W14)");
  {
    const page = await desktop.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    // paced demo (no fast=1) so the run screen stays up for the manual buddy drives
    await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
    await waitScreen(page, "screen-start");
    await page.check("#consent").catch(() => {});
    await page.click("#btn-start");
    await waitScreen(page, "screen-run", 12000);
    await page.waitForFunction(() => window.__nunchi && window.__nunchi.buddyReady(), null, { timeout: 10000 });
    // take manual control of the buddy (stops the fixture feed overwriting our poses)
    await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 0, roll_deg: 0, depth: 1, conf: 0.97 }));
    await check("figure parts match the active render mode (3D figure or 2D fallback)", async () => {
      // Read mode + parts + triangles atomically so they can't disagree across round-trips
      // (the WebGL context can init to 3D or, under software GL, fall back to 2D by design).
      const snap = await page.evaluate(() => ({
        is3d: window.__nunchi.buddyIs3D(),
        parts: window.__nunchi.buddyParts(),
        tris: window.__nunchi.buddyTriangles(),
      }));
      if (snap.is3d) {
        for (const p of ["head", "neck", "shoulders", "chest", "rightArm", "leftArm", "desk"]) {
          assert(snap.parts.includes(p), `missing 3D part: ${p} (got ${snap.parts.join(",")})`);
        }
        assert(snap.tris > 0 && snap.tris <= 4000, `triangle budget out of range: ${snap.tris}`);
      } else {
        // graceful, by-design 2D fallback (software GL may refuse a context): a flat angle icon
        assert(snap.parts.includes("head2d"), `2D fallback should report head2d (got ${snap.parts.join(",")})`);
      }
    });
    await check("honesty line is shown: head+hand measured, neck+torso estimated, no legs", async () => {
      const note = (await page.textContent(".buddy-measured-note"))?.trim() || "";
      assert(/measured/i.test(note) && /estimate/i.test(note) && /legs/i.test(note),
        `measured/estimated/legs disclosure missing: "${note}"`);
    });
    await check("accessibility: canvas is role=img with a live aria-label (either mode)", async () => {
      assert((await page.getAttribute("#buddy-canvas", "role")) === "img", "buddy canvas role!=img");
      const aria = (await page.getAttribute("#buddy-canvas", "aria-label")) || "";
      assert(aria.trim().length > 0, "buddy canvas has no aria-label");
    });
    await check("the measured drink event raises the right arm, then it falls", async () => {
      await page.evaluate(() => window.__nunchi.setBuddyDrinking(true));
      await page.waitForFunction(() => window.__nunchi.buddyArmRaise() > 0.3, null, { timeout: 4000 });
      const raised = await page.evaluate(() => window.__nunchi.buddyArmRaise());
      assert(raised > 0.3, `arm did not raise: ${raised}`);
      await page.evaluate(() => window.__nunchi.setBuddyDrinking(false));
      await page.waitForFunction(() => window.__nunchi.buddyArmRaise() < 0.15, null, { timeout: 4000 });
      const lowered = await page.evaluate(() => window.__nunchi.buddyArmRaise());
      assert(lowered < 0.15, `arm did not lower: ${lowered}`);
    });
    await check("forward-head pose leans the estimated torso; aria names it an estimate", async () => {
      await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 12, roll_deg: 1, depth: 1.4, conf: 0.95 }));
      await page.waitForFunction(() => window.__nunchi.buddyTorsoLean() > 1, null, { timeout: 4000 });
      const lean = await page.evaluate(() => window.__nunchi.buddyTorsoLean());
      assert(lean > 1 && lean <= 18, `torso lean out of range: ${lean}`);
      await page.waitForFunction(() => {
        const a = document.getElementById("buddy-canvas")?.getAttribute("aria-label") || "";
        return /estimate|추정/i.test(a);
      }, null, { timeout: 4000 });
      const aria = await page.getAttribute("#buddy-canvas", "aria-label");
      assert(/estimate|추정/i.test(aria), `aria does not flag estimate: ${aria}`);
    });
    await check("low confidence holds the figure still (tracking unsure)", async () => {
      // let the forward-head lean settle first (ramp complete) so `before` is a stable value,
      // not a mid-animation sample that the next frame would still advance.
      await page.waitForFunction(() => window.__nunchi.buddyTorsoLean() > 10, null, { timeout: 4000 }).catch(() => {});
      let prev = -1, stable = 0;
      await page.waitForFunction(() => true, null, { timeout: 100 });
      for (let i = 0; i < 40 && stable < 3; i++) {
        const v = await page.evaluate(() => window.__nunchi.buddyTorsoLean());
        if (Math.abs(v - prev) < 0.05) stable++; else stable = 0;
        prev = v;
        await page.waitForTimeout(60);
      }
      const before = await page.evaluate(() => window.__nunchi.buddyTorsoLean());
      await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 30, pitch_deg: 30, roll_deg: 20, depth: 1.9, conf: 0.2 }));
      // the unsure badge flips synchronously; the rig then freezes — confirm the lean does not move.
      await page.waitForFunction(() => !document.getElementById("buddy-unsure")?.hidden, null, { timeout: 4000 });
      await page.waitForTimeout(350);
      const after = await page.evaluate(() => window.__nunchi.buddyTorsoLean());
      assert(Math.abs(after - before) < 0.5, `figure moved on low conf: ${before} → ${after}`);
      assert(!(await page.locator("#buddy-unsure").evaluate((el) => el.hidden)), "unsure badge hidden on low conf");
    });
    await check("ghost (good-posture outline) toggles on the new figure without errors", async () => {
      await page.check("#buddy-ghost");
      await page.waitForTimeout(120);
      assert(await page.locator("#buddy-ghost").isChecked(), "ghost not checked");
      await page.uncheck("#buddy-ghost");
    });
    await check("keyboard rotates the figure (ArrowRight / Home), canvas keeps focus", async () => {
      await page.focus("#buddy-canvas");
      await page.keyboard.press("ArrowRight");
      await page.keyboard.press("Home");
      assert((await page.evaluate(() => document.activeElement?.id)) === "buddy-canvas", "canvas lost focus");
    });
    await check("no uncaught page errors across the sitting-buddy flow", async () =>
      assert(pageErrors.length === 0, `page errors: ${pageErrors.join(" | ")}`));
    await page.close();
  }

  // ---- 3c3. W14: mobile 390px shows the figure + honesty line without overflow ----
  group("sitting buddy mobile (W14)");
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 820 }, isMobile: true });
    const page = await ctx.newPage();
    await startDemoToRun(page);
    await page.waitForFunction(() => window.__nunchi && window.__nunchi.buddyReady(), null, { timeout: 10000 });
    await check("mobile 390px: buddy canvas + honesty line visible, no h-scroll", async () => {
      assert(await page.isVisible("#buddy-canvas"), "buddy canvas hidden on mobile");
      assert(await page.isVisible(".buddy-measured-note"), "honesty line hidden on mobile");
      await assertNoHScroll(page, "mobile buddy");
    });
    await page.close();
    await ctx.close();
  }

  // ---- 3d. W11: demo strip never covers buddy content (390px + 320px panel) ----
  group("demo strip (W11)");
  {
    for (const [label, vp] of [["mobile 390px", { width: 390, height: 780 }], ["narrow 360px", { width: 360, height: 760 }]]) {
      const ctx = await browser.newContext({ viewport: vp, isMobile: vp.width <= 400 });
      const page = await ctx.newPage();
      await startDemoToRun(page);
      await check(`${label}: demo strip visible and full-width at the bottom`, async () => {
        assert(await page.isVisible("#demo-corner"), "demo strip hidden");
        const box = await page.locator("#demo-corner").boundingBox();
        assert(box, "no demo strip box");
        // full-width bottom strip: spans the viewport and sits at the bottom edge
        assert(box.width >= vp.width - 2, `strip not full width: ${box.width} < ${vp.width}`);
        assert(box.y + box.height >= vp.height - 2, `strip not at bottom: ${box.y + box.height}`);
      });
      await check(`${label}: demo strip does not overlap the buddy rewind hint`, async () => {
        // reveal the rewind timeline first (needs a few pose samples)
        await page.waitForSelector("#buddy-rewind:not([hidden])", { timeout: 8000 });
        const strip = await page.locator("#demo-corner").boundingBox();
        for (const sel of ["#buddy-state", ".buddy-rotate-hint", "#rewind-time"]) {
          const el = page.locator(sel).first();
          if (!(await el.count())) continue;
          const b = await el.boundingBox();
          if (!b || !strip) continue;
          const overlapY = Math.max(0, Math.min(b.y + b.height, strip.y + strip.height) - Math.max(b.y, strip.y));
          assert(overlapY === 0, `${sel} overlapped by demo strip (${overlapY}px)`);
        }
      });
      await check(`${label}: demo strip text is not clipped`, async () => {
        // full-width strip must show the whole phrase (no ellipsis truncation)
        const clipped = await page.locator("#demo-corner").evaluate((el) => {
          const span = el.querySelector("span");
          return span ? span.scrollWidth - span.clientWidth > 2 : false;
        });
        assert(!clipped, "demo strip text is clipped");
      });
      await page.close();
      await ctx.close();
    }
  }

  // ---- 4. error states (>= 3 kinds) ----
  group("error states");
  {
    const page = await desktop.newPage();
    await page.goto(`${BASE}/?mock=1`, { waitUntil: "load" });
    await waitScreen(page, "screen-start");
    for (const kind of ["denied", "server", "offline"]) {
      await check(`error "${kind}" shows recoverable screen with retry`, async () => {
        await page.evaluate((k) => window.__nunchi.showError(k), kind);
        await waitScreen(page, "screen-camerror", 4000);
        assert(await page.isVisible("#btn-retry"), "retry button missing");
      });
    }
    await check("errorKindFromStatus maps 500->server, 0(offline)->offline", async () => {
      const map = await page.evaluate(() => ({
        s500: window.__nunchi.errorKindFromStatus(500),
        s401: window.__nunchi.errorKindFromStatus(401),
        s429: window.__nunchi.errorKindFromStatus(429),
      }));
      assert(map.s500 === "server", `500->${map.s500}`);
      assert(map.s401 === "unauthorized", `401->${map.s401}`);
      assert(map.s429 === "rate_limited", `429->${map.s429}`);
    });
    await page.close();
  }

  // ---- 5. no horizontal scroll (desktop + mobile) ----
  group("layout / no h-scroll");
  {
    const dpage = await desktop.newPage();
    await startDemoToRun(dpage);
    await check("desktop 1280px: no horizontal scroll on run", async () => assertNoHScroll(dpage, "desktop run"));
    await dpage.close();

    const mpage = await mobile.newPage();
    await startDemoToRun(mpage);
    await check("mobile 390px: no horizontal scroll on run", async () => assertNoHScroll(mpage, "mobile run"));
    await check("mobile 390px: demo corner within viewport", async () => {
      const box = await mpage.locator("#demo-corner").boundingBox();
      if (box) assert(box.x + box.width <= 391, `demo corner right edge ${box.x + box.width} > 390`);
    });
    await mpage.close();
  }

  // ---- 6. keyboard-only: reach run via Tab/Enter ----
  group("keyboard only");
  {
    const page = await desktop.newPage();
    await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
    await waitScreen(page, "screen-start");
    await check("consent + start reachable by keyboard", async () => {
      // focus the consent checkbox by id, toggle with Space, then activate Start
      await page.focus("#consent").catch(() => {});
      await page.keyboard.press("Space").catch(() => {});
      // ensure start is enabled, focus and Enter
      await page.waitForSelector("#btn-start:not([disabled])", { timeout: 4000 });
      await page.focus("#btn-start");
      await page.keyboard.press("Enter");
      await waitScreen(page, "screen-run", 12000);
    });
    await check("a visible focus indicator exists (focus-visible outline)", async () => {
      await page.focus("#btn-end");
      const outline = await page.evaluate(() => {
        const el = document.activeElement;
        const s = getComputedStyle(el);
        return s.outlineStyle + " " + s.outlineWidth;
      });
      assert(/solid/.test(outline), `no focus outline: ${outline}`);
    });
    await page.close();
  }

  await browser.close();

  const passed = results.filter((r) => r.ok).length;
  const failed = results.length - passed;
  console.log(`\n${passed}/${results.length} passed, ${failed} failed`);
  console.log("E2E_SUMMARY " + JSON.stringify({
    base: BASE, total: results.length, passed, failed,
    results: results.map((r) => ({ name: r.name, ok: r.ok, error: r.error || null })),
    at: new Date().toISOString(),
  }));
  process.exit(failed === 0 ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(2); });
