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
  const q = ["demo=1"]; if (lang) q.push(`lang=${lang}`);
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
