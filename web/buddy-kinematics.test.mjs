// buddy-kinematics.test.mjs — unit tests for the pure posture→rig mapping (W14).
// OWNER: web tab. Run: node --test web/buddy-kinematics.test.mjs
// No DOM, no browser, no deps — exercises computeRig()/neutralRig() directly.

import { test } from "node:test";
import assert from "node:assert/strict";
import { computeRig, neutralRig, KINEMATICS } from "./buddy-kinematics.js";

// ---- normal path -----------------------------------------------------------

test("neutral input returns the base sitting pose (no lean, arms down, marked estimated)", () => {
  const r = computeRig({ yaw: 0, pitch: 0, roll: 0, depth: 1, conf: 0.98 });
  assert.equal(r.headRot.yaw, 0);
  assert.equal(r.headRot.pitch, 0);
  assert.equal(r.headRot.roll, 0);
  assert.equal(r.torsoLean, 0);
  assert.equal(r.neckBend, 0);
  assert.equal(r.headOffset, 0);
  assert.equal(r.rightArmRaise, 0);
  assert.equal(r.estimated, true, "body is always a model → estimated:true");
  assert.equal(r.held, false, "good confidence is not a hold");
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

test("deeper depth increases the ESTIMATED torso lean monotonically, then clamps at the cap", () => {
  const leanAt = (depth) => computeRig({ yaw: 0, pitch: 0, roll: 0, depth, conf: 0.95 }).torsoLean;
  const a = leanAt(1.0), b = leanAt(1.1), c = leanAt(1.3), d = leanAt(1.6);
  assert.equal(a, 0, "at calibration distance there is no lean");
  assert.ok(b > a && c > b, `lean should grow with depth: ${a} < ${b} < ${c}`);
  assert.ok(c <= KINEMATICS.TORSO_MAX && d <= KINEMATICS.TORSO_MAX, "lean never exceeds the cap");
  // a very large depth saturates exactly at the cap (no runaway)
  assert.equal(leanAt(5), KINEMATICS.TORSO_MAX);
  // headOffset is also bounded to 0..1
  const off = computeRig({ yaw: 0, pitch: 0, roll: 0, depth: 5, conf: 0.95 }).headOffset;
  assert.ok(off > 0 && off <= KINEMATICS.HEAD_OFFSET_MAX);
});

// ---- edge cases ------------------------------------------------------------

test("low confidence holds the last stable rig (no invented motion) and flags held", () => {
  const stable = computeRig({ yaw: 12, pitch: 4, roll: 3, depth: 1.2, conf: 0.95 });
  const dipped = computeRig({ yaw: 40, pitch: 30, roll: 20, depth: 1.9, conf: 0.2 }, stable);
  assert.deepEqual(dipped.headRot, stable.headRot, "head must not move on low confidence");
  assert.equal(dipped.torsoLean, stable.torsoLean, "torso must not move on low confidence");
  assert.equal(dipped.held, true, "low-confidence frame is a hold");
  assert.equal(dipped.estimated, true);
  // with no prior rig it holds a safe neutral instead of crashing
  const held0 = computeRig({ yaw: 10, pitch: 10, roll: 0, depth: 1.3, conf: 0.1 });
  assert.deepEqual(held0.headRot, neutralRig().headRot);
  assert.equal(held0.held, true);
});

test("the measured drink event raises the right arm; otherwise it rests", () => {
  const resting = computeRig({ yaw: 0, pitch: 0, roll: 0, depth: 1, conf: 0.95 });
  const drinking = computeRig({ yaw: 0, pitch: 0, roll: 0, depth: 1, conf: 0.95, drinking: true });
  assert.equal(resting.rightArmRaise, 0);
  assert.equal(drinking.rightArmRaise, 1, "drink event drives the right arm toward the mouth");
  assert.notEqual(drinking.rightArmRaise, resting.rightArmRaise);
  // the left arm is never driven by data (not measured)
  assert.equal(drinking.leftArmRaise, 0);
  // shoulders are never shrugged from data (not measured)
  assert.equal(drinking.shoulderShrug, 0);
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
    const vals = [r.headRot.yaw, r.headRot.pitch, r.headRot.roll, r.headOffset, r.neckBend, r.torsoLean, r.rightArmRaise];
    for (const v of vals) assert.ok(Number.isFinite(v), `non-finite rig value from input ${JSON.stringify(bad)}: ${v}`);
    assert.equal(r.estimated, true);
  }
  // an input with no pose fields at all is treated as "no pose" → held neutral
  const noPose = computeRig({ conf: 0.99 });
  assert.equal(noPose.held, true);
  assert.deepEqual(noPose.headRot, neutralRig().headRot);
});
