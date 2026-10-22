// web/e2e/capture-w10.mjs — screenshots of the posture buddy (W10), demo mode only.
// OWNER: web tab. No real camera/server. Writes PNGs to docs/screenshots/.
//   node e2e/capture-w10.mjs   (needs a static server on BASE, e.g. PORT=8099)

import { chromium } from "playwright";
import { join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE || "http://localhost:8099";
const webRoot = normalize(join(fileURLToPath(import.meta.url), "..", ".."));
const shotsDir = normalize(join(webRoot, "..", "docs", "screenshots"));

async function waitScreen(page, id, t = 12000) {
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
  const page = await (await browser.newContext({ viewport: { width: 1180, height: 940 } })).newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));

  await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
  await waitScreen(page, "screen-start");
  await page.check("#consent").catch(() => {});
  await page.click("#btn-start");
  await waitScreen(page, "screen-run", 12000);
  await page.waitForFunction(() => window.__nunchi.buddyReady());
  await page.waitForTimeout(800);

  const buddy = page.locator("#buddy-wrap");
  // 1) forward-head pose (clay buddy leaning forward, warm colour)
  await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 15, roll_deg: 2, depth: 1.33, conf: 0.95 }));
  await page.waitForTimeout(500);
  await buddy.screenshot({ path: join(shotsDir, "w10-buddy-forward.png") });

  // 2) side view of a head tilt (ghost on)
  await page.evaluate(() => { window.__nunchi.setBuddyPose({ yaw_deg: 6, pitch_deg: 1, roll_deg: 12, depth: 1.0, conf: 0.97 }); window.__nunchi.buddySetView(70, 0); });
  await page.check("#buddy-ghost").catch(() => {});
  await page.waitForTimeout(500);
  await buddy.screenshot({ path: join(shotsDir, "w10-buddy-side-ghost.png") });
  await page.uncheck("#buddy-ghost").catch(() => {});

  // 3) low confidence — buddy holds still, "tracking unsure"
  await page.evaluate(() => { window.__nunchi.buddySetView(0, 0); window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 7, roll_deg: 0, depth: 1.1, conf: 0.3 }); });
  await page.waitForTimeout(500);
  await buddy.screenshot({ path: join(shotsDir, "w10-buddy-unsure.png") });

  // 4) report screen rewind replay
  if ((await page.evaluate(() => window.__nunchi.screen)) === "screen-run") await page.click("#btn-end");
  await waitScreen(page, "screen-report", 15000);
  await page.waitForFunction(() => window.__nunchi.reportBuddyReady());
  await page.evaluate(() => window.__nunchi.rewindScrub(0.75));
  await page.waitForTimeout(500);
  await page.locator("#report-buddy-wrap").screenshot({ path: join(shotsDir, "w10-buddy-rewind.png") });

  // 5) mobile (390px): full-width demo strip at the bottom, buddy hint not clipped (W11)
  const mctx = await browser.newContext({ viewport: { width: 390, height: 820 }, isMobile: true });
  const mpage = await mctx.newPage();
  mpage.on("pageerror", (e) => errs.push(String(e)));
  await mpage.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
  await waitScreen(mpage, "screen-start");
  await mpage.check("#consent").catch(() => {});
  await mpage.click("#btn-start");
  await waitScreen(mpage, "screen-run", 12000);
  await mpage.waitForFunction(() => window.__nunchi.buddyReady());
  await mpage.waitForSelector("#buddy-rewind:not([hidden])", { timeout: 8000 });
  await mpage.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 4, pitch_deg: 10, roll_deg: 8, depth: 1.22, conf: 0.95 }));
  await mpage.waitForTimeout(500);
  await mpage.screenshot({ path: join(shotsDir, "w10-buddy-mobile.png") });
  await mctx.close();

  await browser.close();
  console.log("captured w10 buddy screenshots; pageErrors=" + errs.length + (errs.length ? " :: " + errs.join(" | ") : ""));
  process.exit(errs.length ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
