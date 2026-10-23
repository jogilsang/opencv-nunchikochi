// buddy.js — "Posture buddy / 자세 인형": a sitting upper-body figure (W14, was a sphere+capsule in W10).
// OWNER: web tab.
//
// Shows a soft pastel-clay person from the chest up — head, neck, shoulders, chest/belly,
// upper arms, forearms, hands — sitting at a simple desk. Legs are NOT drawn (hidden under
// the desk). NO bones, NO skeleton, NO anatomy lines — child-friendly, gender/ethnicity-neutral.
//
// HONESTY: we MEASURE only the head angles (yaw/pitch/roll) + depth and the drink event. The
// neck, torso and arms are an ESTIMATE from those few numbers (see buddy-kinematics.js), and
// the UI says so. The head follows the measured angles (1.5x exaggerated, clamped); the body
// lean/neck/arm are derived. Signs follow docs/CONTRACTS.md (the user's own view); we mirror
// yaw/roll on screen so the buddy moves the way the user sees themselves.
//
// Rendering: vendored three.js (web/vendor/three.module.min.js, MIT, pinned r158). If the
// module or WebGL is unavailable we fall back to a 2D angle icon — console errors must be 0.
// Low-poly (≤ ~4k triangles). Drag/touch rotation is hand-rolled (no OrbitControls). 30fps
// cap; paused when tab hidden. prefers-reduced-motion: snap (no smoothing) and no breathing.

