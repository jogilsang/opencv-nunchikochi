// web/e2e/capture-w6.mjs — live-mode screenshots (no real camera, no real AWS).
// OWNER: web tab. Uses a real LOCAL service (SVC) for the status line + a running session,
// and a Playwright fake camera. Output: docs/screenshots/live-*.png
//
//   SVC=http://127.0.0.1:8000 KEY=local-... BASE=http://localhost:8099 OUT=../docs/screenshots \
//     node web/e2e/capture-w6.mjs
// Writes web/config.json for the run and restores it afterwards.

import { chromium } from "playwright";
import { writeFile, rm, readFile, mkdir } from "node:fs/promises";
import { join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE || "http://localhost:8099";
const SVC = process.env.SVC || "http://127.0.0.1:8000";
const KEY = process.env.KEY || "local-w6test";
const OUT = process.env.OUT || "../docs/screenshots";
const webRoot = normalize(join(fileURLToPath(import.meta.url), "..", ".."));
const cfgPath = join(webRoot, "config.json");

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true, args: [
    "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
    "--autoplay-policy=no-user-gesture-required",
  ] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });

  // 1) Live selected, NO service configured → "no config / use demo" guidance.
  {
    const page = await ctx.newPage();
    await page.route("**/config.json", (r) => r.fulfill({ status: 404, body: "" }));
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);
    await page.click("#mode-live");
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/live-01-select-nokey.png` });
    await page.close();
  }

  // 2) Live with reachable service → status "Connected · arm64 · opencv · OpenCV 5.x", key filled.
  {
    const page = await ctx.newPage();
    await page.route("**/config.json", (r) => r.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ apiBase: SVC, apiKey: "", lang: "en", fps: 2 }),
    }));
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);
    await page.click("#mode-live");
    await page.waitForFunction(() => /Connected|연결/.test(document.getElementById("live-status").textContent), { timeout: 6000 }).catch(() => {});
    await page.fill("#live-key", KEY);
    await page.check("#consent");
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}/live-02-connected-ready.png` });
    await page.close();
  }

  // 3) Live session RUNNING against the real local service with a fake camera.
  {
    let hadCfg = false, prev = null;
    try { prev = await readFile(cfgPath, "utf8"); hadCfg = true; } catch {}
    await writeFile(cfgPath, JSON.stringify({ apiBase: SVC, apiKey: "", lang: "en", fps: 2 }, null, 2));
    try {
      const page = await ctx.newPage();
      await page.goto(`${BASE}/`, { waitUntil: "load" });
      await page.waitForFunction(() => window.__nunchi);
      await page.click("#mode-live");
      await page.waitForFunction(() => /Connected|연결/.test(document.getElementById("live-status").textContent), { timeout: 6000 }).catch(() => {});
      await page.fill("#live-key", KEY);
      await page.check("#consent");
      await page.click("#btn-start");
      await page.waitForFunction(() => window.__nunchi.screen === "screen-run", { timeout: 20000 });
      await page.waitForTimeout(2500);
      await page.screenshot({ path: `${OUT}/live-03-running-fakecam.png` });
      await page.close();
    } finally {
      if (hadCfg) await writeFile(cfgPath, prev); else await rm(cfgPath, { force: true });
    }
  }

  await browser.close();
  console.log("captured live-01/02/03 to", OUT);
}
main().catch((e) => { console.error(e); process.exit(2); });
