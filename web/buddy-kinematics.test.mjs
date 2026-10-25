// buddy-kinematics.test.mjs — unit tests for the pure posture→rig mapping (W20: face + neck).
// OWNER: web tab. Run: node --test web/buddy-kinematics.test.mjs
// No DOM, no browser, no deps — exercises computeRig()/neutralRig()/normalizeExpr() directly.

import { test } from "node:test";
import assert from "node:assert/strict";
import { computeRig, neutralRig, neutralExpr, normalizeExpr, KINEMATICS } from "./buddy-kinematics.js";

// ---- normal path -----------------------------------------------------------

test("neutral input returns the base rig (no neck bend, neutral face, marked estimated)", () => {
  const r = computeRig({ yaw: 0, pitch: 0, roll: 0, depth: 1, conf: 0.98 });
  assert.equal(r.headRot.yaw, 0);
  assert.equal(r.headRot.pitch, 0);
  assert.equal(r.headRot.roll, 0);
  assert.equal(r.neckBend, 0);
  assert.equal(r.headOffset, 0);
  assert.deepEqual(r.expr, neutralExpr(), "no expr given → neutral face (eyes open, mouth closed)");
  assert.equal(r.estimated, true, "the neck is a model → estimated:true");
  assert.equal(r.held, false, "good confidence is not a hold");
  // the body is gone: no torso/arm channels on the rig
  assert.equal(r.torsoLean, undefined);
  assert.equal(r.rightArmRaise, undefined);
});

test("measured head angles are exaggerated 1.5x and clamped to the rig limits", () => {
  const r = computeRig({ yaw: 10, pitch: 8, roll: -6, depth: 1, conf: 0.95 });
  assert.equal(r.headRot.yaw, 10 * KINEMATICS.EXAGGERATION);   // 15
  assert.equal(r.headRot.pitch, 8 * KINEMATICS.EXAGGERATION);  // 12
  assert.equal(r.headRot.roll, -6 * KINEMATICS.EXAGGERATION);  // -9
  // extreme input clamps instead of exploding
  const big = computeRig({ yaw: 200, pitch: 200, roll: -200, depth: 1, conf: 0.95 });
  assert.equal(big.headRot.yaw, KINEMATICS.HEAD_YAW_MAX);
  assert.equal(big.headRot.pitch, KINEMATICS.HEAD_PITCH_MAX);
  assert.equal(big.headRot.roll, -KINEMATICS.HEAD_ROLL_MAX);
});

test("deeper depth increases the ESTIMATED neck forward-offset + bend, then clamps at the caps", () => {
  const offAt = (depth) => computeRig({ yaw: 0, pitch: 0, roll: 0, depth, conf: 0.95 }).headOffset;
  const a = offAt(1.0), b = offAt(1.1), c = offAt(1.3);
  assert.equal(a, 0, "at calibration distance the head is not pushed forward");
  assert.ok(b > a && c > b, `forward offset should grow with depth: ${a} < ${b} < ${c}`);
  assert.ok(c <= KINEMATICS.HEAD_OFFSET_MAX, "offset never exceeds the cap");
  assert.equal(offAt(5), KINEMATICS.HEAD_OFFSET_MAX, "a very large depth saturates at the cap");
  // chin-down bends the neck, bounded by NECK_MAX
  const bend = (pitch) => computeRig({ yaw: 0, pitch, roll: 0, depth: 1, conf: 0.95 }).neckBend;
  assert.equal(bend(0), 0);
  assert.ok(bend(10) > 0 && bend(10) <= KINEMATICS.NECK_MAX);
  assert.equal(bend(200), KINEMATICS.NECK_MAX, "huge chin-down clamps at the neck cap");
});

