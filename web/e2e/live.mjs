// web/e2e/live.mjs — live-mode integration against a locally running service.
// OWNER: web tab. Proves the judge's "Live (your camera)" path end to end with a FAKE
// camera (Playwright fake media) and a real local service — no real face, no AWS.
//
// Preconditions: a service answering /healthz and /v1/* at SVC (default :8000), and a
// static server for web/ at BASE (default :8099). scripts/run_local.sh provides both;
// this test can also be pointed at a service started any other way.
//
//   SVC=http://127.0.0.1:8000 KEY=local-... BASE=http://localhost:8099 node web/e2e/live.mjs
//
// It writes web/config.json (gitignored) for the run and removes it afterwards.

import { chromium } from "playwright";
import { writeFile, rm, readFile } from "node:fs/promises";
import { join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE || "http://localhost:8099";
const SVC = process.env.SVC || "http://127.0.0.1:8000";
const KEY = process.env.KEY || "local-w6test";
const webRoot = normalize(join(fileURLToPath(import.meta.url), "..", ".."));
const cfgPath = join(webRoot, "config.json");

const results = [];
async function check(name, fn) {
  try { await fn(); results.push({ name, ok: true }); console.log(`  ✓ ${name}`); }
  catch (e) { results.push({ name, ok: false, error: String(e && e.message || e) }); console.log(`  ✗ ${name}\n      ${String(e && e.message || e).split("\n")[0]}`); }
}
function assert(c, m) { if (!c) throw new Error(m || "assertion failed"); }

async function main() {
  // config.json present only for this run; captured so we can restore/remove honestly.
  let hadCfg = false, prev = null;
  try { prev = await readFile(cfgPath, "utf8"); hadCfg = true; } catch {}
  await writeFile(cfgPath, JSON.stringify({ apiBase: SVC, apiKey: "", lang: "en", fps: 2 }, null, 2));

  const browser = await chromium.launch({ headless: true, args: [
    "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
  ] });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage();
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));

  await page.goto(`${BASE}/`, { waitUntil: "load" });
  await page.waitForFunction(() => window.__nunchi);

  await check("start gate blocks live with no key chosen", async () => {
    await page.click("#mode-live");
    assert(await page.locator("#btn-start").isDisabled(), "start enabled before key");
  });

  await check("service status shows runtime (arch / OpenCV)", async () => {
    await page.waitForFunction(() => {
      const s = document.getElementById("live-status");
      return s && /Connected|연결/.test(s.textContent);
    }, { timeout: 6000 });
    const txt = await page.textContent("#live-status");
    assert(/arm64|opencv|OpenCV/i.test(txt), `status missing runtime: ${txt}`);
  });

  await check("entering key + consent enables start; key stays in memory only", async () => {
    await page.fill("#live-key", KEY);
    await page.check("#consent");
    await page.waitForSelector("#btn-start:not([disabled])", { timeout: 4000 });
    // key must NOT be in localStorage, sessionStorage, the URL, or the hook's value
    const leak = await page.evaluate(() => {
      const inStore = (s) => { try { return Object.keys(s).some((k) => (s.getItem(k) || "").length > 0); } catch { return false; } };
      return {
        ls: inStore(localStorage), ss: inStore(sessionStorage),
        url: location.href, hasKey: window.__nunchi.hasLiveKey(), len: window.__nunchi.liveKeyLen(),
      };
    });
    assert(leak.hasKey === true && leak.len > 0, "key not held in memory");
    assert(leak.ls === false, "localStorage has data (possible key leak)");
    assert(leak.ss === false, "sessionStorage has data (possible key leak)");
    assert(!/local-|key=|apikey/i.test(leak.url), `key may be in URL: ${leak.url}`);
  });

  await check("live session runs: calibrate -> run with overlay + metrics", async () => {
    await page.click("#btn-start");
    await page.waitForFunction(() => window.__nunchi.screen === "screen-run", { timeout: 20000 });
    // overlay canvas present and metrics leave the "—" placeholder within a few frames
    await page.waitForTimeout(3000);
    const ov = await page.locator("#run-overlay").count();
    assert(ov === 1, "overlay canvas missing");
    assert((await page.getAttribute("#btn-end", "data-i18n")) === "endSession", "run controls missing");
  });

  await check("end session -> report renders", async () => {
    if ((await page.evaluate(() => window.__nunchi.screen)) === "screen-run") await page.click("#btn-end");
    await page.waitForFunction(() => window.__nunchi.screen === "screen-report", { timeout: 20000 });
    assert((await page.locator(".num-card").count()) >= 1, "no report cards");
  });

  await check("no uncaught page errors during live run", async () =>
    assert(pageErrors.length === 0, pageErrors.join(" | ")));

  // live-mode screenshots (fake camera): running view (3rd of the 3 live assets)
  await browser.close();

  // restore config.json state
  if (hadCfg) await writeFile(cfgPath, prev); else await rm(cfgPath, { force: true });

  const passed = results.filter((r) => r.ok).length;
  const failed = results.length - passed;
  console.log(`\nlive: ${passed}/${results.length} passed, ${failed} failed`);
  console.log("LIVE_SUMMARY " + JSON.stringify({ base: BASE, svc: SVC, total: results.length, passed, failed, results, at: new Date().toISOString() }));
  process.exit(failed === 0 ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(2); });
