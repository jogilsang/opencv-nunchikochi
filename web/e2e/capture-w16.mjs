// web/e2e/capture-w16.mjs — screenshots of the W16 UI: Quiet mode (run) + posture-record
// timeline and earlier-session comparison (report). OWNER: web tab. No real camera/server.
// Writes PNGs to docs/screenshots/w16-*.png.
//   node e2e/capture-w16.mjs   (needs a static server on BASE, e.g. PORT=8099)
//
// Shots: the Quiet toggle + status chip on the run screen, the posture-record card as a
// bar chart and as its accessible table, and the "compared with earlier sessions" trend
// card (demo = sample data, labelled "Example data"). Numbers only — no frames.

import { chromium } from "playwright";
import { join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE || "http://localhost:8099";
const webRoot = normalize(join(fileURLToPath(import.meta.url), "..", ".."));
const shotsDir = normalize(join(webRoot, "..", "docs", "screenshots"));

async function waitScreen(page, id, t = 14000) {
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

  // ---- run screen: Quiet toggle (default ON) + status chip ----
  await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" }); // paced demo keeps the run screen up
  await waitScreen(page, "screen-start");
  await page.check("#consent").catch(() => {});
  await page.click("#btn-start");
  await waitScreen(page, "screen-run", 14000);
  // feed a couple of nudges so the quiet chip shows a held-back count
  await page.evaluate(() => { window.__nunchi.feedDecision({ action: "nudge", reason: "sustained:head_tilt", message: "Straighten up?", message_ko: "바로 세워볼까요?" }); window.__nunchi.feedDecision({ action: "nudge", reason: "sustained:forward_head", message: "Sit back a little?", message_ko: "조금 기대어 볼까요?" }); });
  await page.waitForTimeout(500);
  // clip the Quiet bar + its hint line together so the shot shows the toggle, the status
  // chip, and the "alerts stay off, still recording" explanation in one frame.
  const bar = await page.locator("#quiet-bar").boundingBox();
  const hint = await page.locator("#quiet-hint").boundingBox();
  if (bar && hint) {
    const x = Math.min(bar.x, hint.x) - 8;
    const y = bar.y - 8;
    const w = Math.max(bar.x + bar.width, hint.x + hint.width) - x + 8;
    const h = (hint.y + hint.height) - y + 8;
    await page.screenshot({ path: join(shotsDir, "w16-quiet-toggle.png"), clip: { x, y, width: w, height: h } });
  } else {
    await page.locator("#quiet-bar").screenshot({ path: join(shotsDir, "w16-quiet-toggle.png") });
  }

  // ---- report screen: end the (paced) demo, then shoot the two report cards ----
  await page.click("#btn-end");
  await waitScreen(page, "screen-report", 15000);
  await page.waitForTimeout(400);

  // 1) posture-record timeline as a bar chart (5-min slices)
  await page.evaluate(() => window.__nunchi.setTimelineUnit("5m"));
  await page.waitForTimeout(250);
  await page.locator("#report-timeline").screenshot({ path: join(shotsDir, "w16-timeline-chart.png") });

  // 2) posture-record timeline as its accessible table (toggle), 30-min slices
  await page.evaluate(() => window.__nunchi.setTimelineUnit("30m"));
  await page.click("#tl-toggle-view"); // chart → table
  await page.waitForTimeout(250);
  await page.locator("#report-timeline").screenshot({ path: join(shotsDir, "w16-timeline-table.png") });
  await page.click("#tl-toggle-view"); // back to chart

  // 3) compared-with-earlier-sessions trend card (demo = Example data, improving)
  await page.locator("#report-history").screenshot({ path: join(shotsDir, "w16-comparison.png") });

  await browser.close();
  console.log("captured w16 screenshots; pageErrors=" + errs.length + (errs.length ? " :: " + errs.join(" | ") : ""));
  process.exit(errs.length ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
