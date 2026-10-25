// web/e2e/capture-w22.mjs — screenshots of the expression-readable face buddy (W22).
// OWNER: web tab. No real camera/server. Writes PNGs to docs/screenshots/w22-*.png.
//   node e2e/capture-w22.mjs   (needs a static server on BASE, e.g. PORT=8099)
//
// Drives the face into the states W22 asks to eyeball — neutral, big smile, mouth open (yawn),
// both eyes closed, one-eye wink, brows up, head forward + a side view, and mobile — so a human
// can confirm "anyone would read that expression." Numbers only (angles + expr channels).

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
  await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
  await waitScreen(page, "screen-start");
  await page.check("#consent").catch(() => {});
  await page.click("#btn-start");
  await waitScreen(page, "screen-run", 12000);
  await page.waitForFunction(() => window.__nunchi.buddyReady());
  await page.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 0, pitch_deg: 0, roll_deg: 0, depth: 1, conf: 0.97, expr: { eye_l: 1, eye_r: 1, mouth_open: 0, smile: 0, brow_raise: 0 } }));
  await page.waitForTimeout(500);
}
// hold an expression a touch longer so the smoothing settles before the shot
async function setExpr(page, pose) {
  await page.evaluate((p) => window.__nunchi.setBuddyPose(p), pose);
  await page.waitForTimeout(900);
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
  const page = await (await browser.newContext({ viewport: { width: 1180, height: 1040 } })).newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(String(e)));
  await openToRun(page);
  const buddy = page.locator("#buddy-wrap");
  console.log("buddy 3D:", await page.evaluate(() => window.__nunchi.buddyIs3D()),
    "triangles:", await page.evaluate(() => window.__nunchi.buddyTriangles()),
    "parts:", (await page.evaluate(() => window.__nunchi.buddyParts())).join(","));

  const front = (expr) => ({ yaw_deg: 0, pitch_deg: 0, roll_deg: 0, depth: 1, conf: 0.97, expr });

  await page.evaluate(() => window.__nunchi.buddySetView(0, 0));
  await setExpr(page, front({ eye_l: 1, eye_r: 1, mouth_open: 0, smile: 0, brow_raise: 0 }));
  await buddy.screenshot({ path: join(shotsDir, "w22-buddy-neutral.png") });

  await setExpr(page, front({ eye_l: 1, eye_r: 1, mouth_open: 0.12, smile: 0.95, brow_raise: 0.2 }));
  await buddy.screenshot({ path: join(shotsDir, "w22-buddy-smile.png") });

  await setExpr(page, front({ eye_l: 0.65, eye_r: 0.65, mouth_open: 0.95, smile: 0, brow_raise: 0.4 }));
  await buddy.screenshot({ path: join(shotsDir, "w22-buddy-mouth-open.png") });

  await setExpr(page, front({ eye_l: 0.05, eye_r: 0.05, mouth_open: 0, smile: 0.3, brow_raise: 0 }));
  await buddy.screenshot({ path: join(shotsDir, "w22-buddy-eyes-closed.png") });

  // wink: user's left eye closed, right open
  await setExpr(page, front({ eye_l: 0.05, eye_r: 1, mouth_open: 0.1, smile: 0.6, brow_raise: 0.1 }));
  await buddy.screenshot({ path: join(shotsDir, "w22-buddy-wink.png") });

  await setExpr(page, front({ eye_l: 1, eye_r: 1, mouth_open: 0.15, smile: 0.1, brow_raise: 0.95 }));
  await buddy.screenshot({ path: join(shotsDir, "w22-buddy-brows-up.png") });

  // head forward + chin down (estimated neck), then a side view of a tilt
  await setExpr(page, { yaw_deg: 2, pitch_deg: 14, roll_deg: 3, depth: 1.4, conf: 0.95, expr: { eye_l: 1, eye_r: 1, mouth_open: 0, smile: 0, brow_raise: 0 } });
  await buddy.screenshot({ path: join(shotsDir, "w22-buddy-forward.png") });
  await page.evaluate(() => { window.__nunchi.setBuddyPose({ yaw_deg: 6, pitch_deg: 3, roll_deg: 12, depth: 1.05, conf: 0.96, expr: { eye_l: 1, eye_r: 1, mouth_open: 0.1, smile: 0.4, brow_raise: 0 } }); window.__nunchi.buddySetView(70, 0); });
  await page.waitForTimeout(800);
  await buddy.screenshot({ path: join(shotsDir, "w22-buddy-side.png") });
  await page.evaluate(() => window.__nunchi.buddySetView(0, 0));

  // mobile 390px: a smiling face + honesty line + full status text visible
  const mctx = await browser.newContext({ viewport: { width: 390, height: 900 }, isMobile: true });
  const mpage = await mctx.newPage();
  mpage.on("pageerror", (e) => errs.push(String(e)));
  await openToRun(mpage);
  await mpage.evaluate(() => window.__nunchi.setBuddyPose({ yaw_deg: 3, pitch_deg: 12, roll_deg: 6, depth: 1.3, conf: 0.95, expr: { eye_l: 1, eye_r: 1, mouth_open: 0.1, smile: 0.7, brow_raise: 0.2 } }));
  await mpage.waitForTimeout(900);
  await mpage.locator("#buddy-wrap").screenshot({ path: join(shotsDir, "w22-buddy-mobile.png") });
  await mctx.close();

  await browser.close();
  console.log("captured w22 buddy screenshots; pageErrors=" + errs.length + (errs.length ? " :: " + errs.join(" | ") : ""));
  process.exit(errs.length ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
