// web/e2e/capture-w5.mjs — before/after screenshots for the three W5 defect fixes.
// OWNER: web tab. "before" is reproduced by re-injecting the pre-fix behaviour in-page
// (CSS/JS) so no git revert is needed; "after" is the shipped code as-is.
// Output: docs/screenshots/w5-*.png

import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";

const BASE = process.env.BASE || "http://localhost:8099";
const OUT = process.env.OUT || "../docs/screenshots";

async function waitScreen(page, id, t = 12000) {
  await page.waitForFunction((w) => window.__nunchi && window.__nunchi.screen === w, id, { timeout: t });
}
async function toRun(page) {
  await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
  await waitScreen(page, "screen-start");
  await page.check("#consent").catch(() => {});
  await page.click("#btn-start");
  await waitScreen(page, "screen-run", 12000);
  await page.waitForTimeout(400);
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true, args: [
    "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
  ] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const mobile = await browser.newContext({ viewport: { width: 390, height: 780 }, isMobile: true });

  // -------- defect ① toast over metric cards --------
  // BEFORE: force the old top-right host and spawn 3 toasts (old behaviour had no cap).
  {
    const page = await ctx.newPage();
    await toRun(page);
    await page.addStyleTag({ content: `
      #toast-host { top: 76px !important; bottom: auto !important;
        flex-direction: column !important; }` });
    await page.evaluate(() => {
      const host = document.getElementById("toast-host");
      host.innerHTML = "";
      for (const m of ["Sit back a little — you're leaning in.",
                       "Straighten up — your head is tilting.",
                       "You've been close for a while."]) {
        const t = document.createElement("div"); t.className = "toast";
        const p = document.createElement("p"); p.className = "msg"; p.textContent = m;
        t.appendChild(p); host.appendChild(t);
      }
    });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${OUT}/w5-01a-toast-before.png` });
    await page.close();
  }
  // AFTER: real app, let the demo fire nudges; cap keeps <=2, bottom-right, clear of cards.
  {
    const page = await ctx.newPage();
    await toRun(page);
    await page.waitForTimeout(4000); // let several nudges fire
    await page.screenshot({ path: `${OUT}/w5-01b-toast-after.png` });
    await page.close();
  }

  // -------- defect ② demo badge/corner overlapping body text (narrow width) --------
  // BEFORE: old bottom-right corner that could sit over the bottom-right flow + no ellipsis.
  {
    const page = await mobile.newPage();
    await toRun(page);
    await page.addStyleTag({ content: `
      #demo-corner { left: auto !important; right: 14px !important; bottom: 14px !important;
        white-space: normal !important; max-width: 70vw !important; }` });
    await page.evaluate(() => {
      const el = document.getElementById("demo-corner");
      el.querySelector("span").textContent = "Demo playback — not a real camera";
    });
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${OUT}/w5-02a-democorner-before.png`, fullPage: true });
    await page.close();
  }
  // AFTER: shipped bottom-left pill, nowrap + ellipsis, clear of bottom-right toasts.
  {
    const page = await mobile.newPage();
    await toRun(page);
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${OUT}/w5-02b-democorner-after.png`, fullPage: true });
    await page.close();
  }

  // -------- defect ③ "mock preview" label mirror-flipped --------
  // The run-screen preview is the one holding #run-canvas (CSS-mirrored).
  const runPreview = "#screen-run .preview";
  // BEFORE: re-draw the label WITHOUT the counter-flip (reproduces reversed text under CSS mirror).
  {
    const page = await ctx.newPage();
    await toRun(page);
    await page.evaluate(() => {
      const c = document.getElementById("run-canvas");
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#8aa0c0";
      ctx.font = "12px system-ui, sans-serif";
      ctx.setTransform(1, 0, 0, 1, 0, 0); // plain draw -> flips under CSS scaleX(-1)
      ctx.fillText("mock preview", 10, c.height - 12);
    });
    await page.waitForTimeout(200);
    const box1 = await page.locator(runPreview).boundingBox();
    console.log("before preview box:", JSON.stringify(box1));
    if (box1) await page.screenshot({ path: `${OUT}/w5-03a-label-before.png`, clip: box1 });
    await page.close();
  }
  // AFTER: shipped counter-flipped label reads normally.
  {
    const page = await ctx.newPage();
    await toRun(page);
    await page.waitForTimeout(700);
    const box2 = await page.locator(runPreview).boundingBox();
    console.log("after preview box:", JSON.stringify(box2));
    if (box2) await page.screenshot({ path: `${OUT}/w5-03b-label-after.png`, clip: box2 });
    await page.close();
  }

  await browser.close();
  console.log("captured w5 before/after screenshots to", OUT);
}
main().catch((e) => { console.error(e); process.exit(2); });
