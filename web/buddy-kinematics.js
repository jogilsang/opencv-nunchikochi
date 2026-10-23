// buddy-kinematics.js — pure posture→rig mapping for the sitting upper-body buddy (W14).
// OWNER: web tab. NO DOM, NO three.js: just numbers in → rig angles out, so it is unit-testable.
//
// HONESTY (the whole point): we only MEASURE head angles (yaw/pitch/roll) + depth and the
// `drink` event. We do NOT measure shoulders, elbows, torso, or legs. So everything this
// module returns for the neck/torso/arms is an ESTIMATE derived from those few measured
// numbers — the output carries `estimated: true` and the UI says so on screen. No anatomy,
// no bones, no medical claims. Signs follow docs/CONTRACTS.md (the user's own view):
//   yaw>0 turns right, pitch>0 chin down, roll>0 toward the right shoulder, depth>1 = closer
//   (forward head / slouch).
//
// Output (all angles in DEGREES unless noted):
//   headRot:      { yaw, pitch, roll }  measured head angles, exaggerated + clamped
//   headOffset:   forward head offset 0..1 (scene maps to a small +z push), estimated
//   neckBend:     neck bend that absorbs chin-down, degrees, estimated
//   torsoLean:    forward torso lean 0..TORSO_MAX deg, estimated
//   shoulderShrug:0..1 (kept 0 — we don't measure shoulders; reserved), estimated
//   rightArmRaise:0..1 toward the mouth (driven by the measured `drink` event)
//   leftArmRaise: 0..1 (rests on the desk; reserved)
//   estimated:    true (always — the body is a model)

// Tunable constants, gathered so the mapping is auditable in one place. These are chosen so a
// synthetic input looks reasonable on screen; we do NOT claim they are anatomically accurate.
export const KINEMATICS = {
  EXAGGERATION: 1.5,     // amplify MEASURED head motion so it is easy to read (shown on screen)
  HEAD_YAW_MAX: 60,      // clamp exaggerated head angles (deg) so the rig never breaks
  HEAD_PITCH_MAX: 45,
  HEAD_ROLL_MAX: 45,
  CONF_HOLD: 0.5,        // below this (or no pose) → hold last stable values
  // torsoLean = clamp(K_DEPTH*(depth-1) + K_PITCH*max(pitch,0), 0, TORSO_MAX)
  K_DEPTH: 28,           // depth 1.3 → ~8.4deg from depth alone
  K_PITCH: 0.25,         // chin-down adds a little forward lean
  TORSO_MAX: 18,         // hard cap on the estimated forward lean (deg)
  // neck absorbs part of the chin-down so the head doesn't clip the chest
  K_NECK_PITCH: 0.35,
  NECK_MAX: 16,
  // forward-head offset (0..1) from depth; scene turns this into a small +z push
  K_HEAD_OFFSET: 2.2,    // depth 1.3 → ~0.66
  HEAD_OFFSET_MAX: 1.0,
};

function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }
// Treat NaN / Infinity / non-numbers as 0 so bad input never produces NaN rig values.
function num(x, dflt = 0) {
  const n = typeof x === "number" ? x : Number(x);
  return Number.isFinite(n) ? n : dflt;
}

// A safe neutral rig (used as the "hold" value and the default).
export function neutralRig() {
  return {
    headRot: { yaw: 0, pitch: 0, roll: 0 },
    headOffset: 0,
    neckBend: 0,
    torsoLean: 0,
    shoulderShrug: 0,
    rightArmRaise: 0,
    leftArmRaise: 0,
    estimated: true,
  };
}

// Compute the rig from a pose-ish input. Pure + total: any missing/garbage field → neutral-ish.
// `last` (optional) is the previous rig, returned unchanged when confidence is too low so the
// buddy holds still instead of twitching (the UI shows "tracking unsure" in that case).
//
// input: { yaw, pitch, roll, depth, conf, drinking }
//   - yaw/pitch/roll: measured head angles (deg)
//   - depth: measured (1 = calibration distance, >1 closer)
//   - conf: 0..1 measurement confidence
//   - drinking: boolean measured `drink` event → right arm raises toward the mouth
export function computeRig(input, last = null) {
  const K = KINEMATICS;
  const inp = input && typeof input === "object" ? input : {};
  const conf = inp.conf == null ? 1 : num(inp.conf, 0);

  // Low confidence or no usable pose → hold the last stable rig (or neutral). This is the
  // honest "we're unsure, don't invent motion" behaviour.
  const hasPose = ["yaw", "pitch", "roll", "depth"].some((k) => inp[k] != null);
  if (!hasPose || conf < K.CONF_HOLD) {
    const held = last && typeof last === "object" ? { ...last } : neutralRig();
    held.estimated = true;
    held.held = true;        // marker so callers/tests can see this was a hold
    return held;
  }

  const E = K.EXAGGERATION;
  const yaw = num(inp.yaw);
  const pitch = num(inp.pitch);
  const roll = num(inp.roll);
  const depth = inp.depth == null ? 1 : num(inp.depth, 1);
  const drinking = !!inp.drinking;

  // MEASURED head angles, exaggerated for readability then clamped so the rig can't break.
  const headRot = {
    yaw: clamp(yaw * E, -K.HEAD_YAW_MAX, K.HEAD_YAW_MAX),
    pitch: clamp(pitch * E, -K.HEAD_PITCH_MAX, K.HEAD_PITCH_MAX),
    roll: clamp(roll * E, -K.HEAD_ROLL_MAX, K.HEAD_ROLL_MAX),
  };

  // ESTIMATED torso lean: closer (depth>1) and/or chin-down → lean forward, capped.
  const depthOver = Math.max(0, depth - 1);
  const torsoLean = clamp(K.K_DEPTH * depthOver + K.K_PITCH * Math.max(0, pitch), 0, K.TORSO_MAX);

  // ESTIMATED neck bend: absorbs part of the chin-down so the head doesn't clip the chest.
  const neckBend = clamp(K.K_NECK_PITCH * Math.max(0, pitch), 0, K.NECK_MAX);

  // ESTIMATED forward-head offset 0..1 from depth only (roll/yaw don't push the head forward).
  const headOffset = clamp(K.K_HEAD_OFFSET * depthOver, 0, K.HEAD_OFFSET_MAX);

  // Arms: default rest on the desk. The MEASURED drink event raises the right arm fully; the
  // scene animates the actual rise/fall over ~1.5s, so here it's just the target (0 or 1).
  const rightArmRaise = drinking ? 1 : 0;

  return {
    headRot,
    headOffset,
    neckBend,
    torsoLean,
    // shoulders are NOT measured → never shrug from data; reserved at 0.
    shoulderShrug: 0,
    rightArmRaise,
    leftArmRaise: 0,
    estimated: true,
    held: false,
  };
}
