// mock.js — fake server with the SAME surface as Api, for ?mock=1.
// Lets the whole UI run with no backend and no other tabs.
// Scenario over frames: normal → low quality → sustained head tilt (nudge) → ask_confirmation → calm.
// Shapes mirror tests/fixtures/*.json and src/nunchi/contracts.py.

const SCHEMA = "1.0";

function metrics(over = {}) {
  return {
    ear: null, mar: null, head_roll_deg: null, head_pitch_proxy: null,
    face_scale: null, shoulder_ear_ratio: null, hand_mouth_dist: null, ...over,
  };
}
function quality(over = {}) {
  return { ok: true, brightness: 118.0, sharpness: 210.0, face_px: 96, issues: [], ...over };
}
function frameResult(sessionId, t, over = {}) {
  return {
    schema: SCHEMA, session_id: sessionId, t, face_present: true, persons: 1,
    metrics: metrics(), quality: quality(), events: [], calibrated: true,
    latency_ms: 40.0, backend: "opencv", cv_version: "5.0.0", ...over,
  };
}
function decision(over = {}) {
  return {
    action: "none", message: "", message_ko: "", reason: "", needs_human: false,
    tool_calls: [], evidence: {}, cooldown_s: 0, ...over,
  };
}

// Fake FrameResult.overlay (0-1 coords, server-frame space) mirroring tests/fixtures/frame_result_ok.json.
// Sways with head roll so the demo overlay looks alive. Web mirrors x and draws it.
function overlay(rollDeg = 0, t = 0) {
  const sway = Math.sin(t * 0.8) * 0.015 + (rollDeg / 100); // gentle horizontal drift
  const x = 0.31 + sway;
  return {
    face: [x, 0.22, 0.34, 0.5],
    points: {
      eye_l: [x + 0.10, 0.38],
      eye_r: [x + 0.25, 0.38],
      nose: [x + 0.175, 0.50],
      mouth_l: [x + 0.12, 0.62],
      mouth_r: [x + 0.23, 0.62],
    },
  };
}

export class MockApi {
  constructor() {
    this._frame = 0;
    this._startDate = new Date().toISOString().slice(0, 10);
    this._lastSummary = null;
  }

  async health() {
    await delay(60);
    return { ok: true, cv_version: "5.0.0", backend: "opencv", arch: "arm64", build: "mock" };
  }

  async createSession({ lang }) {
    await delay(120);
    this._frame = 0;
    return {
      session_id: "mock-session",
      calibration: { seconds: 5, instruction: lang === "ko" ? "화면을 바라보고 가만히 계세요" : "Hold still, facing the screen" },
    };
  }

