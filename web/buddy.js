// buddy.js — "Posture buddy / 자세 인형" 3D view. OWNER: web tab (W10).
//
// Shows a soft pastel clay figure (round head sphere + capsule body + simple eyes/mouth)
// that mirrors the user's head pose from numbers only (FrameResult.overlay.pose:
// yaw/pitch/roll/depth/conf). NO bones, NO skeleton, NO anatomy — child-friendly.
//
// Privacy: this module consumes ONLY the pose numbers. It never touches images or raw
// landmark points. Angles are relative to calibration; signs are the user's own view and
// we flip yaw/roll on screen so it moves the way the user sees themselves (mirror).
//
// Rendering: vendored three.js (web/vendor/three.module.min.js, MIT, pinned r158). If the
// module or WebGL is unavailable we fall back to a 2D angle icon — console errors must be 0.
// Drag/touch rotation is hand-rolled (no OrbitControls). 30fps cap; paused when tab hidden
// or prefers-reduced-motion (no smoothing / no idle drift then).

let THREE = null;
let threeLoadTried = false;

async function loadThree() {
  if (THREE || threeLoadTried) return THREE;
  threeLoadTried = true;
  try {
    THREE = await import("./vendor/three.module.min.js");
  } catch {
    THREE = null; // fallback path will handle it quietly
  }
  return THREE;
}

const DEG = Math.PI / 180;
export const EXAGGERATION = 1.5;     // amplify head motion so it's easy to read (shown on screen)
const CONF_HOLD = 0.5;               // below this, hold the buddy still and say "tracking unsure"
const FRAME_MS = 1000 / 30;          // 30fps cap
const DEPTH_LEAN_DEG = 22;           // how much a full "depth=2" maps to a forward head lean

function prefersReducedMotion() {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
  catch { return false; }
}
function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }

// Posture deviation 0..1 from neutral: combines tilt + forward head. Pure number → colour+word.
export function deviationScore(pose) {
  if (!pose) return 0;
  const tilt = Math.abs(pose.roll_deg || 0) + Math.abs(pose.yaw_deg || 0) * 0.5;
  const down = Math.max(0, pose.pitch_deg || 0);
  const fwd = Math.max(0, ((pose.depth || 1) - 1) * 100); // depth 1.3 → 30
  const raw = tilt / 20 + down / 20 + fwd / 30;
  return clamp(raw, 0, 1);
}

// Calm green/sky when good, warm orange as it deviates. Never red / fear colours.
function postureColor(dev) {
  // interpolate hue from sky-green (good) to warm amber (off). returns {r,g,b} 0..1
  const good = { r: 0.49, g: 0.78, b: 0.62 };  // #7cc79e calm green
  const off = { r: 0.93, g: 0.64, b: 0.33 };   // #eda354 warm amber (no red)
  const k = clamp(dev, 0, 1);
  return {
    r: good.r + (off.r - good.r) * k,
    g: good.g + (off.g - good.g) * k,
    b: good.b + (off.b - good.b) * k,
  };
}

// Plain-language state for aria-label and the 2D fallback. EN/KO via the provided t().
export function describePose(pose, t) {
  if (!pose || (pose.conf != null && pose.conf < CONF_HOLD)) {
    return t ? t("buddyUnsure") : "Tracking unsure";
  }
  const parts = [];
  const roll = Math.round(pose.roll_deg || 0);
  const yaw = Math.round(pose.yaw_deg || 0);
  const pitch = Math.round(pose.pitch_deg || 0);
  const fwd = Math.round(((pose.depth || 1) - 1) * 100);
  const say = (k, v) => (t ? fmt(t(k), { deg: Math.abs(v) }) : `${k} ${Math.abs(v)}`);
  if (Math.abs(roll) >= 3) parts.push(say(roll > 0 ? "buddyTiltRight" : "buddyTiltLeft", roll));
  if (Math.abs(yaw) >= 4) parts.push(say(yaw > 0 ? "buddyTurnRight" : "buddyTurnLeft", yaw));
  if (pitch >= 4) parts.push(say("buddyChinDown", pitch));
  if (fwd >= 6) parts.push(t ? t("buddyForward") : "head forward");
  if (parts.length === 0) return t ? t("buddyNeutral") : "neutral posture";
  return parts.join(", ");
}
function fmt(tpl, vars) { return String(tpl).replace(/\{(\w+)\}/g, (_, k) => (k in vars ? vars[k] : `{${k}}`)); }

