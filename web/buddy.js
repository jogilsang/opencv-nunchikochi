// buddy.js — "Posture buddy / 자세 인형": a FACE + NECK stand-in (W20; was a seated upper-body
// figure in W14, a sphere+capsule in W10). OWNER: web tab.
//
// W20: the buddy is now only the head (with a live face) + a neck + a faint shoulder-line hint.
// The torso, arms, hands, desk and the water-drinking arm lift are GONE — people said "the face
// and neck are enough: my expression, my neck angle." So we draw exactly what we MEASURE plus a
// small neck estimate, and nothing else.
//
// HONESTY: we MEASURE the head angles (yaw/pitch/roll) + depth and the facial channels
// (overlay.expr: eye_l, eye_r, mouth_open, smile, brow_raise) and the drink event. The NECK is an
// ESTIMATE from the measured head angles (see buddy-kinematics.js), and the UI says so. The face
// shows measured facial MOVEMENT — it does NOT guess emotion. We do NOT draw a body. Signs follow
// docs/CONTRACTS.md (the user's own view); we mirror yaw/roll on screen so the buddy moves the way
// the user sees themselves.
//
// Water drinking: with no arm, a drink event just shows a small cup icon near the mouth + a
// "taking a sip" chip for the measured window. It reacts only to the measured `drink` event.
//
// Rendering: vendored three.js (web/vendor/three.module.min.js, MIT, pinned r158). If the module
// or WebGL is unavailable we fall back to a 2D face that reflects the same angles + expression —
// console errors must be 0. Low-poly. Drag/touch rotation is hand-rolled. 30fps cap; paused when
// tab hidden. prefers-reduced-motion: snap (no smoothing) and no breathing.

