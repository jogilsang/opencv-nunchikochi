// web/e2e/capture-w20.mjs — screenshots of the face + neck posture buddy (W20).
// OWNER: web tab. No real camera/server. Writes PNGs to docs/screenshots/w20-*.png.
//   node e2e/capture-w20.mjs   (needs a static server on BASE, e.g. PORT=8099)
//
// Drives the buddy into the states the brief asks to eyeball: front neutral, a smile, mouth
// open (yawn/talk), head leaning forward (estimated neck), and a side view. Uses the paced
// demo (?demo=1) so the run screen stays up, then takes manual control via __nunchi (numbers
// only — angles + expression channels, no image).

import { chromium } from "playwright";
import { join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE || "http://localhost:8099";
const webRoot = normalize(join(fileURLToPath(import.meta.url), "..", ".."));
const shotsDir = normalize(join(webRoot, "..", "docs", "screenshots"));

async function waitScreen(page, id, t = 12000) {
  await page.waitForFunction((w) => window.__nunchi && window.__nunchi.screen === w, id, { timeout: t });
}

async function openToRun(page) {
  await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" }); // paced demo keeps the run screen up
  await waitScreen(page, "screen-start");
  await page.check("#consent").catch(() => {});
  await page.click("#btn-start");
  await waitScreen(page, "screen-run", 12000);
  await page.waitForFunction(() => window.__nunchi.buddyReady());
  // take manual control (stops the fixture feed overwriting our poses)
  await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 0, roll_deg: 0, depth: 1, conf: 0.97 }));
  await page.waitForTimeout(500);
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
  const page = await (await browser.newContext({ viewport: { width: 1180, height: 980 } })).newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  await openToRun(page);
  const buddy = page.locator("#buddy-wrap");

  const is3d = await page.evaluate(() => window.__nunchi.buddyIs3D());
  console.log("buddy 3D:", is3d, "triangles:", await page.evaluate(() => window.__nunchi.buddyTriangles()), "parts:", (await page.evaluate(() => window.__nunchi.buddyParts())).join(","));

  // 1) front, neutral face
  await page.evaluate(() => { window.__nunchi.buddySetView(0, 0); window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 0, roll_deg: 0, depth: 1, conf: 0.97, expr: { eye_l: 1, eye_r: 1, mouth_open: 0, smile: 0, brow_raise: 0 } }); });
  await page.waitForTimeout(700);
  await buddy.screenshot({ path: join(shotsDir, "w20-buddy-front-neutral.png") });

  // 2) front, smiling
  await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 0, roll_deg: 0, depth: 1, conf: 0.97, expr: { eye_l: 1, eye_r: 1, mouth_open: 0.1, smile: 0.85, brow_raise: 0.2 } }));
  await page.waitForTimeout(900);
  await buddy.screenshot({ path: join(shotsDir, "w20-buddy-smile.png") });

  // 3) front, mouth open (yawn / talking)
  await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 2, roll_deg: 0, depth: 1.02, conf: 0.96, expr: { eye_l: 0.6, eye_r: 0.6, mouth_open: 0.95, smile: 0, brow_raise: 0.5 } }));
  await page.waitForTimeout(900);
  await buddy.screenshot({ path: join(shotsDir, "w20-buddy-mouth-open.png") });

  // 4) head leaning forward (estimated neck), front
  await page.evaluate(() => { window.__nunchi.buddySetView(0, 0); window.__nunchi.setBuddyPose({ yaw_deg: 2, pitch_deg: 14, roll_deg: 3, depth: 1.4, conf: 0.95, expr: { eye_l: 1, eye_r: 1, mouth_open: 0, smile: 0, brow_raise: 0 } }); });
  await page.waitForTimeout(900);
  await buddy.screenshot({ path: join(shotsDir, "w20-buddy-forward.png") });

  // 5) side view of a head tilt
  await page.evaluate(() => { window.__nunchi.setBuddyPose({ yaw_deg: 6, pitch_deg: 3, roll_deg: 12, depth: 1.05, conf: 0.96, expr: { eye_l: 1, eye_r: 1, mouth_open: 0.1, smile: 0.2, brow_raise: 0 } }); window.__nunchi.buddySetView(70, 0); });
  await page.waitForTimeout(800);
  await buddy.screenshot({ path: join(shotsDir, "w20-buddy-side.png") });

  // 6) drink cup/chip near the mouth (measured drink event, no arm), front
  await page.evaluate(() => { window.__nunchi.buddySetView(0, 0); window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 2, roll_deg: 0, depth: 1.02, conf: 0.96, expr: { eye_l: 1, eye_r: 1, mouth_open: 0.3, smile: 0, brow_raise: 0 } }); window.__nunchi.setBuddyDrinking(true); });
  await page.waitForFunction(() => window.__nunchi.buddyDrinkingShown() === true, null, { timeout: 2000 }).catch(() => {});
  await page.waitForTimeout(500);
  await buddy.screenshot({ path: join(shotsDir, "w20-buddy-drink.png") });
  await page.evaluate(() => window.__nunchi.setBuddyDrinking(false));

  // 7) good-posture ghost overlap (front, slight forward so buddy vs ghost differ)
  await page.evaluate(() => { window.__nunchi.buddySetView(12, 6); window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 10, roll_deg: 2, depth: 1.3, conf: 0.96, expr: { eye_l: 1, eye_r: 1, mouth_open: 0, smile: 0, brow_raise: 0 } }); });
  await page.check("#buddy-ghost").catch(() => {});
  await page.waitForTimeout(800);
  await buddy.screenshot({ path: join(shotsDir, "w20-buddy-ghost.png") });
  await page.uncheck("#buddy-ghost").catch(() => {});

  // 8) mobile 390px: face + honesty line visible
  const mctx = await browser.newContext({ viewport: { width: 390, height: 860 }, isMobile: true });
  const mpage = await mctx.newPage();
  mpage.on("pageerror", (e) => errs.push(String(e)));
  await openToRun(mpage);
  await mpage.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 3, pitch_deg: 8, roll_deg: 6, depth: 1.2, conf: 0.95, expr: { eye_l: 1, eye_r: 1, mouth_open: 0.2, smile: 0.5, brow_raise: 0.1 } }));
  await mpage.waitForTimeout(700);
  await mpage.locator("#buddy-wrap").screenshot({ path: join(shotsDir, "w20-buddy-mobile.png") });
  await mctx.close();

  await browser.close();
  console.log("captured w20 buddy screenshots; pageErrors=" + errs.length + (errs.length ? " :: " + errs.join(" | ") : ""));
  process.exit(errs.length ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
