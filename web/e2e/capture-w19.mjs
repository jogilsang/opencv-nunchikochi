// web/e2e/capture-w19.mjs — screenshots of the W19 short-session posture record.
// OWNER: web tab. No real camera/server. Writes PNGs to docs/screenshots/w19-*.png.
//   node e2e/capture-w19.mjs   (needs a static server on BASE, e.g. PORT=8099)
//
// Uses the __nunchi.renderReportWith test hook to render the report from crafted payloads so
// we can eyeball the three short-session states: (1) rate withheld but bars + count sentence,
// (2) zero events, (3) short session with earlier records → "too short to compare" + earlier
// bars only. Also a 390px mobile shot of state (1).

import { chromium } from "playwright";
import { join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE || "http://localhost:8099";
const webRoot = normalize(join(fileURLToPath(import.meta.url), "..", ".."));
const shotsDir = normalize(join(webRoot, "..", "docs", "screenshots"));

const shortTl = {
  bad_posture: {
    "5m": [{ start_s: 0, events: 2, seconds: 18 }],
    "10m": [{ start_s: 0, events: 2, seconds: 18 }],
    "30m": [{ start_s: 0, events: 2, seconds: 18 }],
    "60m": [{ start_s: 0, events: 2, seconds: 18 }],
  },
  per_hour_rate: null,
};
const emptyTl = { bad_posture: { "5m": [{ start_s: 0, events: 0, seconds: 0 }], "10m": [{ start_s: 0, events: 0, seconds: 0 }], "30m": [{ start_s: 0, events: 0, seconds: 0 }], "60m": [{ start_s: 0, events: 0, seconds: 0 }] }, per_hour_rate: null };

async function open(page) {
  await page.goto(`${BASE}/?mock=1`, { waitUntil: "load" });
  await page.waitForFunction(() => window.__nunchi);
  await page.evaluate(() => window.__nunchi.clearStored());
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required", "--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"],
  });
  const page = await (await browser.newContext({ viewport: { width: 1180, height: 1100 } })).newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  await open(page);

  // 1) short session with 2 events: bar + count sentence (rate withheld)
  await page.evaluate((tl) => window.__nunchi.renderReportWith({
    summary: { date: "2026-10-25", duration_s: 125, counts: { forward_head: 1, head_tilt: 1 }, seconds: {}, timeline: tl },
    report: { text_en: "", text_ko: "", trend: { direction: "na", line_en: "No earlier sessions to compare with yet.", line_ko: "" } },
    previous: null, history: [], trend: { direction: "na", line_en: "No earlier sessions to compare with yet.", line_ko: "" }, example: false,
  }), shortTl);
  await page.waitForTimeout(250);
  await page.locator("#report-timeline").screenshot({ path: join(shotsDir, "w19-short-count.png") });

  // 2) zero-event short session
  await page.evaluate((tl) => window.__nunchi.renderReportWith({
    summary: { date: "2026-10-25", duration_s: 90, counts: {}, seconds: {}, timeline: tl },
    report: { text_en: "", text_ko: "", trend: { direction: "na", line_en: "No earlier sessions to compare with yet.", line_ko: "" } },
    previous: null, history: [], trend: { direction: "na", line_en: "No earlier sessions to compare with yet.", line_ko: "" }, example: false,
  }), emptyTl);
  await page.waitForTimeout(250);
  await page.locator("#report-timeline").screenshot({ path: join(shotsDir, "w19-no-events.png") });

  // 3) short session + earlier records → comparison "too short to compare" + earlier bars only
  const hist = [
    { date: "2026-10-23", timeline: { bad_posture: {}, per_hour_rate: 9.0 } },
    { date: "2026-10-24", timeline: { bad_posture: {}, per_hour_rate: 7.0 } },
  ];
  await page.evaluate(({ tl, hist }) => window.__nunchi.renderReportWith({
    summary: { date: "2026-10-25", duration_s: 125, counts: { forward_head: 2 }, seconds: {}, timeline: tl },
    report: { text_en: "", text_ko: "", trend: { direction: "na", today_rate: null, baseline_rate: 8.0, n: 2, line_en: "", line_ko: "" } },
    previous: null, history: hist, trend: { direction: "na", today_rate: null, baseline_rate: 8.0, n: 2, line_en: "", line_ko: "" }, example: false,
  }), { tl: shortTl, hist });
  await page.waitForTimeout(250);
  await page.locator("#report-history").screenshot({ path: join(shotsDir, "w19-compare-tooshort.png") });

  // 4) mobile 390px of state (1)
  const mctx = await browser.newContext({ viewport: { width: 390, height: 900 }, isMobile: true });
  const mp = await mctx.newPage();
  mp.on("pageerror", (e) => errs.push(String(e)));
  await open(mp);
  await mp.evaluate((tl) => window.__nunchi.renderReportWith({
    summary: { date: "2026-10-25", duration_s: 125, counts: { forward_head: 1, head_tilt: 1 }, seconds: {}, timeline: tl },
    report: { text_en: "", text_ko: "", trend: { direction: "na", line_en: "No earlier sessions to compare with yet.", line_ko: "" } },
    previous: null, history: [], trend: { direction: "na", line_en: "No earlier sessions to compare with yet.", line_ko: "" }, example: false,
  }), shortTl);
  await mp.waitForTimeout(250);
  const over = await mp.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth));
  await mp.locator("#report-timeline").screenshot({ path: join(shotsDir, "w19-short-count-mobile.png") });
  await mctx.close();

  await browser.close();
  console.log("captured w19 screenshots; mobileOverflow=" + over + "; pageErrors=" + errs.length + (errs.length ? " :: " + errs.join(" | ") : ""));
  process.exit(errs.length ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