import { computeRig, neutralRig, neutralExpr, KINEMATICS } from "./buddy-kinematics.js";

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
export const EXAGGERATION = KINEMATICS.EXAGGERATION; // single source of truth (shown on screen)
const CONF_HOLD = KINEMATICS.CONF_HOLD;              // below this, hold still + "tracking unsure"
const FRAME_MS = 1000 / 30;                          // 30fps cap

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
// Appends a short "neck is estimated" clause when the head leans forward, so a screen-reader
// user hears the measured-vs-estimated distinction too (not colour-only, not visual-only).
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
  const leaning = fwd >= 6;
  if (leaning) parts.push(t ? t("buddyForward") : "head forward");
  // facial movement, measured (not emotion). Mention the clear ones so a SR user hears them.
  const e = pose.expr;
  if (e && typeof e === "object") {
    if ((e.mouth_open || 0) >= 0.4) parts.push(t ? (t("buddyMouthOpen") || "mouth open") : "mouth open");
    if ((e.smile || 0) >= 0.4) parts.push(t ? (t("buddySmile") || "smiling") : "smiling");
    const eyeMin = Math.min(e.eye_l == null ? 1 : e.eye_l, e.eye_r == null ? 1 : e.eye_r);
    if (eyeMin <= 0.25) parts.push(t ? (t("buddyEyesClosed") || "eyes closed") : "eyes closed");
  }
  if (pose.drinking && t) parts.push(t("buddyDrinking") || "drinking");
  if (parts.length === 0) return t ? t("buddyNeutral") : "neutral posture";
  let s = parts.join(", ");
  // If the neck is doing something estimated (lean forward), name it as an estimate.
  if (leaning && t) s += " — " + (t("buddyNeckEstimated") || "neck is estimated");
  return s;
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
    this.target = { yaw: 0, pitch: 0, roll: 0, depth: 1, conf: 1, drinking: false, expr: neutralExpr() };
    // smoothed rig values actually shown this frame
    this.shown = {
      yaw: 0, pitch: 0, roll: 0, neckBend: 0, headOffset: 0,
      expr: neutralExpr(),
    };
    this._rig = neutralRig();       // last computed rig (for holds)
    this.view = { az: 0, el: 0 };   // user's orbit of the camera (radians)
    this.ghost = false;
    this.reduced = prefersReducedMotion();
    this.running = false;
    this.mode3d = false;
    this._last = 0;
    this._lastAria = "";
    this._disposed = false;
    this._drag = null;
    this._t0 = performance.now();   // for the gentle breathing idle
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
    // Probe WebGL support WITHOUT leaking a context: software-GL backends have a tiny context
    // budget, and a lingering probe context can make the real renderer fail to init and fall
    // back to 2D intermittently. Create, test, then explicitly lose the probe context.
    try {
      const c = document.createElement("canvas");
      const gl = c.getContext("webgl2") || c.getContext("webgl");
      if (!gl) return false;
      try { gl.getExtension("WEBGL_lose_context")?.loseContext(); } catch {}
      return true;
    } catch { return false; }
  }

  _initThree(three) {
    const w = this.canvas.clientWidth || 320;
    const h = this.canvas.clientHeight || 300;
    const renderer = new three.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.setSize(w, h, false);
    const scene = new three.Scene();
    const cam = new three.PerspectiveCamera(30, w / h, 0.1, 100);
    cam.position.set(0, 0.15, 6.4);
    cam.lookAt(0, 0.1, 0);

    // soft, shadow-free lighting
    scene.add(new three.AmbientLight(0xffffff, 0.9));
    const key = new three.DirectionalLight(0xffffff, 0.45);
    key.position.set(2, 3, 4);
    scene.add(key);

    const skinColor = 0x7cc79e;
    const mkMat = (c) => new three.MeshStandardMaterial({ color: c, roughness: 0.9, metalness: 0.0 });

    // skin material is shared across skin parts so the deviation colour tints head + neck
    this._skinMat = mkMat(skinColor);
    const faceMat = new three.MeshStandardMaterial({ color: 0x2b3a4a, roughness: 0.6 });

    // --- rig groups: just a neck pivot and a head (child-friendly, head slightly large) ------
    const buddy = new three.Group();     // whole figure (head + neck)
    const neck = new three.Group();      // neck bend pivot (base of the neck)
    const head = new three.Group();      // measured yaw/pitch/roll

    // a faint, level shoulder-line hint so the head has somewhere to sit (we do NOT draw a body
    // and we do NOT measure shoulder tilt — it stays level and is a thin, low-opacity bar).
    const shoulderHint = new three.Mesh(new three.CapsuleGeometry(0.14, 1.5, 3, 8), mkMat(0x4a5a6e));
    shoulderHint.rotation.z = Math.PI / 2;
    shoulderHint.position.y = -0.95;
    shoulderHint.material.transparent = true;
    shoulderHint.material.opacity = 0.35;
    buddy.add(shoulderHint);

    // neck (skin) rises from the shoulder line; head sits on top
    const neckMesh = new three.Mesh(new three.CylinderGeometry(0.24, 0.3, 0.6, 12), this._skinMat);
    neckMesh.position.y = 0.0;
    neck.add(neckMesh);
    neck.position.y = -0.62;         // base of the neck, just above the shoulder hint
    buddy.add(neck);

    // head: a slightly large smooth sphere + a simple, expressive face on +z. A soft rim light is
    // added separately; the sphere itself is high-ish poly so it reads as a smooth round head.
    const headMesh = new three.Mesh(new three.SphereGeometry(0.95, 28, 18), this._skinMat);
    head.add(headMesh);

    // --- eyes: white sclera + dark pupil, with a skin upper-lid that lowers to close ----------
    // Bigger than W20's tiny holes so open/closed reads clearly (sizes are exaggerated for
    // legibility — the on-screen ~1.5x note covers this). Each eye is its own group so a wink
    // (one eye closing) is independent.
    const scleraMat = new three.MeshStandardMaterial({ color: 0xf2f6fb, roughness: 0.5 });
    const EYE_R = 0.18, EYE_Y = 0.14, EYE_X = 0.34, EYE_Z = 0.80;
    const makeEye = (sx) => {
      const g = new three.Group();
      const sclera = new three.Mesh(new three.SphereGeometry(EYE_R, 12, 8), scleraMat);
      sclera.scale.set(1.15, 1, 0.5);                 // slightly wide, flattened onto the face
      const pupil = new three.Mesh(new three.SphereGeometry(EYE_R * 0.52, 10, 8), faceMat);
      pupil.position.z = EYE_R * 0.42;                 // sits in front of the sclera
      // upper lid: a skin cap that slides down over the eye to "close" it
      const lid = new three.Mesh(new three.SphereGeometry(EYE_R * 1.18, 12, 6, 0, Math.PI * 2, 0, Math.PI / 2), this._skinMat);
      lid.scale.set(1.15, 1.0, 0.6);
      lid.position.y = EYE_R;                          // fully up (eye open) by default
      g.add(sclera, pupil, lid);
      g.position.set(sx, EYE_Y, EYE_Z);
      g._lid = lid; g._pupil = pupil;
      return g;
    };
    const eyeL = makeEye(-EYE_X);
    const eyeR = makeEye(EYE_X);

    // --- brows: soft bars above the eyes; rise + tilt with brow_raise -------------------------
    const browGeo = new three.BoxGeometry(0.34, 0.07, 0.06);
    const browBaseY = EYE_Y + 0.26;                    // comfortably above the eyes (no overlap)
    const browL = new three.Mesh(browGeo, faceMat); browL.position.set(-EYE_X, browBaseY, 0.86);
    const browR = new three.Mesh(browGeo, faceMat); browR.position.set(EYE_X, browBaseY, 0.86);

    // --- mouth: a curved smile arc + a round open-mouth, blended by smile / mouth_open --------
    // smile line = a thin partial torus bowed upward (never a rectangle). Its arc angle + lift
    // grow with `smile`; near-neutral it is a short, almost-flat line.
    const smileMat = faceMat;
    const smileArc = new three.Mesh(new three.TorusGeometry(0.26, 0.035, 8, 18, Math.PI), smileMat);
    // the open mouth = a dark rounded cavity (flattened sphere) that grows with mouth_open
    const openMat = new three.MeshStandardMaterial({ color: 0x1b2430, roughness: 0.8 });
    const openMouth = new three.Mesh(new three.SphereGeometry(0.17, 14, 10), openMat);
    const mouth = new three.Group();
    mouth.add(smileArc, openMouth);
    mouth.position.set(0, -0.34, 0.82);
    mouth._smile = smileArc; mouth._open = openMouth;

    head.add(eyeL, eyeR, browL, browR, mouth);
    head.position.y = 0.72;         // sit the head on top of the neck
    neck.add(head);

    // a small cup icon that appears near the mouth ONLY during a measured drink event (no arm).
    const cup = new three.Mesh(new three.CylinderGeometry(0.12, 0.1, 0.26, 10), mkMat(0xcfd8e6));
    cup.visible = false;
    cup.position.set(0, -0.46, 1.04); // just in front of the mouth
    head.add(cup);

    // keep handles to the face parts so _render3D can drive expression
    this._face = { eyeL, eyeR, browL, browR, mouth, cup, browBaseY };
    this._faceMat = faceMat;

    scene.add(buddy);

    // ghost: a translucent SKY-BLUE copy of the head+neck at the neutral/good posture, with a
    // thin back-side outline so its shape reads from any angle. Different colour family from the
    // buddy (green→amber) so the two never merge; a text legend carries the meaning too.
    const GHOST_SKY = 0x8fd0ff;
    const ghost = buddy.clone(true);
    const ghostMeshes = [];
    ghost.traverse((o) => { if (o.isMesh) ghostMeshes.push(o); });
    for (const o of ghostMeshes) {
      o.material = new three.MeshStandardMaterial({
        color: GHOST_SKY, transparent: true, opacity: 0.15, roughness: 1, depthWrite: false,
      });
      o.renderOrder = 1;
      const outline = new three.Mesh(
        o.geometry,
        new three.MeshBasicMaterial({ color: GHOST_SKY, transparent: true, opacity: 0.5, side: three.BackSide, depthWrite: false })
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
    this._neck = neck;
    this._head = head;
    this._ghost = ghost;

    // report the triangle budget once (helps keep us low-poly)
    try {
      let tris = 0;
      buddy.traverse((o) => { if (o.isMesh && o.geometry?.index) tris += o.geometry.index.count / 3; else if (o.isMesh && o.geometry?.attributes?.position) tris += o.geometry.attributes.position.count / 3; });
      this.triangleCount = Math.round(tris);
    } catch { this.triangleCount = 0; }

    this._resize = () => {
      const W = this.canvas.clientWidth || w, H = this.canvas.clientHeight || h;
      renderer.setSize(W, H, false);
      cam.aspect = W / H; cam.updateProjectionMatrix();
    };
    window.addEventListener("resize", this._resize);
  }

  _init2D() {
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
      drinking: !!pose.drinking,
      expr: pose.expr && typeof pose.expr === "object" ? pose.expr : null,
    };
    this._lastPose = pose;
    const aria = describePose(conf < CONF_HOLD ? null : pose, this.t);
    if (aria !== this._lastAria && this.onAria) { this._lastAria = aria; this.onAria(aria); }
  }

  // Explicit drink signal (the app drives this from the measured `drink` event). With no arm,
  // this just toggles the cup icon + the "taking a sip" chip for the window.
  setDrinking(on) { this.target.drinking = !!on; if (this._lastPose) this._lastPose.drinking = !!on; }

  setGhost(on) { this.ghost = !!on; if (this._ghost) this._ghost.visible = this.ghost; }

  setView(azDeg, elDeg) { this.view.az = (azDeg || 0) * DEG; this.view.el = (elDeg || 0) * DEG; }
  resetView() { this.view.az = 0; this.view.el = 0; }
  nudgeView(dAzDeg, dElDeg) {
    this.view.az = clamp(this.view.az + (dAzDeg || 0) * DEG, -Math.PI, Math.PI);
    this.view.el = clamp(this.view.el + (dElDeg || 0) * DEG, -70 * DEG, 70 * DEG);
  }

  // Which parts exist in the current render (for tests + the 2D-fallback note). Face + neck only.
  parts() {
    if (this.mode3d) return ["head", "neck", "face", "shoulderHint"];
    return ["head2d"];
  }

  // The smoothed expression shown this frame (0..1 channels), for tests/captures.
  exprShown() { return { ...this.shown.expr }; }

  // Concrete face-geometry numbers actually applied this frame, so tests can prove the drawing
  // scales with the measured values (not just that the channel changed). 3D reads the mesh
  // scales/positions; 2D reports the computed draw values. Null until a frame has rendered.
  faceMetrics() {
    const e = this.shown.expr;
    if (this.mode3d && this._face) {
      const f = this._face;
      return {
        mode: "3d",
        smileArcBow: Number((f.mouth._smile.scale.y).toFixed(3)),   // grows with smile
        smileArcWide: Number((f.mouth._smile.scale.x).toFixed(3)),
        smileVisible: !!f.mouth._smile.visible,
        openMouthH: Number((f.mouth._open.scale.y).toFixed(3)),      // grows with mouth_open
        openMouthVisible: !!f.mouth._open.visible,
        lidL: Number((f.eyeL._lid.position.y).toFixed(3)),           // lower = more closed
        lidR: Number((f.eyeR._lid.position.y).toFixed(3)),
        pupilLVisible: !!f.eyeL._pupil.visible,
        pupilRVisible: !!f.eyeR._pupil.visible,
        browY: Number((f.browL.position.y).toFixed(3)),              // rises with brow_raise
      };
    }
    // 2D fallback: recompute the same draw quantities the 2D renderer uses.
    const smile = clamp(e.smile, 0, 1), open = clamp(e.mouth_open, 0, 1);
    return {
      mode: "2d",
      smileBow: Number((0.04 + smile * 0.34).toFixed(3)),
      openMouthH: Number((0.08 + open * 0.34).toFixed(3)),
      openMouthVisible: open > 0.06,
      lidCoverL: Number(((1 - clamp(e.eye_l, 0, 1))).toFixed(3)),    // 0 open → 1 closed
      lidCoverR: Number(((1 - clamp(e.eye_r, 0, 1))).toFixed(3)),
      browRaise: Number((clamp(e.brow_raise, 0, 1)).toFixed(3)),
    };
  }

  start() {
    if (this.running || this._disposed) return;
    this.running = true;
    this._last = performance.now();
    const loop = (now) => {
      if (!this.running || this._disposed) return;
      this._raf = requestAnimationFrame(loop);
      if (now - this._last < FRAME_MS) return; // 30fps cap
      this._dt = (now - this._last) / 1000;
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
    if (this._onVis) document.removeEventListener("visibilitychange", this._onVis);
    if (this._renderer) {
      // free the GL context promptly so a following buddy (report screen / new session) can
      // get one under a tight software-GL context budget.
      try { this._renderer.forceContextLoss?.(); } catch {}
      try { this._renderer.dispose(); } catch {}
    }
  }

  // ---- per-frame ------------------------------------------------------------
  _step() {
    const lowConf = this.target.conf < CONF_HOLD;
    // Compute the honest rig from the current (measured) target. On low conf this returns a
    // hold of the last rig (face settled to neutral) so nothing invented moves.
    const input = {
      yaw: this.target.yaw, pitch: this.target.pitch, roll: this.target.roll,
      depth: this.target.depth, conf: this.target.conf, expr: this.target.expr,
    };
    const rig = computeRig(input, this._rig);
    if (!rig.held) this._rig = rig; // remember the last good rig for future holds

    // Smooth (lerp) toward the rig unless reduced-motion (then snap). Hold still on low conf.
    const alpha = this.reduced ? 1 : 0.18;
    const L = (cur, tgt) => cur + (tgt - cur) * alpha;
    if (!lowConf) {
      this.shown.yaw = L(this.shown.yaw, rig.headRot.yaw);
      this.shown.pitch = L(this.shown.pitch, rig.headRot.pitch);
      this.shown.roll = L(this.shown.roll, rig.headRot.roll);
      this.shown.neckBend = L(this.shown.neckBend, rig.neckBend);
      this.shown.headOffset = L(this.shown.headOffset, rig.headOffset);
      // expression channels lerp toward the measured target
      const e = rig.expr || neutralExpr();
      for (const k of ["eye_l", "eye_r", "mouth_open", "smile", "brow_raise"]) {
        this.shown.expr[k] = L(this.shown.expr[k], e[k]);
      }
    } else {
      // when unsure, ease the face back to neutral (never freeze a mid-expression)
      const n = neutralExpr();
      for (const k of ["eye_l", "eye_r", "mouth_open", "smile", "brow_raise"]) {
        this.shown.expr[k] = L(this.shown.expr[k], n[k]);
      }
    }

    // Render defensively: under a software-GL headless environment the WebGL context can be
    // dropped transiently; a throw here would surface as an uncaught page error. Swallow it so
    // the buddy skips a frame instead of crashing (the 2D fallback has no such risk).
    try {
      if (this.mode3d) this._render3D(lowConf);
      else this._render2D(lowConf);
    } catch { /* transient GL hiccup — skip this frame */ }
  }

  _render3D(lowConf) {
    // Screen is a mirror of the user: flip yaw & roll so the buddy moves the way the user sees.
    const yaw = -this.shown.yaw * DEG;
    const roll = -this.shown.roll * DEG;
    const pitch = this.shown.pitch * DEG; // chin-down stays chin-down
    // head: measured angles. (rig values are already exaggerated.)
    this._head.rotation.set(pitch, yaw, roll);
    // neck absorbs some chin-down + tilts a little with roll (estimated).
    this._neck.rotation.set(this.shown.neckBend * DEG * 0.5, 0, roll * 0.4);
    // forward head: push head group slightly +z toward the camera (estimated neck extension)
    this._head.position.z = this.shown.headOffset * 0.5;

    // breathing idle: a tiny vertical bob unless reduced-motion
    if (!this.reduced) {
      const b = Math.sin((performance.now() - this._t0) / 1000 * 1.6) * 0.01;
      this._buddy.position.y = b;
    } else {
      this._buddy.position.y = 0;
    }

    // --- facial expression (measured; never emotion) -----------------------
    const f = this._face;
    if (f) {
      const e = this.shown.expr;
      // eyes: slide the upper skin lid down to "close". eye=1 open (lid up, out of the way),
      // eye=0 closed (lid down over the sclera). Each eye independent → winks read.
      const EYE_R = 0.18;
      const lidY = (open) => EYE_R - (1 - clamp(open, 0, 1)) * (EYE_R * 2.0); // up (open) → down (closed)
      f.eyeL._lid.position.y = lidY(e.eye_l);
      f.eyeR._lid.position.y = lidY(e.eye_r);
      // pupils dim/hide as the eye closes so a shut eye doesn't show a floating dot
      f.eyeL._pupil.visible = e.eye_l > 0.3;
      f.eyeR._pupil.visible = e.eye_r > 0.3;
      // brows: rise with brow_raise and arch gently (outer ends up → a friendly, attentive lift,
      // not an inward angry slant). Kept subtle so it never reads as a frown.
      const browY = f.browBaseY + e.brow_raise * 0.14;
      f.browL.position.y = browY;
      f.browR.position.y = browY;
      f.browL.rotation.z = -e.brow_raise * 0.1; // user's left brow: outer (screen-left) end up
      f.browR.rotation.z = e.brow_raise * 0.1;  // user's right brow: outer (screen-right) end up

      // mouth: blend a curved smile line with a round open mouth (NEVER a rectangle).
      const smile = clamp(e.smile, 0, 1);
      const open = clamp(e.mouth_open, 0, 1);
      // smile arc: a bowed line. Width + upward bow grow with smile; it eases out as the mouth
      // opens (an open mouth carries the shape instead). Rotated so the arc smiles (ends up).
      const arc = f.mouth._smile;
      const smileVisible = 1 - open * 0.8;           // fade as the mouth opens
      arc.visible = smileVisible > 0.05;
      // base: a short near-flat line at neutral; more curved + wider with smile
      const bow = 0.35 + smile * 1.0;                 // y-scale = how deep the curve bows
      const widen = 0.7 + smile * 0.5;                // x-scale = mouth width
      arc.scale.set(widen, bow * smileVisible, 1);
      arc.rotation.z = Math.PI;                       // flip the half-torus so it curves up (smile)
      arc.position.y = -0.02 - smile * 0.04;
      // open mouth: a dark rounded cavity that grows (round, not a box). Hidden when ~closed.
      const om = f.mouth._open;
      om.visible = open > 0.06;
      om.scale.set(0.8 + smile * 0.3, 0.35 + open * 1.5, 0.6); // taller as it opens, a touch wider with smile
      om.position.y = -0.02 - open * 0.02;
      // cup icon appears only during a measured drink event (no arm)
      f.cup.visible = !lowConf && !!this.target.drinking;
    }

    // orbit camera around the head for the user's x/y/z views
    const r = 6.4;
    const az = this.view.az, el = this.view.el;
    this._cam.position.set(
      r * Math.cos(el) * Math.sin(az),
      0.15 + r * Math.sin(el),
      r * Math.cos(el) * Math.cos(az)
    );
    this._cam.lookAt(0, 0.1, 0);

    // colour by deviation (unless unsure → neutral, no alarming shift)
    const dev = lowConf ? 0 : deviationScore(this._lastPose);
    const c = postureColor(dev);
    if (this._skinMat) this._skinMat.color.setRGB(c.r, c.g, c.b);

    this._renderer.render(this._scene, this._cam);
  }

  _render2D(lowConf) {
    const ctx = this._ctx; if (!ctx) return;
    const W = this.canvas.width, H = this.canvas.height;
    ctx.clearRect(0, 0, W, H);
    const cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.3;
    const dev = lowConf ? 0 : deviationScore(this._lastPose);
    const c = postureColor(dev);
    const rgb = `rgb(${Math.round(c.r * 255)},${Math.round(c.g * 255)},${Math.round(c.b * 255)})`;
    const e = this.shown.expr;
    ctx.save();
    ctx.translate(cx, cy);
    if (!lowConf) ctx.rotate((-this.shown.roll) * DEG); // tilt the face icon (already exaggerated)
    // face
    ctx.fillStyle = rgb;
    ctx.beginPath(); ctx.arc(0, 0, R, 0, Math.PI * 2); ctx.fill();
    const look = lowConf ? 0 : clamp(-this.shown.yaw / 30, -1, 1) * R * 0.2;
    const eyeY = -R * 0.12, eyeX = R * 0.36, eyeRX = R * 0.17, eyeRY = R * 0.2;
    // eyes: white sclera + dark pupil + a skin "lid" wedge that covers from the top as it closes.
    const drawEye = (sign) => {
      const open = clamp(sign < 0 ? e.eye_l : e.eye_r, 0, 1);
      const ex = sign * eyeX + look;
      // sclera (white)
      ctx.fillStyle = "#f2f6fb";
      ctx.beginPath(); ctx.ellipse(ex, eyeY, eyeRX, eyeRY, 0, 0, Math.PI * 2); ctx.fill();
      // pupil (dark) — hidden as the eye closes
      if (open > 0.3) {
        ctx.fillStyle = "#2b3a4a";
        ctx.beginPath(); ctx.ellipse(ex + look * 0.2, eyeY + (1 - open) * eyeRY * 0.4, eyeRX * 0.5, eyeRY * 0.55, 0, 0, Math.PI * 2); ctx.fill();
      }
      // upper lid: a skin-coloured block covering the top portion as the eye closes
      const cover = (1 - open) * (eyeRY * 2);
      if (cover > 0.5) {
        ctx.fillStyle = rgb;
        ctx.fillRect(ex - eyeRX - 1, eyeY - eyeRY - 1, (eyeRX + 1) * 2, cover + 1);
        // a thin eyelash line at the lid edge for a clearer closed look
        ctx.fillStyle = "#2b3a4a";
        ctx.fillRect(ex - eyeRX, eyeY - eyeRY + cover, eyeRX * 2, Math.max(1.5, R * 0.015));
      }
    };
    drawEye(-1);
    drawEye(1);
    // brows: rise with brow_raise and tilt (inner up)
    const browY = eyeY - R * 0.22 - e.brow_raise * R * 0.12;
    const browW = R * 0.3, browH = Math.max(2, R * 0.045), tilt = e.brow_raise * R * 0.08;
    ctx.fillStyle = "#2b3a4a";
    const drawBrow = (sign) => {
      const bx = sign * eyeX + look;
      ctx.save();
      ctx.translate(bx, browY);
      ctx.rotate(-sign * e.brow_raise * 0.12); // outer end up (friendly lift, not an inward slant)
      ctx.fillRect(-browW / 2, -browH / 2, browW, browH);
      ctx.restore();
    };
    drawBrow(-1);
    drawBrow(1);
    // mouth: a CURVED line (quadratic) for smile/neutral + a round open mouth — never a rectangle.
    const smile = clamp(e.smile, 0, 1), open = clamp(e.mouth_open, 0, 1);
    const mY = R * 0.4, mW = R * 0.46 * (0.8 + smile * 0.5);
    if (open > 0.06) {
      // open mouth: a dark rounded ellipse that grows taller as it opens
      ctx.fillStyle = "#1b2430";
      const oH = R * 0.08 + open * R * 0.34;
      ctx.beginPath(); ctx.ellipse(0, mY, mW * 0.55, oH / 2, 0, 0, Math.PI * 2); ctx.fill();
    }
    if (open < 0.95) {
      // smile/neutral line: a quadratic curve. Control point dips BELOW the ends for a smile
      // (ends up), near-flat at neutral. Fades as the mouth opens.
      ctx.strokeStyle = "#2b3a4a";
      ctx.lineWidth = Math.max(2.5, R * 0.05);
      ctx.lineCap = "round";
      ctx.globalAlpha = 1 - open;
      const bow = R * (0.04 + smile * 0.34); // how far the curve dips (smile depth)
      ctx.beginPath();
      ctx.moveTo(-mW / 2, mY - smile * R * 0.06);
      ctx.quadraticCurveTo(0, mY + bow, mW / 2, mY - smile * R * 0.06);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.restore();
    // cup chip near the mouth during a measured drink event
    if (!lowConf && this.target.drinking) {
      ctx.fillStyle = "rgba(207,216,230,0.95)";
      ctx.fillRect(cx + R * 0.5, cy + R * 0.2, R * 0.22, R * 0.3);
    }
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

// Resolve a single pose sample from a fixture time series at time t (seconds). Carries the
// `drinking` flag and `expr` through when either neighbouring sample has them (so a drink span /
// expression shows). Expression channels are interpolated per channel when both samples have them.
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
        conf: Math.min(a.conf, b.conf),
        drinking: !!(a.drinking || b.drinking),
        expr: lerpExpr(a.expr, b.expr, k),
      };
    }
  }
  return s[s.length - 1];
}

// Interpolate two expr objects channel-wise; if only one side has an expr, carry it; neither → null.
function lerpExpr(a, b, k) {
  if (!a && !b) return null;
  if (a && !b) return a;
  if (b && !a) return b;
  const out = {};
  for (const key of ["eye_l", "eye_r", "mouth_open", "smile", "brow_raise"]) {
    const av = a[key], bv = b[key];
    if (av == null && bv == null) continue;
    const x = av == null ? bv : av, y = bv == null ? av : bv;
    out[key] = x + (y - x) * k;
  }
  return out;
}