// ---------------------------------------------------------------------------
// PostureBuddy: owns a canvas, a three.js scene (or a 2D fallback), and an
// animation loop. Feed it poses with setPose(); it smooths + renders.
// ---------------------------------------------------------------------------
export class PostureBuddy {
  constructor(canvas, { t = null, onAria = null } = {}) {
    this.canvas = canvas;
    this.t = t;
    this.onAria = onAria;           // callback(text) to publish aria-label / status
    this.target = { yaw: 0, pitch: 0, roll: 0, depth: 1, conf: 1 };
    this.shown = { yaw: 0, pitch: 0, roll: 0, lean: 0 };
    this.view = { az: 0, el: 0 };   // user's orbit of the camera (radians)
    this.ghost = false;
    this.reduced = prefersReducedMotion();
    this.running = false;
    this.mode3d = false;
    this._last = 0;
    this._lastAria = "";
    this._disposed = false;
    this._drag = null;
  }

  async init() {
    const three = await loadThree();
    const hasWebGL = three && this._webglOK();
    if (hasWebGL) {
      try { this._initThree(three); this.mode3d = true; }
      catch { this.mode3d = false; }
    }
    if (!this.mode3d) this._init2D();
    this._bindControls();
    this._bindVisibility();
    this.start();
    return this.mode3d;
  }

  _webglOK() {
    try {
      const c = document.createElement("canvas");
      return !!(c.getContext("webgl2") || c.getContext("webgl"));
    } catch { return false; }
  }

  _initThree(three) {
    const w = this.canvas.clientWidth || 320;
    const h = this.canvas.clientHeight || 300;
    const renderer = new three.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(w, h, false);
    const scene = new three.Scene();
    const cam = new three.PerspectiveCamera(32, w / h, 0.1, 100);
    cam.position.set(0, 0.2, 7.2);
    cam.lookAt(0, 0.1, 0);

    // soft lighting, gentle shadow-free look
    scene.add(new three.AmbientLight(0xffffff, 0.85));
    const key = new three.DirectionalLight(0xffffff, 0.55);
    key.position.set(2, 3, 4);
    scene.add(key);

    // --- buddy: a group so we can rotate the head only and lean the whole body ---
    const buddy = new three.Group();
    const body = new three.Group();   // leans forward on depth>1
    const head = new three.Group();   // yaw/pitch/roll go here

    const skinColor = 0x7cc79e;
    const mat = (c) => new three.MeshStandardMaterial({ color: c, roughness: 0.85, metalness: 0.0 });
    this._skinMat = mat(skinColor);
    this._skinMat2 = mat(skinColor);

    // rounded body (capsule). CapsuleGeometry exists in r158.
    const torso = new three.Mesh(new three.CapsuleGeometry(0.9, 1.0, 8, 24), this._skinMat);
    torso.position.y = -1.15;
    body.add(torso);

    // round head (sphere)
    const headMesh = new three.Mesh(new three.SphereGeometry(0.95, 36, 28), this._skinMat2);
    head.add(headMesh);

    // simple face: two eyes + a small mouth, on +z (facing camera at neutral)
    const faceMat = new three.MeshStandardMaterial({ color: 0x2b3a4a, roughness: 0.6 });
    const eyeGeo = new three.SphereGeometry(0.12, 16, 12);
    const eyeL = new three.Mesh(eyeGeo, faceMat); eyeL.position.set(-0.32, 0.12, 0.86);
    const eyeR = new three.Mesh(eyeGeo, faceMat); eyeR.position.set(0.32, 0.12, 0.86);
    const mouth = new three.Mesh(new three.BoxGeometry(0.34, 0.07, 0.06), faceMat);
    mouth.position.set(0, -0.28, 0.9);
    head.add(eyeL, eyeR, mouth);
    head.position.y = 0.15;

    body.add(head);
    buddy.add(body);
    scene.add(buddy);

    // ghost: a translucent green buddy at the neutral pose, toggled on
    // Ghost = the good (neutral) posture, overlaid for comparison. Kept in a DIFFERENT colour
    // family from the buddy (buddy is green→amber; ghost is faint SKY-BLUE) so the two never
    // merge, plus a thin silhouette outline (back-side shell — NOT a wireframe) so its shape
    // reads even from the side. A text legend ("faint outline = good posture") carries the
    // meaning too, so it is never colour-only.
    const GHOST_SKY = 0x8fd0ff;
    const ghost = buddy.clone(true);
    const ghostMeshes = [];
    ghost.traverse((o) => { if (o.isMesh) ghostMeshes.push(o); });
    for (const o of ghostMeshes) {
      o.material = new three.MeshStandardMaterial({
        color: GHOST_SKY, transparent: true, opacity: 0.16, roughness: 1,
        depthWrite: false,
      });
      o.renderOrder = 1;
      // thin outline: a slightly larger back-side shell in a stronger sky-blue
      const outline = new three.Mesh(
        o.geometry,
        new three.MeshBasicMaterial({
          color: GHOST_SKY, transparent: true, opacity: 0.5,
          side: three.BackSide, depthWrite: false,
        })
      );
      outline.scale.setScalar(1.05);
      outline.renderOrder = 0;
      o.add(outline);
    }
    ghost.visible = false;
    scene.add(ghost);

    this._three = three;
    this._renderer = renderer;
    this._scene = scene;
    this._cam = cam;
    this._buddy = buddy;
    this._body = body;
    this._head = head;
    this._ghost = ghost;

    // keep canvas sized to its box
    this._resize = () => {
      const W = this.canvas.clientWidth || w, H = this.canvas.clientHeight || h;
      renderer.setSize(W, H, false);
      cam.aspect = W / H; cam.updateProjectionMatrix();
    };
    window.addEventListener("resize", this._resize);
  }

