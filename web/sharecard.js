// sharecard.js — render a numbers-only share card to PNG (no face, no image). OWNER: web tab.
// Brand tone matches the app. EN/KO via passed strings.

import { t, getLang } from "./i18n.js";

const W = 1200;
const H = 630; // social-card ratio

/**
 * Build a share card PNG blob from a SessionSummary.
 * @param {object} summary SessionSummary
 * @param {string[]} highlights up to 3 short strings
 * @returns {Promise<Blob>}
 */
export function buildShareCard(summary, highlights = []) {
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");

  // background
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, "#16202e");
  g.addColorStop(1, "#0e141c");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  // brand
  ctx.fillStyle = "#5b9df0";
  ctx.beginPath();
  ctx.arc(70, 82, 11, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#e8eef6";
  ctx.font = "700 40px system-ui, -apple-system, 'Segoe UI', sans-serif";
  ctx.fillText(t("appName"), 94, 96);
  ctx.fillStyle = "#9fb0c6";
  ctx.font = "400 24px system-ui, sans-serif";
  ctx.fillText(`${t("shareCardSub")} · ${summary.date || ""}`, 70, 140);

  // big number tiles
  const mins = Math.round((summary.duration_s || 0) / 60);
  const tiles = [
    { n: `${mins}`, u: t("min"), k: t("reportDuration") },
    { n: `${summary.nudges_sent ?? 0}`, u: "", k: t("reportNudges") },
    { n: `${summary.nudges_suppressed ?? 0}`, u: "", k: t("reportSuppressed") },
    { n: `${summary.confirmations_asked ?? 0}`, u: "", k: t("reportConfirms") },
  ];
  const tileW = 255;
  const tileH = 170;
  const gap = 24;
  const startX = 70;
  const topY = 196;
  tiles.forEach((tile, i) => {
    const x = startX + i * (tileW + gap);
    rr(ctx, x, topY, tileW, tileH, 16);
    ctx.fillStyle = "#1d2836";
    ctx.fill();
    ctx.strokeStyle = "#2a3850";
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = "#e8eef6";
    ctx.font = "800 62px system-ui, sans-serif";
    ctx.fillText(tile.n, x + 22, topY + 86);
    if (tile.u) {
      const nw = ctx.measureText(tile.n).width;
      ctx.fillStyle = "#9fb0c6";
      ctx.font = "600 26px system-ui, sans-serif";
      ctx.fillText(tile.u, x + 22 + nw + 8, topY + 86);
    }
    ctx.fillStyle = "#9fb0c6";
    ctx.font = "500 22px system-ui, sans-serif";
    ctx.fillText(tile.k, x + 22, topY + 134);
  });

  // highlights
  let hy = 452;
  ctx.fillStyle = "#9fb0c6";
  ctx.font = "600 22px system-ui, sans-serif";
  ctx.fillText(t("highlightsTitle"), 70, hy);
  hy += 34;
  ctx.font = "400 24px system-ui, sans-serif";
  for (const h of (highlights || []).slice(0, 3)) {
    ctx.fillStyle = "#5b9df0";
    ctx.fillText("•", 70, hy);
    ctx.fillStyle = "#e8eef6";
    ctx.fillText(String(h), 94, hy);
    hy += 34;
  }

  // privacy footer (reinforce honest claim)
  ctx.fillStyle = "#6b7c93";
  ctx.font = "400 18px system-ui, sans-serif";
  const footer = getLang() === "ko"
    ? "숫자만 공유됩니다 · 영상은 저장되지 않습니다"
    : "Numbers only — no video is ever stored";
  ctx.fillText(footer, 70, H - 36);

  return new Promise((resolve) => canvas.toBlob((b) => resolve(b), "image/png"));
}

/** Trigger a browser download of a blob. */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function rr(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