import { computeRig, neutralRig, KINEMATICS } from "./buddy-kinematics.js";

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
const ARM_RAISE_SECONDS = 1.5;                       // drink arm rise/fall duration

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
// Appends a short "torso is estimated" clause when the body is leaning, so a screen-reader
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
  if (pose.drinking && t) parts.push(t("buddyDrinking") || "drinking");
  if (parts.length === 0) return t ? t("buddyNeutral") : "neutral posture";
  let s = parts.join(", ");
  // If the body is doing something estimated (lean), name it as an estimate.
  if (leaning && t) s += " — " + (t("buddyTorsoEstimated") || "torso is estimated");
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
    this.target = { yaw: 0, pitch: 0, roll: 0, depth: 1, conf: 1, drinking: false };
    // smoothed rig values actually shown this frame
    this.shown = {
      yaw: 0, pitch: 0, roll: 0,
      torsoLean: 0, neckBend: 0, headOffset: 0, rightArmRaise: 0,
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
    const cam = new three.PerspectiveCamera(32, w / h, 0.1, 100);
    cam.position.set(0, 0.3, 8.2);
    cam.lookAt(0, -0.2, 0);

    // soft, shadow-free lighting
    scene.add(new three.AmbientLight(0xffffff, 0.88));
    const key = new three.DirectionalLight(0xffffff, 0.5);
    key.position.set(2, 3, 4);
    scene.add(key);

    const skinColor = 0x7cc79e;
    const clothColor = 0x6f86b8;   // plain solid top (no logo/pattern), neutral blue-grey
    const mkMat = (c) => new three.MeshStandardMaterial({ color: c, roughness: 0.9, metalness: 0.0 });

    // skin material is shared across skin parts so the deviation colour tints the whole figure
    this._skinMat = mkMat(skinColor);
    const clothMat = mkMat(clothColor);
    const faceMat = new three.MeshStandardMaterial({ color: 0x2b3a4a, roughness: 0.6 });

    // --- rig groups (low-poly, child-friendly proportions; head slightly large) ---------
    const buddy = new three.Group();     // whole figure
    const body = new three.Group();      // torso lean pivot (hips area, under the desk line)
    const neck = new three.Group();      // neck bend pivot (top of chest)
    const head = new three.Group();      // measured yaw/pitch/roll
    const rShoulder = new three.Group(); // right upper-arm pivot (user's right = screen left after mirror handled in scene)
    const lShoulder = new three.Group();

    // chest / belly: a tapered body (two stacked rounded shapes), cloth-coloured
    const chest = new three.Mesh(new three.CapsuleGeometry(0.78, 0.7, 4, 12), clothMat);
    chest.position.y = -0.55;
    const belly = new three.Mesh(new three.SphereGeometry(0.82, 16, 10), clothMat);
    belly.position.y = -1.25; belly.scale.set(1.0, 0.7, 0.9);
    body.add(chest, belly);

    // shoulders: a soft horizontal bar (stays level — we do NOT measure shoulder tilt)
    const shoulderBar = new three.Mesh(new three.CapsuleGeometry(0.34, 1.5, 3, 10), clothMat);
    shoulderBar.rotation.z = Math.PI / 2;
    shoulderBar.position.y = 0.05;
    body.add(shoulderBar);

    // neck (skin) rises from the chest; head sits on top
    const neckMesh = new three.Mesh(new three.CylinderGeometry(0.26, 0.3, 0.5, 12), this._skinMat);
    neckMesh.position.y = 0.3;
    neck.add(neckMesh);
    neck.position.y = 0.15;         // top of chest
    body.add(neck);

    // head: a slightly large sphere + simple face on +z
    const headMesh = new three.Mesh(new three.SphereGeometry(0.82, 22, 14), this._skinMat);
    head.add(headMesh);
    const eyeGeo = new three.SphereGeometry(0.1, 10, 8);
    const eyeL = new three.Mesh(eyeGeo, faceMat); eyeL.position.set(-0.27, 0.1, 0.74);
    const eyeR = new three.Mesh(eyeGeo, faceMat); eyeR.position.set(0.27, 0.1, 0.74);
    const mouth = new three.Mesh(new three.BoxGeometry(0.3, 0.06, 0.05), faceMat);
    mouth.position.set(0, -0.26, 0.77);
    head.add(eyeL, eyeR, mouth);
    head.position.y = 0.62;         // sit the head on top of the neck
    neck.add(head);

    // arms: upper arm + forearm + hand. Each arm hangs from its own group origin (the shoulder
    // joint), so rotating the shoulder group rotates about the shoulder — not the body centre.
    const makeArm = () => {
      const grp = new three.Group();               // pivot = shoulder joint
      const upper = new three.Mesh(new three.CapsuleGeometry(0.2, 0.7, 3, 10), this._skinMat);
      upper.position.y = -0.4;                      // upper arm hangs below the shoulder
      const fore = new three.Group();               // pivot = elbow
      const foreMesh = new three.Mesh(new three.CapsuleGeometry(0.17, 0.66, 3, 10), this._skinMat);
      foreMesh.position.y = -0.37;
      const hand = new three.Mesh(new three.SphereGeometry(0.2, 10, 8), this._skinMat);
      hand.position.y = -0.74; hand.scale.set(1, 0.8, 0.9);
      fore.add(foreMesh, hand);
      fore.position.y = -0.78;                      // elbow is at the bottom of the upper arm
      grp.add(upper, fore);
      grp._fore = fore;
      return grp;
    };
    const rArm = makeArm();   // user's right arm
    const lArm = makeArm();
    rShoulder.add(rArm); lShoulder.add(lArm);
    // shoulder joints sit at the top-sides of the chest
    rShoulder.position.set(0.72, 0.0, 0.08);
    lShoulder.position.set(-0.72, 0.0, 0.08);
    body.add(rShoulder, lShoulder);

    // a simple cup (cylinder) in the right hand, shown only while drinking
    const cup = new three.Mesh(new three.CylinderGeometry(0.14, 0.12, 0.34, 10), mkMat(0xcfd8e6));
    cup.visible = false;
    rArm._fore.add(cup);
    cup.position.set(0, -0.78, 0.12);
    this._cup = cup;
    this._rArm = rArm;
    this._lArm = lArm;

    buddy.add(body);

    // desk: a simple top + a small keyboard; a chair-back silhouette behind (optional, subtle)
    const deskMat = mkMat(0x394657);
    const desk = new three.Mesh(new three.BoxGeometry(4.6, 0.18, 1.8), deskMat);
    desk.position.set(0, -1.75, 0.5);
    const keyboard = new three.Mesh(new three.BoxGeometry(1.7, 0.08, 0.6), mkMat(0x2b3542));
    keyboard.position.set(0, -1.63, 0.95);
    const chairBack = new three.Mesh(new three.BoxGeometry(2.0, 1.7, 0.16), mkMat(0x2a333f));
    chairBack.position.set(0, -0.7, -0.75);
    chairBack.material.transparent = true; chairBack.material.opacity = 0.5;
    const deskGroup = new three.Group();
    deskGroup.add(chairBack, desk, keyboard);
    scene.add(deskGroup);
    scene.add(buddy);

    // ghost: a translucent SKY-BLUE copy of the figure at the neutral/good posture, with a
    // thin back-side outline so its shape reads from any angle. Different colour family from
    // the buddy (green→amber) so the two never merge; a text legend carries the meaning too.
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
    this._body = body;
    this._neck = neck;
    this._head = head;
    this._rShoulder = rShoulder;
    this._lShoulder = lShoulder;
    this._ghost = ghost;

    // report the triangle budget once (helps keep us under ~4k)
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
    };
    this._lastPose = pose;
    const aria = describePose(conf < CONF_HOLD ? null : pose, this.t);
    if (aria !== this._lastAria && this.onAria) { this._lastAria = aria; this.onAria(aria); }
  }

  // Explicit drink signal (the app drives this from the measured `drink` event).
  setDrinking(on) { this.target.drinking = !!on; if (this._lastPose) this._lastPose.drinking = !!on; }

  // Test/screenshot helper: pin the right-arm raise at a value (0=rest, 1=apex/hand-at-mouth)
  // so a capture can grab the apex frame deterministically. Pass null to release the pin.
  forceArmRaise(v) {
    if (v == null) { this._armLock = null; return; }
    this._armLock = clamp(Number(v) || 0, 0, 1);
    this.shown.rightArmRaise = this._armLock;
  }

  setGhost(on) { this.ghost = !!on; if (this._ghost) this._ghost.visible = this.ghost; }

  setView(azDeg, elDeg) { this.view.az = (azDeg || 0) * DEG; this.view.el = (elDeg || 0) * DEG; }
  resetView() { this.view.az = 0; this.view.el = 0; }
  nudgeView(dAzDeg, dElDeg) {
    this.view.az = clamp(this.view.az + (dAzDeg || 0) * DEG, -Math.PI, Math.PI);
    this.view.el = clamp(this.view.el + (dElDeg || 0) * DEG, -70 * DEG, 70 * DEG);
  }

  // Which body parts exist in the current render (for tests + the 2D-fallback note).
  parts() {
    if (this.mode3d) return ["head", "neck", "shoulders", "chest", "rightArm", "leftArm", "hand", "desk"];
    return ["head2d"];
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
    // hold of the last rig so nothing invented moves.
    const input = {
      yaw: this.target.yaw, pitch: this.target.pitch, roll: this.target.roll,
      depth: this.target.depth, conf: this.target.conf, drinking: this.target.drinking,
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
      this.shown.torsoLean = L(this.shown.torsoLean, rig.torsoLean);
      this.shown.neckBend = L(this.shown.neckBend, rig.neckBend);
      this.shown.headOffset = L(this.shown.headOffset, rig.headOffset);
    }
    // Arm raise moves at a fixed rate so it takes ~ARM_RAISE_SECONDS up or down (drink gesture),
    // independent of confidence (it's a measured event signal). A test pin (_armLock) freezes it.
    if (this._armLock != null) {
      this.shown.rightArmRaise = this._armLock;
    } else {
      const armTarget = this._rig.rightArmRaise || (rig.held ? this.shown.rightArmRaise : 0);
      const armStep = (this._dt || FRAME_MS / 1000) / ARM_RAISE_SECONDS;
      if (this.shown.rightArmRaise < armTarget) this.shown.rightArmRaise = Math.min(armTarget, this.shown.rightArmRaise + armStep);
      else this.shown.rightArmRaise = Math.max(armTarget, this.shown.rightArmRaise - armStep);
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
    // head: measured angles. neck absorbs some chin-down. (rig values are already exaggerated.)
    this._head.rotation.set(pitch, yaw, roll);
    // roll tilts the head + upper neck only; shoulders stay level (we don't measure shoulder tilt)
    this._neck.rotation.set(this.shown.neckBend * DEG * 0.5, 0, roll * 0.4);
    // forward head: push head group slightly +z toward the camera
    this._head.position.z = this.shown.headOffset * 0.5;
    // torso lean forward (estimated) — bow the whole body from the hips
    this._body.rotation.x = this.shown.torsoLean * DEG;

    // breathing idle: a tiny vertical bob unless reduced-motion
    if (!this.reduced) {
      const b = Math.sin((performance.now() - this._t0) / 1000 * 1.6) * 0.012;
      this._body.position.y = b;
    } else {
      this._body.position.y = 0;
    }

    // Right arm. Rest = forearm resting forward on the desk (elbow by the side, hand near the
    // keyboard); raise (drink) = upper arm lifts and the elbow folds so the hand comes to mouth
    // height. Angles solved so the hand lands on the desk at rest and near the mouth at apex.
    // (Rotations are about the shoulder/elbow joints; negative shoulder.x swings the arm +z/forward.)
    const raise = this.shown.rightArmRaise;
    const restShoX = -0.2, apexShoX = -1.3;   // shoulder swing: forward-down(desk) → up/forward(face)
    const restShoZ = -0.2, apexShoZ = -0.8;   // bring the hand in toward the mouth centreline
    const restForeX = -1.1, apexForeX = -1.5; // elbow: forearm forward on desk → folded to the face
    this._rShoulder.rotation.x = restShoX + (apexShoX - restShoX) * raise;
    this._rShoulder.rotation.z = restShoZ + (apexShoZ - restShoZ) * raise;
    if (this._rArm._fore) this._rArm._fore.rotation.x = restForeX + (apexForeX - restForeX) * raise;
    // left arm: a fixed relaxed rest on the desk (mirror of the right rest → negate z)
    this._lShoulder.rotation.x = restShoX;
    this._lShoulder.rotation.z = -restShoZ;
    if (this._lArm._fore) this._lArm._fore.rotation.x = restForeX;
    // cup appears only when the arm is meaningfully raised
    if (this._cup) this._cup.visible = raise > 0.08;

    // orbit camera around the buddy for the user's x/y/z views
    const r = 8.2;
    const az = this.view.az, el = this.view.el;
    this._cam.position.set(
      r * Math.cos(el) * Math.sin(az),
      0.3 + r * Math.sin(el),
      r * Math.cos(el) * Math.cos(az)
    );
    this._cam.lookAt(0, -0.2, 0);

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
    const cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.28;
    const dev = lowConf ? 0 : deviationScore(this._lastPose);
    const c = postureColor(dev);
    const rgb = `rgb(${Math.round(c.r * 255)},${Math.round(c.g * 255)},${Math.round(c.b * 255)})`;
    ctx.save();
    ctx.translate(cx, cy);
    if (!lowConf) ctx.rotate((-this.shown.roll) * DEG); // tilt the face icon (already exaggerated)
    ctx.fillStyle = rgb;
    ctx.beginPath(); ctx.arc(0, 0, R, 0, Math.PI * 2); ctx.fill();
    const look = lowConf ? 0 : clamp(-this.shown.yaw / 30, -1, 1) * R * 0.2;
    ctx.fillStyle = "#2b3a4a";
    ctx.beginPath(); ctx.arc(-R * 0.35 + look, -R * 0.1, R * 0.12, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.arc(R * 0.35 + look, -R * 0.1, R * 0.12, 0, Math.PI * 2); ctx.fill();
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
// `drinking` flag through when either neighbouring sample has it set (so a drink span shows).
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
      };
    }
  }
  return s[s.length - 1];
}