  _init2D() {
    // 2D fallback: a flat face that tilts/looks — angle icon + text. No WebGL needed.
    this.canvas.classList.add("buddy-2d");
    this._ctx = this.canvas.getContext("2d");
  }

  // ---- public API ----------------------------------------------------------
  setPose(pose) {
    if (!pose || typeof pose !== "object") return;
    const conf = pose.conf == null ? 1 : pose.conf;
    this.target = {
      yaw: pose.yaw_deg || 0,
      pitch: pose.pitch_deg || 0,
      roll: pose.roll_deg || 0,
      depth: pose.depth == null ? 1 : pose.depth,
      conf,
    };
    this._lastPose = pose;
    // publish plain-language state for screen readers
    const aria = describePose(conf < CONF_HOLD ? null : pose, this.t);
    if (aria !== this._lastAria && this.onAria) { this._lastAria = aria; this.onAria(aria); }
  }

  setGhost(on) { this.ghost = !!on; if (this._ghost) this._ghost.visible = this.ghost; }

  setView(azDeg, elDeg) { this.view.az = (azDeg || 0) * DEG; this.view.el = (elDeg || 0) * DEG; }
  resetView() { this.view.az = 0; this.view.el = 0; }
  nudgeView(dAzDeg, dElDeg) {
    this.view.az = clamp(this.view.az + (dAzDeg || 0) * DEG, -Math.PI, Math.PI);
    this.view.el = clamp(this.view.el + (dElDeg || 0) * DEG, -70 * DEG, 70 * DEG);
  }

  start() {
    if (this.running || this._disposed) return;
    this.running = true;
    this._last = performance.now();
    const loop = (now) => {
      if (!this.running || this._disposed) return;
      this._raf = requestAnimationFrame(loop);
      if (now - this._last < FRAME_MS) return; // 30fps cap
      this._last = now;
      this._step();
    };
    this._raf = requestAnimationFrame(loop);
  }
  stop() { this.running = false; if (this._raf) cancelAnimationFrame(this._raf); }

  dispose() {
    this._disposed = true;
    this.stop();
    if (this._resize) window.removeEventListener("resize", this._resize);
    if (this._renderer) { try { this._renderer.dispose(); } catch {} }
  }

  // ---- per-frame ------------------------------------------------------------
  _step() {
    const lowConf = this.target.conf < CONF_HOLD;
    // Smoothing: lerp toward target unless reduced-motion (then snap). Hold still on low conf.
    const alpha = this.reduced ? 1 : 0.18;
    if (!lowConf) {
      this.shown.yaw += (this.target.yaw - this.shown.yaw) * alpha;
      this.shown.pitch += (this.target.pitch - this.shown.pitch) * alpha;
      this.shown.roll += (this.target.roll - this.shown.roll) * alpha;
      const leanTarget = clamp((this.target.depth - 1), 0, 1.2) * DEPTH_LEAN_DEG;
      this.shown.lean += (leanTarget - this.shown.lean) * alpha;
    }
    if (this.mode3d) this._render3D(lowConf);
    else this._render2D(lowConf);
  }

  _render3D(lowConf) {
    const E = EXAGGERATION;
    // Screen is a mirror of the user: flip yaw & roll so the buddy moves the way the user sees.
    const yaw = -this.shown.yaw * E * DEG;
    const roll = -this.shown.roll * E * DEG;
    const pitch = this.shown.pitch * E * DEG; // chin-down stays chin-down
    this._head.rotation.set(pitch, yaw, roll);
    // depth>1: push head forward (+z toward camera) and bow the body a little
    const fwd = clamp((this.shown.lean / DEPTH_LEAN_DEG), 0, 1.2);
    this._head.position.z = fwd * 0.6;
    this._body.rotation.x = (this.shown.lean * DEG) * 0.4;

    // orbit camera around the buddy for the user's x/y/z views
    const r = 7.2;
    const az = this.view.az, el = this.view.el;
    this._cam.position.set(
      r * Math.cos(el) * Math.sin(az),
      0.2 + r * Math.sin(el),
      r * Math.cos(el) * Math.cos(az)
    );
    this._cam.lookAt(0, 0.0, 0);

    // colour by deviation (unless unsure → neutral grey-green, no alarming shift)
    const dev = lowConf ? 0 : deviationScore(this._lastPose);
    const c = postureColor(dev);
    if (this._skinMat) { this._skinMat.color.setRGB(c.r, c.g, c.b); this._skinMat2.color.setRGB(c.r, c.g, c.b); }

    this._renderer.render(this._scene, this._cam);
  }

