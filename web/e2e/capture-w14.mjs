// web/e2e/capture-w14.mjs — screenshots of the sitting upper-body posture buddy (W14).
// OWNER: web tab. No real camera/server. Writes PNGs to docs/screenshots/w14-*.png.
//   node e2e/capture-w14.mjs   (needs a static server on BASE, e.g. PORT=8099)
//
// Drives the figure into the states the brief asks to eyeball: front/side/top, neutral vs
// forward-head (estimated torso lean), the drink moment (right arm raised), ghost overlap,
// and a mobile 390px layout. Uses the paced demo (?demo=1) so the run screen stays up, then
// takes manual control of the buddy via the __nunchi test hooks (numbers only).

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
  console.log("buddy 3D:", is3d, "triangles:", await page.evaluate(() => window.__nunchi.buddyTriangles()));

  // 1) neutral, front view
  await page.evaluate(() => { window.__nunchi.buddySetView(0, 0); window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 0, roll_deg: 0, depth: 1, conf: 0.97 }); });
  await page.waitForTimeout(700);
  await buddy.screenshot({ path: join(shotsDir, "w14-buddy-front-neutral.png") });

  // 2) forward-head (estimated torso lean), front view
  await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 2, pitch_deg: 13, roll_deg: 3, depth: 1.4, conf: 0.95 }));
  await page.waitForTimeout(900);
  await buddy.screenshot({ path: join(shotsDir, "w14-buddy-front-forward.png") });

  // 3) side view of a head tilt
  await page.evaluate(() => { window.__nunchi.setBuddyPose({ yaw_deg: 6, pitch_deg: 2, roll_deg: 12, depth: 1.05, conf: 0.96 }); window.__nunchi.buddySetView(70, 0); });
  await page.waitForTimeout(800);
  await buddy.screenshot({ path: join(shotsDir, "w14-buddy-side.png") });

  // 4) top view
  await page.evaluate(() => { window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 8, roll_deg: 0, depth: 1.2, conf: 0.96 }); window.__nunchi.buddySetView(0, 60); });
  await page.waitForTimeout(800);
  await buddy.screenshot({ path: join(shotsDir, "w14-buddy-top.png") });

  // 5) drinking APEX: pin the right-arm raise at 1.0 so the hand is at mouth height (W15 task 2).
  //    Front and side, each a clean apex frame.
  await page.evaluate(() => { window.__nunchi.buddySetView(18, 0); window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 2, roll_deg: 0, depth: 1.02, conf: 0.96 }); window.__nunchi.setBuddyDrinking(true); window.__nunchi.forceBuddyArmRaise(1); });
  await page.waitForFunction(() => window.__nunchi.buddyArmRaise() > 0.95, null, { timeout: 2000 }).catch(() => {});
  await page.waitForTimeout(300);
  await buddy.screenshot({ path: join(shotsDir, "w14-buddy-drinking.png") });
  // side view of the same apex
  await page.evaluate(() => window.__nunchi.buddySetView(68, 0));
  await page.waitForTimeout(400);
  await buddy.screenshot({ path: join(shotsDir, "w14-buddy-drinking-side.png") });
  await page.evaluate(() => { window.__nunchi.forceBuddyArmRaise(null); window.__nunchi.setBuddyDrinking(false); window.__nunchi.buddySetView(0, 0); });

  // 6) good-posture ghost overlap (front, slight forward so buddy vs ghost differ)
  await page.evaluate(() => { window.__nunchi.buddySetView(12, 6); window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 10, roll_deg: 2, depth: 1.3, conf: 0.96 }); });
  await page.check("#buddy-ghost").catch(() => {});
  await page.waitForTimeout(800);
  await buddy.screenshot({ path: join(shotsDir, "w14-buddy-ghost.png") });
  await page.uncheck("#buddy-ghost").catch(() => {});

  // 7) mobile 390px: figure + honesty line visible
  const mctx = await browser.newContext({ viewport: { width: 390, height: 860 }, isMobile: true });
  const mpage = await mctx.newPage();
  mpage.on("pageerror", (e) => errs.push(String(e)));
  await openToRun(mpage);
  await mpage.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 3, pitch_deg: 10, roll_deg: 6, depth: 1.25, conf: 0.95 }));
  await mpage.waitForTimeout(700);
  await mpage.locator("#buddy-wrap").screenshot({ path: join(shotsDir, "w14-buddy-mobile.png") });
  await mctx.close();

  await browser.close();
  console.log("captured w14 buddy screenshots; pageErrors=" + errs.length + (errs.length ? " :: " + errs.join(" | ") : ""));
  process.exit(errs.length ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
