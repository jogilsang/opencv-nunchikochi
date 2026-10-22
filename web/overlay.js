// overlay.js — draws "what OpenCV sees" (face box + landmark points) over the mirrored preview.
// OWNER: web tab. Input: FrameResult.overlay (0-1 coords in server-frame space). We mirror x.
// Display-only; no pixels/image here. Out-of-range coords are clamped and never throw.

const clamp01 = (v) => (Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : null);

// Mirror x because the on-screen preview is flipped horizontally (scaleX(-1)).
const mx = (x) => 1 - x;

const POINT_COLORS = {
  eye_l: "#5b9df0", eye_r: "#5b9df0",
  nose: "#e8eef6",
  mouth_l: "#58c08a", mouth_r: "#58c08a",
};

/**
 * Draw an overlay onto a canvas sized to the preview.
 * @param {HTMLCanvasElement} canvas overlay canvas (same box as preview)
 * @param {object|null} overlay FrameResult.overlay or null
 */
export function drawOverlay(canvas, overlay) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  if (!overlay || typeof overlay !== "object") return; // server gave nothing -> draw nothing

  // face box: [x, y, w, h] in 0-1. Mirror: left edge becomes 1-(x+w).
  const face = Array.isArray(overlay.face) ? overlay.face : null;
  if (face && face.length === 4) {
    let [x, y, w, h] = face.map((n) => (Number.isFinite(n) ? n : NaN));
    if ([x, y, w, h].every(Number.isFinite)) {
      // clamp box within [0,1]
      x = Math.max(0, Math.min(1, x));
      y = Math.max(0, Math.min(1, y));
      w = Math.max(0, Math.min(1 - x, w));
      h = Math.max(0, Math.min(1 - y, h));
      const px = mx(x + w) * W; // mirrored left
      const py = y * H;
      const pw = w * W;
      const ph = h * H;
      ctx.lineWidth = 2;
      ctx.strokeStyle = "rgba(91,157,240,0.95)";
      roundRect(ctx, px, py, pw, ph, 8);
      ctx.stroke();
      // subtle corner ticks for a "detector" feel
      ctx.strokeStyle = "rgba(91,157,240,0.5)";
      ctx.lineWidth = 1;
    }
  }

  // landmark points
  const points = overlay.points && typeof overlay.points === "object" ? overlay.points : {};
  for (const [name, pt] of Object.entries(points)) {
    if (!Array.isArray(pt) || pt.length < 2) continue;
    const cx = clamp01(pt[0]);
    const cy = clamp01(pt[1]);
    if (cx === null || cy === null) continue;
    const dx = mx(cx) * W;
    const dy = cy * H;
    ctx.beginPath();
    ctx.arc(dx, dy, 3.2, 0, Math.PI * 2);
    ctx.fillStyle = POINT_COLORS[name] || "#9fb0c6";
    ctx.fill();
    ctx.strokeStyle = "rgba(10,16,22,0.6)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }
}

export function clearOverlay(canvas) {
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
}

function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}