test("measured facial expression passes through (null-safe) and is clamped 0..1", () => {
  const r = computeRig({
    yaw: 0, pitch: 0, roll: 0, depth: 1, conf: 0.95,
    expr: { eye_l: 0.1, eye_r: 1, mouth_open: 0.6, smile: 0.4, brow_raise: 0.3 },
  });
  assert.ok(r.expr.eye_l >= 0 && r.expr.eye_l <= 1);
  assert.equal(r.expr.eye_l, 0.1, "eye openness passes through un-amplified");
  assert.ok(r.expr.mouth_open > 0.6, "mouth_open is gently exaggerated for readability");
  assert.ok(r.expr.mouth_open <= 1 && r.expr.smile <= 1 && r.expr.brow_raise <= 1, "all clamped to 1");
  // a partial / null expr falls back to neutral PER CHANNEL, never NaN
  const partial = computeRig({ yaw: 0, pitch: 0, roll: 0, depth: 1, conf: 0.95, expr: { mouth_open: 0.5, smile: null, eye_l: null } });
  assert.equal(partial.expr.eye_l, 1, "null eye → open (neutral)");
  assert.equal(partial.expr.smile, 0, "null smile → neutral");
  for (const v of Object.values(partial.expr)) assert.ok(Number.isFinite(v));
});

// ---- edge cases ------------------------------------------------------------

test("low confidence holds the last stable rig (no invented motion) and settles the face to neutral", () => {
  const stable = computeRig({ yaw: 12, pitch: 4, roll: 3, depth: 1.2, conf: 0.95, expr: { mouth_open: 0.8, smile: 0.5 } });
  const dipped = computeRig({ yaw: 40, pitch: 30, roll: 20, depth: 1.9, conf: 0.2, expr: { mouth_open: 1 } }, stable);
  assert.deepEqual(dipped.headRot, stable.headRot, "head must not move on low confidence");
  assert.equal(dipped.neckBend, stable.neckBend, "neck must not move on low confidence");
  assert.deepEqual(dipped.expr, neutralExpr(), "face settles to neutral when unsure (no invented expression)");
  assert.equal(dipped.held, true, "low-confidence frame is a hold");
  assert.equal(dipped.estimated, true);
  // with no prior rig it holds a safe neutral instead of crashing
  const held0 = computeRig({ yaw: 10, pitch: 10, roll: 0, depth: 1.3, conf: 0.1 });
  assert.deepEqual(held0.headRot, neutralRig().headRot);
  assert.equal(held0.held, true);
});

test("normalizeExpr: garbage/empty input yields a full neutral face, never NaN", () => {
  for (const bad of [undefined, null, {}, "x", 5, { eye_l: "nope", mouth_open: NaN, smile: Infinity }]) {
    const e = normalizeExpr(bad);
    for (const k of ["eye_l", "eye_r", "mouth_open", "smile", "brow_raise"]) {
      assert.ok(Number.isFinite(e[k]), `non-finite expr channel ${k} from ${JSON.stringify(bad)}`);
      assert.ok(e[k] >= 0 && e[k] <= 1, `expr channel ${k} out of 0..1`);
    }
  }
  assert.deepEqual(normalizeExpr(null), neutralExpr());
});

// ---- error / malformed input ----------------------------------------------

test("NaN / undefined / missing fields never yield NaN rig values", () => {
  for (const bad of [
    undefined,
    null,
    {},
    { yaw: NaN, pitch: undefined, roll: "x", depth: null, conf: 0.9 },
    { yaw: Infinity, pitch: -Infinity, roll: 0, depth: NaN, conf: 0.95 },
  ]) {
    const r = computeRig(bad);
    const vals = [r.headRot.yaw, r.headRot.pitch, r.headRot.roll, r.headOffset, r.neckBend,
      r.expr.eye_l, r.expr.eye_r, r.expr.mouth_open, r.expr.smile, r.expr.brow_raise];
    for (const v of vals) assert.ok(Number.isFinite(v), `non-finite rig value from input ${JSON.stringify(bad)}: ${v}`);
    assert.equal(r.estimated, true);
  }
  // an input with no pose fields at all is treated as "no pose" → held neutral
  const noPose = computeRig({ conf: 0.99 });
  assert.equal(noPose.held, true);
  assert.deepEqual(noPose.headRot, neutralRig().headRot);
});