  _render2D(lowConf) {
    const ctx = this._ctx; if (!ctx) return;
    const W = this.canvas.width, H = this.canvas.height;
    ctx.clearRect(0, 0, W, H);
    const cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.28;
    const E = EXAGGERATION;
    const dev = lowConf ? 0 : deviationScore(this._lastPose);
    const c = postureColor(dev);
    const rgb = `rgb(${Math.round(c.r * 255)},${Math.round(c.g * 255)},${Math.round(c.b * 255)})`;
    ctx.save();
    ctx.translate(cx, cy);
    if (!lowConf) ctx.rotate((-this.shown.roll * E) * DEG); // tilt the face icon
    // head
    ctx.fillStyle = rgb;
    ctx.beginPath(); ctx.arc(0, 0, R, 0, Math.PI * 2); ctx.fill();
    // eyes (shift horizontally with yaw as a simple "look" cue)
    const look = lowConf ? 0 : clamp(-this.shown.yaw * E / 30, -1, 1) * R * 0.2;
    ctx.fillStyle = "#2b3a4a";
    ctx.beginPath(); ctx.arc(-R * 0.35 + look, -R * 0.1, R * 0.12, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.arc(R * 0.35 + look, -R * 0.1, R * 0.12, 0, Math.PI * 2); ctx.fill();
    // mouth
    ctx.fillRect(-R * 0.25, R * 0.3, R * 0.5, R * 0.08);
    ctx.restore();
  }

  // ---- input: drag + touch rotate, keyboard ---------------------------------
  _bindControls() {
    const el = this.canvas;
    const down = (x, y) => { this._drag = { x, y, az: this.view.az, el: this.view.el }; };
    const move = (x, y) => {
      if (!this._drag) return;
      const dx = x - this._drag.x, dy = y - this._drag.y;
      this.view.az = clamp(this._drag.az + dx * 0.012, -Math.PI, Math.PI);
      this.view.el = clamp(this._drag.el - dy * 0.012, -70 * DEG, 70 * DEG);
    };
    const up = () => { this._drag = null; };

    el.addEventListener("pointerdown", (e) => { el.setPointerCapture?.(e.pointerId); down(e.clientX, e.clientY); });
    el.addEventListener("pointermove", (e) => move(e.clientX, e.clientY));
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    el.addEventListener("pointerleave", up);

    // keyboard: arrows rotate, Home resets. Canvas is focusable (tabindex set in HTML).
    el.addEventListener("keydown", (e) => {
      const step = 12;
      if (e.key === "ArrowLeft") { this.nudgeView(-step, 0); e.preventDefault(); }
      else if (e.key === "ArrowRight") { this.nudgeView(step, 0); e.preventDefault(); }
      else if (e.key === "ArrowUp") { this.nudgeView(0, step); e.preventDefault(); }
      else if (e.key === "ArrowDown") { this.nudgeView(0, -step); e.preventDefault(); }
      else if (e.key === "Home") { this.resetView(); e.preventDefault(); }
    });
  }

  _bindVisibility() {
    this._onVis = () => { if (document.hidden) this.stop(); else this.start(); };
    document.addEventListener("visibilitychange", this._onVis);
  }
}

// Resolve a single pose sample from a fixture time series at time t (seconds).
export function samplePoseAt(fixture, tSec) {
  if (!fixture || !Array.isArray(fixture.samples) || fixture.samples.length === 0) return null;
  const s = fixture.samples;
  if (tSec <= s[0].t) return s[0];
  if (tSec >= s[s.length - 1].t) return s[s.length - 1];
  for (let i = 1; i < s.length; i++) {
    if (tSec <= s[i].t) {
      const a = s[i - 1], b = s[i];
      const span = b.t - a.t || 1;
      const k = (tSec - a.t) / span;
      const lerp = (x, y) => x + (y - x) * k;
      return {
        t: tSec,
        yaw_deg: lerp(a.yaw_deg, b.yaw_deg),
        pitch_deg: lerp(a.pitch_deg, b.pitch_deg),
        roll_deg: lerp(a.roll_deg, b.roll_deg),
        depth: lerp(a.depth, b.depth),
        // confidence: take the lower of the two so a dip is not smoothed away
        conf: Math.min(a.conf, b.conf),
      };
    }
  }
  return s[s.length - 1];
}
