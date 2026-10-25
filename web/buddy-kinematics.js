// buddy-kinematics.js — pure posture→rig mapping for the face+neck posture buddy (W20).
// OWNER: web tab. NO DOM, NO three.js: just numbers in → rig angles out, so it is unit-testable.
//
// W20 CHANGE: the buddy is now only a FACE + NECK (+ a faint shoulder-line hint). The torso,
// arms, hands, desk and the water-drinking arm lift are GONE. What we draw:
//   - head: the MEASURED head angles (yaw/pitch/roll), exaggerated + clamped.
//   - neck: a small bend from the MEASURED head pitch/offset so the head tilts and juts forward
//     the way the user's head does — this is still an ESTIMATE from the head numbers (the UI
//     says so), but it's just the neck, not a whole body.
//   - expr: facial expression channels (eyes, mouth, smile, brows) passed through from the
//     MEASURED face (overlay.expr). These are measured face movement, NOT an emotion guess.
//
// HONESTY: head + facial movement are MEASURED (overlay.pose + overlay.expr). The neck bend is
// an ESTIMATE from the measured head angles. We do NOT draw a body. Signs follow
// docs/CONTRACTS.md (the user's own view):
//   yaw>0 turns right, pitch>0 chin down, roll>0 toward the right shoulder, depth>1 = closer.
//
// Output (angles in DEGREES unless noted):
//   headRot:   { yaw, pitch, roll }  measured head angles, exaggerated + clamped
//   headOffset:forward head offset 0..1 (scene maps to a small +z push), estimated (neck only)
//   neckBend:  neck bend that absorbs chin-down, degrees, estimated
//   expr:      { eye_l, eye_r, mouth_open, smile, brow_raise } each 0..1, measured (null-safe)
//   estimated: true for the neck (the face + head are measured)

// Tunable constants, gathered so the mapping is auditable in one place. Chosen so a synthetic
// input looks reasonable on screen; we do NOT claim they are anatomically accurate.
export const KINEMATICS = {
  EXAGGERATION: 1.5,     // amplify MEASURED head motion so it is easy to read (shown on screen)
  HEAD_YAW_MAX: 60,      // clamp exaggerated head angles (deg) so the rig never breaks
  HEAD_PITCH_MAX: 45,
  HEAD_ROLL_MAX: 45,
  CONF_HOLD: 0.5,        // below this (or no pose) → hold last stable values
  // neck absorbs part of the chin-down so the head doesn't clip the shoulders
  K_NECK_PITCH: 0.35,
  NECK_MAX: 16,
  // forward-head offset (0..1) from depth; scene turns this into a small +z push of the head
  K_HEAD_OFFSET: 2.2,    // depth 1.3 → ~0.66
  HEAD_OFFSET_MAX: 1.0,
  EXPR_EXAGGERATION: 1.25, // gently amplify facial movement for readability (shown on screen)
};

function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }
// Treat NaN / Infinity / non-numbers as 0 so bad input never produces NaN rig values.
function num(x, dflt = 0) {
  const n = typeof x === "number" ? x : Number(x);
  return Number.isFinite(n) ? n : dflt;
}

// Neutral facial expression: eyes open, mouth closed, no smile, brows relaxed.
export function neutralExpr() {
  return { eye_l: 1, eye_r: 1, mouth_open: 0, smile: 0, brow_raise: 0 };
}

