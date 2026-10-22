// web/tools/record_demo.mjs — record a webm screen capture of the Nunchikochi flow.
// OWNER: web tab. No real camera, no real face: demo mode (?demo=1) replays the synthetic
// session; --live drives local-live mode with a Playwright FAKE camera against a local
// service. Output webm goes to docs/video/recordings/ (gitignored — never commit video).
//
// Usage:
//   # demo (no server needed) — serve web/ first, then:
//   python3 -m http.server 8099 --directory web &
//   node web/tools/record_demo.mjs --base http://localhost:8099 --out docs/video/recordings
//
//   # local-live (fake camera) — needs a running service (scripts/run_local.sh):
//   SVC=http://127.0.0.1:8000 KEY=local-... \
//     node web/tools/record_demo.mjs --live --base http://localhost:8099 --out docs/video/recordings
//
// Playwright is not vendored; install ad hoc (npx playwright install chromium). On any
// recording/environment error the script prints the cause and the manual fallback, and
// exits non-zero without pretending it recorded.

import { writeFile, rm, readFile, mkdir, readdir, rename } from "node:fs/promises";
import { join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

function arg(name, def) {
  const i = process.argv.indexOf(`--${name}`);
  if (i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith("--")) return process.argv[i + 1];
  return def;
}
const FLAG_LIVE = process.argv.includes("--live");
const BASE = arg("base", process.env.BASE || "http://localhost:8099");
const OUT = resolve(arg("out", process.env.OUT || "docs/video/recordings"));
const SVC = arg("svc", process.env.SVC || "http://127.0.0.1:8000");
const KEY = process.env.KEY || "local-recording-not-a-secret";
const webRoot = normalize(join(fileURLToPath(import.meta.url), "..", ".."));
const cfgPath = join(webRoot, "config.json");

function log(m) { console.log(`[record] ${m}`); }
function fail(m, code = 1) {
  console.error(`[record] ERROR: ${m}`);
  console.error("[record] manual fallback: open " + BASE + "/?demo=1 in a browser and screen-record the tab");
  console.error("[record] (the demo auto-advances start -> calibrate -> run -> report; no camera needed).");
  process.exit(code);
}

async function loadPlaywright() {
  try { return await import("playwright"); }
  catch { fail("playwright not installed. Install: npx playwright install chromium (or `npm i playwright`).", 2); }
}

async function waitScreen(page, id, t = 20000) {
  await page.waitForFunction((w) => window.__nunchi && window.__nunchi.screen === w, id, { timeout: t });
}

async function main() {
  const { chromium } = await loadPlaywright();
  await mkdir(OUT, { recursive: true });

  // live mode writes a temporary config.json; back up and restore whatever was there.
  let hadCfg = false, prevCfg = null;
  if (FLAG_LIVE) {
    try { prevCfg = await readFile(cfgPath, "utf8"); hadCfg = true; } catch {}
    await writeFile(cfgPath, JSON.stringify({ apiBase: SVC, apiKey: "", lang: "en", fps: 2 }, null, 2));
  }

  let browser, exitCode = 0;
  const tag = FLAG_LIVE ? "live" : "demo";
  try {
    browser = await chromium.launch({ headless: true, args: [
      "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
    ] });
    const ctx = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      recordVideo: { dir: OUT, size: { width: 1280, height: 800 } },
    });
    const page = await ctx.newPage();
    const pageErrors = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    log(`recording ${tag} flow from ${BASE} …`);
    await page.goto(`${BASE}/${FLAG_LIVE ? "" : "?demo=1"}`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);

    // beat: start screen (let viewers read the consent/mode)
    await page.waitForTimeout(2500);

    if (FLAG_LIVE) {
      await page.click("#mode-live");
      await page.waitForFunction(() => /Connected|연결/.test(document.getElementById("live-status").textContent), { timeout: 8000 })
        .catch(() => log("service status not 'connected' — recording continues (status line may show unavailable)"));
      await page.fill("#live-key", KEY);
      await page.check("#consent");
      await page.waitForTimeout(1200);
      await page.click("#btn-start");
    } else {
      await page.check("#consent");
      await page.waitForTimeout(800);
      await page.click("#btn-start");
    }

    // calibrate -> run
    await waitScreen(page, "screen-run", 20000);
    // beat: let the run play — overlay, metrics, nudges accrue (demo auto-fires)
    await page.waitForTimeout(6000);
    // beat: open the agent panel to show the perceive->decide->act evidence
    await page.click("#btn-agent").catch(() => {});
    await page.waitForTimeout(3500);
    // end -> report
    if ((await page.evaluate(() => window.__nunchi.screen)) === "screen-run") {
      await page.click("#btn-end").catch(() => {});
    }
    await waitScreen(page, "screen-report", 20000).catch(() => log("report screen not reached in time"));
    await page.waitForTimeout(3000);

    if (pageErrors.length) log(`note: ${pageErrors.length} page error(s) during run: ${pageErrors[0]}`);

    // finalise the video file (Playwright writes it on context close)
    const video = page.video();
    await ctx.close();
    let outPath = "(unknown)";
    if (video) {
      const raw = await video.path();
      outPath = join(OUT, `nunchi-${tag}.webm`);
      await rename(raw, outPath).catch(async () => { await writeFile(outPath, await readFile(raw)); });
    } else {
      // fall back: find the newest webm Playwright dropped in OUT
      const files = (await readdir(OUT)).filter((f) => f.endsWith(".webm"));
      outPath = files.length ? join(OUT, files[files.length - 1]) : "(no webm produced)";
    }
    log(`done → ${outPath}  (gitignored; do not commit video)`);
  } catch (e) {
    exitCode = 1;
    console.error(`[record] recording failed: ${e && e.message || e}`);
    console.error("[record] manual fallback: screen-record the tab at " + BASE + "/?demo=1 (auto-advancing demo).");
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (FLAG_LIVE) { if (hadCfg) await writeFile(cfgPath, prevCfg); else await rm(cfgPath, { force: true }); }
  }
  process.exit(exitCode);
}

main().catch((e) => { console.error(e); process.exit(1); });
