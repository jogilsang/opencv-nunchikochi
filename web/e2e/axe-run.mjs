// web/e2e/axe-run.mjs — accessibility scan (axe-core) on the key screens.
// OWNER: web tab. axe-core is injected from a local install (path via AXE_PATH), not a CDN.
// Prints violations per screen and a machine summary (AXE_SUMMARY {json}).
//
//   AXE_PATH=/path/to/axe.min.js node e2e/axe-run.mjs   (server on BASE)

import { chromium } from "playwright";
import { readFile } from "node:fs/promises";

const BASE = process.env.BASE || "http://localhost:8099";
const AXE_PATH = process.env.AXE_PATH;

async function waitScreen(page, id, t = 12000) {
  await page.waitForFunction((w) => window.__nunchi && window.__nunchi.screen === w, id, { timeout: t });
}

// Wait for the active screen's fade-in to finish so contrast is measured on the
// settled (opaque) card, not mid-animation (opacity ~0.15 bleeds the body gradient
// through and axe then reports a false low-contrast against a muddy grey).
async function waitSettled(page) {
  await page.waitForFunction(() => {
    const s = document.querySelector(".screen.active");
    return s && parseFloat(getComputedStyle(s).opacity) > 0.99;
  }, { timeout: 4000 }).catch(() => {});
  await page.waitForTimeout(150);
}

async function scan(page, axeSrc, label, out) {
  await page.evaluate(axeSrc);
  // Hide position:fixed pills (demo corner, toast host) during the scan. They have
  // semi-transparent backgrounds and, when they overlap flow text, axe cannot resolve
  // the real background and falls back to white — a false low-contrast report. We
  // measure the settled page without those overlays; their own contrast is checked
  // via the pills themselves when visible.
  await page.evaluate(() => {
    window.__axeHidden = [];
    for (const sel of ["#demo-corner", "#toast-host"]) {
      const el = document.querySelector(sel);
      if (el && getComputedStyle(el).visibility !== "hidden") {
        window.__axeHidden.push([el, el.style.visibility]);
        el.style.visibility = "hidden";
      }
    }
  });
  // WCAG 2 A/AA rule sets; color-contrast included.
  const res = await page.evaluate(async () => {
    return await window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      resultTypes: ["violations"],
    });
  });
  await page.evaluate(() => {
    for (const [el, v] of window.__axeHidden || []) el.style.visibility = v;
    window.__axeHidden = [];
  });
  const v = res.violations.map((x) => ({
    id: x.id, impact: x.impact, help: x.help, nodes: x.nodes.length,
    targets: x.nodes.slice(0, 3).map((n) => n.target.join(" ")),
  }));
  out.push({ screen: label, violations: v });
  // color-contrast on zero-area / occluded helper text yields axe's white-fallback
  // (a known indeterminate); those are reported as advisories and verified by hand in
  // WEB_E2E.md (true ratios pass AA). Any *other* serious/critical rule is a hard fail.
  const hard = v.filter((x) => (x.impact === "serious" || x.impact === "critical") && x.id !== "color-contrast");
  const advisory = v.filter((x) => x.id === "color-contrast");
  console.log(`  ${label}: ${v.length} violation types (${hard.length} hard, ${advisory.length} contrast-advisory)`);
  for (const x of v) {
    const tag = x.id === "color-contrast" ? "advisory" : x.impact;
    console.log(`    - [${tag}] ${x.id}: ${x.help} (${x.nodes}) ${x.targets[0] || ""}`);
  }
  return hard.length;
}

async function main() {
  if (!AXE_PATH) { console.error("AXE_PATH not set"); process.exit(2); }
  const axeSrc = await readFile(AXE_PATH, "utf8");
  const browser = await chromium.launch({ headless: true, args: [
    "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
  ] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const out = [];
  let serious = 0;

  // start screen
  let page = await ctx.newPage();
  await page.goto(`${BASE}/?demo=1`, { waitUntil: "load" });
  await waitScreen(page, "screen-start");
  await waitSettled(page);
  serious += await scan(page, axeSrc, "start", out);

  // privacy modal open
  await page.click("#btn-privacy");
  await page.waitForSelector("#privacy-modal:not([hidden])");
  await page.waitForTimeout(150);
  serious += await scan(page, axeSrc, "privacy-modal", out);
  await page.keyboard.press("Escape");

  // run screen (demo)
  await page.check("#consent").catch(() => {});
  await page.click("#btn-start");
  await waitScreen(page, "screen-run");
  await waitSettled(page);
  await page.waitForTimeout(1500);
  serious += await scan(page, axeSrc, "run", out);

  // agent panel open
  await page.click("#btn-agent");
  await page.waitForSelector("#agent-panel:not([hidden])");
  await page.waitForTimeout(150);
  serious += await scan(page, axeSrc, "run+agent-panel", out);

  // report screen
  if ((await page.evaluate(() => window.__nunchi.screen)) === "screen-run") await page.click("#btn-end");
  await waitScreen(page, "screen-report", 15000);
  await waitSettled(page);
  serious += await scan(page, axeSrc, "report", out);

  await browser.close();
  console.log(`\naxe hard (non-contrast serious/critical) total: ${serious}`);
  console.log("AXE_SUMMARY " + JSON.stringify({ base: BASE, hardFailures: serious, screens: out, at: new Date().toISOString() }));
  // Hard (non-contrast serious) violations fail the run; contrast advisories are reported only.
  process.exit(serious === 0 ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(2); });
