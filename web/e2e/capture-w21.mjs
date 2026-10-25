// web/e2e/capture-w21.mjs — screenshots of the W21 trial-key button flow.
// OWNER: web tab. No real camera/server: a mock service at svc.test.local answers /config.json,
// /healthz (key_issuing:true) and POST /v1/keys. Writes PNGs to docs/screenshots/w21-*.png.
//   node e2e/capture-w21.mjs   (needs a static server on BASE, e.g. PORT=8099)

import { chromium } from "playwright";
import { join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.BASE || "http://localhost:8099";
const webRoot = normalize(join(fileURLToPath(import.meta.url), "..", ".."));
const shotsDir = normalize(join(webRoot, "..", "docs", "screenshots"));

async function wireService(page, { keyResponder } = {}) {
  await page.route("**/config.json", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ apiBase: "https://svc.test.local" }) }));
  await page.route("https://svc.test.local/healthz", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, key_issuing: true, arch: "arm64", backend: "opencv", cv_version: "5.0.0" }) }));
  await page.route("https://svc.test.local/v1/keys", (r) => {
    if (r.request().method() !== "POST") return r.continue();
    (keyResponder || ((route) => route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ key: "a1b2c3d4".repeat(4), expires_at: new Date(Date.now() + 1800000).toISOString(), ttl_s: 1800, remaining_today: 2 }),
    })))(r);
  });
}
async function waitScreen(page, id, t = 8000) {
  await page.waitForFunction((w) => window.__nunchi && window.__nunchi.screen === w, id, { timeout: t });
}

async function main() {
  const browser = await chromium.launch({ headless: true, args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] });
  const errs = [];
  const card = (page) => page.locator(".card").first();          // start-screen card
  const errCard = (page) => page.locator("#screen-camerror .card"); // error-screen card

  // 1) button visible (live mode, key_issuing true)
  {
    const page = await (await browser.newContext({ viewport: { width: 760, height: 900 } })).newPage();
    page.on("pageerror", (e) => errs.push(String(e)));
    await wireService(page);
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);
    await page.click("#mode-live");
    await page.waitForFunction(() => window.__nunchi.trialKeyBtnVisible() === true);
    await page.waitForTimeout(300);
    await card(page).screenshot({ path: join(shotsDir, "w21-button.png") });

    // 2) after getting a key: countdown shown
    await page.click("#btn-trial-key");
    await page.waitForFunction(() => window.__nunchi.trialKeyActive() === true);
    await page.waitForTimeout(1100); // let one countdown tick render
    await card(page).screenshot({ path: join(shotsDir, "w21-countdown.png") });
    await page.close();
  }

  // 3) 429 ip_daily_limit screen
  {
    const page = await (await browser.newContext({ viewport: { width: 760, height: 760 } })).newPage();
    page.on("pageerror", (e) => errs.push(String(e)));
    await wireService(page, { keyResponder: (r) => r.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ error: "ip_daily_limit", retry_after_s: 3600, limit: 3 }) }) });
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);
    await page.click("#mode-live");
    await page.waitForFunction(() => window.__nunchi.trialKeyBtnVisible() === true);
    await page.evaluate(() => window.__nunchi.getTrialKey());
    await waitScreen(page, "screen-camerror");
    await page.waitForTimeout(300);
    await errCard(page).screenshot({ path: join(shotsDir, "w21-429.png") });
    await page.close();
  }

  // 4) expired screen (fast-forwarded)
  {
    const page = await (await browser.newContext({ viewport: { width: 760, height: 760 } })).newPage();
    page.on("pageerror", (e) => errs.push(String(e)));
    await wireService(page);
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);
    await page.click("#mode-live");
    await page.waitForFunction(() => window.__nunchi.trialKeyBtnVisible() === true);
    await page.evaluate(() => window.__nunchi.getTrialKey());
    await page.waitForFunction(() => window.__nunchi.trialKeyActive() === true);
    await page.evaluate(() => window.__nunchi.forceTrialKeyExpire());
    await waitScreen(page, "screen-camerror");
    await page.waitForTimeout(300);
    await errCard(page).screenshot({ path: join(shotsDir, "w21-expired.png") });
    await page.close();
  }

  // 5) mobile 390px button
  {
    const page = await (await browser.newContext({ viewport: { width: 390, height: 860 }, isMobile: true })).newPage();
    page.on("pageerror", (e) => errs.push(String(e)));
    await wireService(page);
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await page.waitForFunction(() => window.__nunchi);
    await page.click("#mode-live");
    await page.waitForFunction(() => window.__nunchi.trialKeyBtnVisible() === true);
    await page.waitForTimeout(300);
    await card(page).screenshot({ path: join(shotsDir, "w21-mobile.png") });
    await page.close();
  }

  await browser.close();
  console.log("captured w21 screenshots; pageErrors=" + errs.length + (errs.length ? " :: " + errs.join(" | ") : ""));
  process.exit(errs.length ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
