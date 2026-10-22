// capture.js — camera capture + frame pump. OWNER: web tab.
// getUserMedia -> 320x240 -> JPEG(0.7) -> <=2 fps. Pauses when tab hidden.
// A fake canvas source (animated pattern) powers mock mode / no-camera demos.

export const CAM = { OK: "ok", DENIED: "denied", NONE: "none", INSECURE: "insecure", ERROR: "error" };

const TARGET_W = 320;
const TARGET_H = 240;
const JPEG_QUALITY = 0.7;

export function isSecure() {
  // Cameras require HTTPS or localhost.
  return window.isSecureContext || ["localhost", "127.0.0.1"].includes(location.hostname);
}

export class Capture {
  constructor({ fps = 2, mock = false } = {}) {
    this.fps = Math.max(0.5, Math.min(fps, 2)); // contract: <= 2 fps
    this.mock = mock;
    this.stream = null;
    this.video = document.createElement("video");
    this.video.muted = true;
    this.video.playsInline = true;
    this._canvas = document.createElement("canvas");
    this._canvas.width = TARGET_W;
    this._canvas.height = TARGET_H;
    this._ctx = this._canvas.getContext("2d");
    this._timer = null;
    this._fakeRaf = null;
    this._fakeT = 0;
  }

  // Returns a CAM.* status. On OK, this.video is playing.
  async start() {
    if (this.mock) {
      this._startFake();
      return CAM.OK;
    }
    if (!isSecure()) return CAM.INSECURE;
    if (!navigator.mediaDevices?.getUserMedia) return CAM.NONE;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: TARGET_W }, height: { ideal: TARGET_H }, facingMode: "user" },
        audio: false,
      });
      this.video.srcObject = this.stream;
      await this.video.play();
      return CAM.OK;
    } catch (e) {
      const name = e && e.name;
      if (name === "NotAllowedError" || name === "SecurityError") return CAM.DENIED;
      if (name === "NotFoundError" || name === "OverconstrainedError" || name === "DevicesNotFoundError") return CAM.NONE;
      return CAM.ERROR;
    }
  }

  // Draws a calm animated canvas as a stand-in for live video (mock / no camera).
  _startFake() {
    const draw = () => {
      this._fakeT += 0.016;
      const ctx = this._ctx;
      const g = ctx.createLinearGradient(0, 0, 0, TARGET_H);
      g.addColorStop(0, "#1b2433");
      g.addColorStop(1, "#0f1620");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, TARGET_W, TARGET_H);
      // a soft "head" oval that gently sways, so the preview looks alive without a real face
      const cx = TARGET_W / 2 + Math.sin(this._fakeT * 0.7) * 10;
      const cy = TARGET_H / 2 + Math.cos(this._fakeT * 0.5) * 6;
      ctx.fillStyle = "#2f3e55";
      ctx.beginPath();
      ctx.ellipse(cx, cy, 52, 66, Math.sin(this._fakeT * 0.3) * 0.12, 0, Math.PI * 2);
      ctx.fill();
      // The preview is CSS-mirrored (scaleX(-1)). Counter-flip just the label so the
      // text reads left-to-right on screen instead of appearing reversed.
      ctx.fillStyle = "#8aa0c0";
      ctx.font = "12px system-ui, sans-serif";
      ctx.save();
      ctx.translate(TARGET_W, 0);
      ctx.scale(-1, 1);
      ctx.textAlign = "left";
      ctx.fillText("mock preview", 10, TARGET_H - 12);
      ctx.restore();
      this._fakeRaf = requestAnimationFrame(draw);
    };
    draw();
  }

  // Capture one frame into a JPEG Blob (null if nothing to draw yet).
  async grab() {
    try {
      if (!this.mock) {
        if (!this.video.videoWidth) return null;
        this._ctx.drawImage(this.video, 0, 0, TARGET_W, TARGET_H);
      }
      // mock: canvas already painted by RAF loop
      const blob = await new Promise((res) => this._canvas.toBlob(res, "image/jpeg", JPEG_QUALITY));
      return blob;
    } catch {
      return null;
    }
  }

  // Source element for on-screen preview (mirrored via CSS). Canvas for mock, video for live.
  previewSource() {
    return this.mock ? this._canvas : this.video;
  }

  // Pump: calls onFrame(blob, timestampSeconds) at <= fps, paused while tab hidden.
  // onFrame may be async; backoff grows on thrown errors and resets on success.
  startPump(onFrame, { startTime = performance.now() } = {}) {
    let backoff = 0;
    const baseInterval = 1000 / this.fps;
    const tick = async () => {
      if (document.hidden) {
        this._timer = setTimeout(tick, baseInterval);
        return;
      }
      const tSec = (performance.now() - startTime) / 1000;
      const blob = await this.grab();
      let wait = baseInterval;
      if (blob) {
        try {
          await onFrame(blob, tSec);
          backoff = 0;
        } catch {
          backoff = Math.min(backoff ? backoff * 2 : baseInterval, 8000); // exponential, capped 8s
          wait = backoff;
        }
      }
      this._timer = setTimeout(tick, wait);
    };
    this._timer = setTimeout(tick, baseInterval);
  }

  stopPump() {
    if (this._timer) clearTimeout(this._timer);
    this._timer = null;
  }

  stop() {
    this.stopPump();
    if (this._fakeRaf) cancelAnimationFrame(this._fakeRaf);
    this._fakeRaf = null;
    if (this.stream) {
      for (const tr of this.stream.getTracks()) tr.stop();
      this.stream = null;
    }
    this.video.srcObject = null;
  }
}
