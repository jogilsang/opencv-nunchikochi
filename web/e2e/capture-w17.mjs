// web/e2e/capture-w17.mjs — screenshots of the W17 polish: first-screen clarity, the
// server-shaped trend sentence on the comparison card, the "saved on this device" row with
// its anonymous-number note, and the demo strip clearing the comparison card's bottom note.
// OWNER: web tab. No real camera/server. Writes PNGs to docs/screenshots/w17-*.png.
//   node e2e/capture-w17.mjs   (needs a static server on BASE, e.g. PORT=8099)

import { chromium } from "playwright";
import { join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE || "http://localhost:8099";
const webRoot = normalize(join(fileURLToPath(import.meta.url), "..", ".."));
const shotsDir = normalize(join(webRoot, "..", "docs", "screenshots"));

async function waitScreen(page, id, t = 15000) {
  await page.waitForFunction((w) => window.__nunchi && window.__nunchi.screen === w, id, { timeout: t });
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    args: [
      "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
      "--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist",
    ],
  });
  const page = await (await browser.newContext({ viewport: { width: 1180, height: 1100 } })).newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));

  // 1) first screen — "what it is + what it won't do" + demo-first mode cards
  await page.goto(`${BASE}/`, { waitUntil: "load" });
  await page.waitForFunction(() => window.__nunchi);
  await page.click("#mode-demo"); // highlight the no-camera, no-key path
  await page.waitForTimeout(250);
  await page.locator("#screen-start .card").screenshot({ path: join(shotsDir, "w17-start-clarity.png") });

  // 2) demo report → comparison card with the server trend sentence (+ Example data label)
  await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
  await waitScreen(page, "screen-start");
  await page.check("#consent").catch(() => {});
  await page.click("#btn-start");
  await waitScreen(page, "screen-run", 14000);
  await page.click("#btn-end");
  await waitScreen(page, "screen-report", 15000);
  await page.waitForTimeout(400);
  await page.locator("#report-history").screenshot({ path: join(shotsDir, "w17-comparison-trend.png") });

  // 3) demo-strip clearance: full-page bottom shows the comparison card's example note is NOT
  //    covered by the fixed "Demo playback" strip.
  await page.locator("#history-example-note").scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await page.screenshot({ path: join(shotsDir, "w17-demostrip-clearance.png") });

  // 4) real mode (mock) — "Saved on this device" row with the anonymous-number note + Clear
  const page2 = await (await browser.newContext({ viewport: { width: 1180, height: 1100 } })).newPage();
  page2.on("pageerror", (e) => errs.push(String(e)));
  await page2.goto(`${BASE}/?mock=1`, { waitUntil: "load" });
  await waitScreen(page2, "screen-start");
  await page2.evaluate(() => window.__nunchi.clearStored());
  await page2.check("#consent").catch(() => {});
  await page2.click("#btn-start");
  await waitScreen(page2, "screen-run", 14000);
  await page2.click("#btn-end");
  await waitScreen(page2, "screen-report", 15000);
  await page2.waitForTimeout(400);
  await page2.locator("#report-stored").scrollIntoViewIfNeeded().catch(() => {});
  await page2.locator("#report-stored").screenshot({ path: join(shotsDir, "w17-stored-anon.png") });
  // and the real-mode comparison card (server trend sentence, no Example label)
  await page2.locator("#report-history").screenshot({ path: join(shotsDir, "w17-comparison-real.png") });
  await page2.close();

  await browser.close();
  console.log("captured w17 screenshots; pageErrors=" + errs.length + (errs.length ? " :: " + errs.join(" | ") : ""));
  process.exit(errs.length ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