  async sendFrame({ sessionId, t, phase }) {
    await delay(50);
    if (phase === "calibrate") {
      return { result: frameResult(sessionId, t, { calibrated: false }), decision: decision(), calibrated: false };
    }
    const n = this._frame++;
    // Scripted run timeline (each run frame ~0.5s at 2fps):
    // 0-5   normal
    // 6-9   quality bad (too dark, no face)
    // 10-15 head tilt building -> nudge at 14
    // 16-17 face a bit close
    // 18    uncertain yawn -> second_look(enhance) -> cleared -> no action (active perception resolves it)
    // 19    uncertain drink -> second_look -> still uncertain -> ask_confirmation (human-in-the-loop)
    // 20+   calm / none
    if (n < 6) {
      return {
        result: frameResult(sessionId, t, { metrics: metrics({ ear: 0.28, head_roll_deg: 2.1, face_scale: 1.02 }), overlay: overlay(2.1, t) }),
        decision: decision(),
        calibrated: true,
      };
    }
    if (n < 10) {
      return {
        result: frameResult(sessionId, t, {
          face_present: false, persons: 0,
          metrics: metrics(),
          quality: quality({ ok: false, brightness: 22.0, sharpness: 0.0, face_px: 0, issues: ["too_dark", "no_face"] }),
          overlay: null, // no face -> server gives no overlay (exercises the "draw nothing" path)
        }),
        decision: decision({ action: "request_recalibration", reason: "quality:too_dark",
          message: "It's a little dark — more light would help.", message_ko: "조금 어두워요 — 조명을 밝혀 주세요.",
          tool_calls: [{ tool: "get_quality", args: {}, result_summary: "too_dark" }] }),
        calibrated: true,
      };
    }
    if (n < 14) {
      const roll = 8 + (n - 10) * 2.5;
      return {
        result: frameResult(sessionId, t, {
          metrics: metrics({ ear: 0.27, head_roll_deg: roll, face_scale: 1.05 }),
          events: [{ type: "head_tilt", start: t - (n - 10) * 0.5, end: null, confidence: 0.8, count: 1 }],
          overlay: overlay(roll, t),
        }),
        decision: decision(),
        calibrated: true,
      };
    }
    if (n === 14) {
      return {
        result: frameResult(sessionId, t, {
          metrics: metrics({ ear: 0.27, head_roll_deg: 14.2, face_scale: 1.05 }),
          events: [{ type: "head_tilt", start: t - 2.5, end: null, confidence: 0.82, count: 1 }],
          overlay: overlay(14.2, t),
        }),
        decision: decision({
          action: "nudge", reason: "sustained:head_tilt",
          message: "You have been tilting your head for a while. Straighten up?",
          message_ko: "고개가 한참 기울어져 있어요. 바로 세워볼까요?",
          tool_calls: [{ tool: "get_quality", args: {}, result_summary: "ok" }],
          evidence: { head_roll_deg: 14.2, duration_s: 2.5 }, cooldown_s: 300,
        }),
        calibrated: true,
      };
    }
    if (n < 18) {
      return {
        result: frameResult(sessionId, t, { metrics: metrics({ ear: 0.26, head_roll_deg: 3.0, face_scale: 1.18 }), overlay: overlay(3.0, t) }),
        decision: decision(),
        calibrated: true,
      };
    }
    if (n === 18) {
      // Active perception: re-analyse before bothering the user. This time it CLEARS → no action.
      return {
        result: frameResult(sessionId, t, {
          metrics: metrics({ ear: 0.22, mar: 0.4, head_roll_deg: 2.0, face_scale: 1.1 }),
          overlay: overlay(2.0, t),
        }),
        decision: decision({
          action: "none", reason: "second_look:yawn_cleared",
          tool_calls: [
            { tool: "second_look", args: { variant: "enhance" }, result_summary: "mar below threshold after CLAHE" },
          ],
          evidence: { mar: 0.4 },
        }),
        calibrated: true,
      };
    }
    if (n === 19) {
      // Re-analyse, but it stays uncertain → ask the user (human-in-the-loop).
      return {
        result: frameResult(sessionId, t, {
          metrics: metrics({ ear: 0.2, head_roll_deg: 2.0, face_scale: 1.2, hand_mouth_dist: 0.12 }),
          events: [{ type: "drink", start: t - 0.5, end: null, confidence: 0.55, count: 1 }],
          overlay: overlay(2.0, t),
        }),
        decision: decision({
          action: "ask_confirmation", reason: "second_look:drink_uncertain", needs_human: true,
          message: "Was that a sip of your drink?",
          message_ko: "방금 음료 한 모금 하셨나요?",
          tool_calls: [
            { tool: "second_look", args: { variant: "zoom_face" }, result_summary: "hand-mouth still ambiguous" },
            { tool: "get_metrics_window", args: { seconds: 3 }, result_summary: "hand near mouth 1.5s" },
          ],
          evidence: { hand_mouth_dist: 0.12 }, cooldown_s: 0,
        }),
        calibrated: true,
      };
    }
    // calm tail
    return {
      result: frameResult(sessionId, t, { metrics: metrics({ ear: 0.29, head_roll_deg: 1.0, face_scale: 1.0 }), overlay: overlay(1.0, t) }),
      decision: decision(),
      calibrated: true,
    };
  }

  async endSession() {
    await delay(150);
    const summary = {
      session_id: "mock-session", date: this._startDate, duration_s: 1500,
      counts: { blink: 420, head_tilt: 3, drink: 1, forward_head: 2 },
      seconds: { forward_head: 180.0, head_tilt: 7.5 },
      longest_s: { forward_head: 95.0 },
      nudges_sent: 1, nudges_suppressed: 2, confirmations_asked: 1, recalibrations: 1,
    };
    this._lastSummary = summary;
    return {
      summary,
      report: {
        text_en: "A steady session. Your posture held well overall, with one longer forward-head stretch near the middle — a short break there would help. Blink rate looked healthy.",
        text_ko: "전반적으로 안정적인 세션이었어요. 중반에 거북목이 한 번 길어졌는데, 그때 잠깐 쉬어 주면 좋아요. 깜빡임 빈도는 건강한 편이었습니다.",
        highlights: ["posture mostly neutral", "one long forward-head stretch", "healthy blink rate"],
      },
    };
  }

  // GET /v1/summary — today's summary + a fabricated "yesterday" so the comparison UI has data.
  async getSummary() {
    await delay(80);
    const summary = this._lastSummary || {
      session_id: "mock-session", date: this._startDate, duration_s: 1500,
      counts: { forward_head: 2 }, seconds: { forward_head: 180.0 }, longest_s: { forward_head: 95.0 },
      nudges_sent: 1, nudges_suppressed: 2, confirmations_asked: 1, recalibrations: 1,
    };
    const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    const previous = {
      session_id: "mock-prev", date: yesterday, duration_s: 1260,
      counts: { blink: 500, head_tilt: 6, forward_head: 4 },
      seconds: { forward_head: 240.0, head_tilt: 15.0 },
      longest_s: { forward_head: 130.0 },
      nudges_sent: 3, nudges_suppressed: 1, confirmations_asked: 0, recalibrations: 2,
    };
    return { summary, previous };
  }
}

function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