// Normalize an expr-ish input into {eye_l, eye_r, mouth_open, smile, brow_raise}, all 0..1.
// Missing / null / garbage channels fall back to the neutral value for THAT channel (so a
// partial expr still renders a sensible face). `exaggerate` lifts movement a touch for the
// expressive channels (mouth/smile/brow) while eyes stay a straight 0..1 openness.
export function normalizeExpr(expr, { exaggerate = false } = {}) {
  const base = neutralExpr();
  if (!expr || typeof expr !== "object") return base;
  const ch = (key, dflt) => {
    const v = expr[key];
    if (v == null) return dflt;              // null/undefined → neutral for this channel
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) ? clamp(n, 0, 1) : dflt;
  };
  const E = exaggerate ? KINEMATICS.EXPR_EXAGGERATION : 1;
  const amp = (v) => clamp(v * E, 0, 1); // amplify toward the extreme, still clamped 0..1
  return {
    eye_l: ch("eye_l", base.eye_l),        // openness 1=open, 0=closed (not amplified)
    eye_r: ch("eye_r", base.eye_r),
    mouth_open: amp(ch("mouth_open", base.mouth_open)),
    smile: amp(ch("smile", base.smile)),
    brow_raise: amp(ch("brow_raise", base.brow_raise)),
  };
}

// A safe neutral rig (used as the "hold" value and the default).
export function neutralRig() {
  return {
    headRot: { yaw: 0, pitch: 0, roll: 0 },
    headOffset: 0,
    neckBend: 0,
    expr: neutralExpr(),
    estimated: true,
  };
}

// Compute the rig from a pose-ish input. Pure + total: any missing/garbage field → neutral-ish.
// `last` (optional) is the previous rig, returned unchanged when confidence is too low so the
// buddy holds still instead of twitching (the UI shows "tracking unsure" in that case).
//
// input: { yaw, pitch, roll, depth, conf, expr }
//   - yaw/pitch/roll: measured head angles (deg)
//   - depth: measured (1 = calibration distance, >1 closer)
//   - conf: 0..1 measurement confidence
//   - expr: measured facial channels {eye_l, eye_r, mouth_open, smile, brow_raise} (null-safe)
export function computeRig(input, last = null) {
  const K = KINEMATICS;
  const inp = input && typeof input === "object" ? input : {};
  const conf = inp.conf == null ? 1 : num(inp.conf, 0);

  // Low confidence or no usable pose → hold the last stable rig (or neutral). This is the
  // honest "we're unsure, don't invent motion" behaviour — the face freezes to neutral-ish too.
  const hasPose = ["yaw", "pitch", "roll", "depth"].some((k) => inp[k] != null);
  if (!hasPose || conf < K.CONF_HOLD) {
    const held = last && typeof last === "object" ? { ...last } : neutralRig();
    held.estimated = true;
    held.held = true;        // marker so callers/tests can see this was a hold
    // when unsure we settle the face to neutral so we never show an invented expression
    held.expr = neutralExpr();
    return held;
  }

  const E = K.EXAGGERATION;
  const yaw = num(inp.yaw);
  const pitch = num(inp.pitch);
  const roll = num(inp.roll);
  const depth = inp.depth == null ? 1 : num(inp.depth, 1);

  // MEASURED head angles, exaggerated for readability then clamped so the rig can't break.
  const headRot = {
    yaw: clamp(yaw * E, -K.HEAD_YAW_MAX, K.HEAD_YAW_MAX),
    pitch: clamp(pitch * E, -K.HEAD_PITCH_MAX, K.HEAD_PITCH_MAX),
    roll: clamp(roll * E, -K.HEAD_ROLL_MAX, K.HEAD_ROLL_MAX),
  };

  // ESTIMATED neck bend: absorbs part of the chin-down so the head tilts forward naturally.
  const neckBend = clamp(K.K_NECK_PITCH * Math.max(0, pitch), 0, K.NECK_MAX);

  // ESTIMATED forward-head offset 0..1 from depth only (roll/yaw don't push the head forward).
  const depthOver = Math.max(0, depth - 1);
  const headOffset = clamp(K.K_HEAD_OFFSET * depthOver, 0, K.HEAD_OFFSET_MAX);

  // MEASURED facial expression, null-safe + gently exaggerated for readability.
  const expr = normalizeExpr(inp.expr, { exaggerate: true });

  return {
    headRot,
    headOffset,
    neckBend,
    expr,
    estimated: true, // the neck is an estimate; head + face are measured
    held: false,
  };
}
