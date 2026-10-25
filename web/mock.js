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

// Build a bad-posture timeline (W16, provisional A11 contract): forward_head + head_tilt
// events bucketed into 5/10/30/60-minute slices with {start_s, events, seconds}, plus a
// per-hour rate (null if the session is under 10 min). Numbers only — no frames.
function buildTimeline(durationS, totalBadEvents, totalBadSeconds) {
  const UNITS = { "5m": 300, "10m": 600, "30m": 1800, "60m": 3600 };
  const out = {};
  for (const [key, step] of Object.entries(UNITS)) {
    const slices = Math.max(1, Math.ceil(durationS / step));
    // Front-loaded weights (more bad posture early, settling later) so the chart tells a
    // small, realistic "started rough, improved" story instead of a flat line. Deterministic.
    const weights = [];
    for (let i = 0; i < slices; i++) weights.push(slices - i);
    const wsum = weights.reduce((a, b) => a + b, 0) || 1;
    const arr = [];
    let allocated = 0;
    for (let i = 0; i < slices; i++) {
      const last = i === slices - 1;
      const events = last ? Math.max(0, totalBadEvents - allocated) : Math.round(totalBadEvents * (weights[i] / wsum));
      allocated += events;
      const secFrac = weights[i] / wsum;
      arr.push({ start_s: i * step, events, seconds: Math.round(totalBadSeconds * secFrac * 10) / 10 });
    }
    out[key] = arr;
  }
  const per_hour_rate = durationS >= 600 ? Math.round((totalBadEvents / (durationS / 3600)) * 10) / 10 : null;
  return { bad_posture: out, per_hour_rate };
}

function badTotals(summary) {
  const c = summary.counts || {};
  const s = summary.seconds || {};
  const events = (c.forward_head || 0) + (c.head_tilt || 0);
  const seconds = (s.forward_head || 0) + (s.head_tilt || 0);
  return { events, seconds };
}

// Real-contract bad-posture trend (W17, mirrors nunchi.agent.summary._trend): compares
// today's per-hour rate to the mean of up to 5 prior sessions. Lower = better. Returns the
// same dict the server puts on `report.trend`: direction + today_rate/baseline_rate/n + EN/KO
// line. `history` is oldest-first serialised summaries carrying timeline.per_hour_rate.
function mockTrend(todayRate, history) {
  const prior = (history || [])
    .map((h) => (h && h.timeline && typeof h.timeline.per_hour_rate === "number") ? h.timeline.per_hour_rate : null)
    .filter((r) => r != null).slice(0, 5);
  if (todayRate == null || prior.length === 0) {
    return { direction: "na", today_rate: todayRate ?? null, baseline_rate: null, n: prior.length,
      line_en: "No earlier sessions to compare with yet.", line_ko: "아직 비교할 이전 기록이 없어요." };
  }
  const baseline = Math.round((prior.reduce((a, b) => a + b, 0) / prior.length) * 100) / 100;
  const pct = baseline === 0 ? null : Math.round(((todayRate - baseline) / baseline) * 1000) / 10;
  let direction = "same";
  if (pct != null && Math.abs(pct) <= 10) direction = "same";
  else if (todayRate < baseline) direction = "improving";
  else if (todayRate > baseline) direction = "worsening";
  const n = prior.length;
  let line_en, line_ko;
  if (direction === "improving") {
    line_en = `Fewer bad-posture events this time: ${todayRate}/h vs a ${baseline}/h average over your last ${n} sessions.`;
    line_ko = `이번에 나쁜 자세가 더 줄었어요: 시간당 ${todayRate}회 (최근 ${n}회 평균 ${baseline}회).`;
  } else if (direction === "worsening") {
    line_en = `More bad-posture events this time: ${todayRate}/h vs a ${baseline}/h average over your last ${n} sessions.`;
    line_ko = `이번엔 나쁜 자세가 더 늘었어요: 시간당 ${todayRate}회 (최근 ${n}회 평균 ${baseline}회).`;
  } else {
    line_en = `About the same as before: ${todayRate}/h vs a ${baseline}/h average over your last ${n} sessions.`;
    line_ko = `이전과 비슷해요: 시간당 ${todayRate}회 (최근 ${n}회 평균 ${baseline}회).`;
  }
  return { direction, today_rate: todayRate, baseline_rate: baseline, n, pct_change: pct, line_en, line_ko };
}

// Build an oldest-first history of serialised summaries (each carries timeline.per_hour_rate +
// date), matching GET /v1/summary `history`. Improving: earlier rates higher than `todayRate`.
function mockHistory(todayRate) {
  const base = typeof todayRate === "number" ? todayRate : 6.0;
  const priorRates = [base + 5.4, base + 3.4, base + 1.4]; // 3 earlier sessions, descending to today
  return priorRates.map((r, i) => {
    const d = new Date(Date.now() - (priorRates.length - i) * 86400000).toISOString().slice(0, 10);
    return { session_id: `mock-prev-${i}`, date: d, duration_s: 1500, counts: {}, seconds: {},
      timeline: { bad_posture: {}, per_hour_rate: Math.round(r * 10) / 10 } };
  });
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
    const bt = badTotals(summary);
    summary.timeline = buildTimeline(summary.duration_s, bt.events, bt.seconds);
    this._lastSummary = summary;
    const todayRate = summary.timeline.per_hour_rate;
    const history = mockHistory(todayRate); // oldest-first prior sessions
    return {
      summary,
      report: {
        text_en: "A steady session. Your posture held well overall, with one longer forward-head stretch near the middle — a short break there would help. Blink rate looked healthy.",
        text_ko: "전반적으로 안정적인 세션이었어요. 중반에 거북목이 한 번 길어졌는데, 그때 잠깐 쉬어 주면 좋아요. 깜빡임 빈도는 건강한 편이었습니다.",
        highlights: ["posture mostly neutral", "one long forward-head stretch", "healthy blink rate"],
        // W17: real contract — the server attaches the multi-session trend here on /end.
        trend: mockTrend(todayRate, history),
      },
    };
  }

  // GET /v1/summary — today's summary + previous + recent history (oldest-first, ≤5),
  // matching CONTRACTS §3. Each history item is a serialised summary carrying
  // timeline.per_hour_rate + date. Numbers only.
  async getSummary() {
    await delay(80);
    const summary = this._lastSummary || {
      session_id: "mock-session", date: this._startDate, duration_s: 1500,
      counts: { forward_head: 2 }, seconds: { forward_head: 180.0 }, longest_s: { forward_head: 95.0 },
      nudges_sent: 1, nudges_suppressed: 2, confirmations_asked: 1, recalibrations: 1,
    };
    if (!summary.timeline) { const b = badTotals(summary); summary.timeline = buildTimeline(summary.duration_s || 0, b.events, b.seconds); }
    const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
    const previous = {
      session_id: "mock-prev", date: yesterday, duration_s: 1260,
      counts: { blink: 500, head_tilt: 6, forward_head: 4 },
      seconds: { forward_head: 240.0, head_tilt: 15.0 },
      longest_s: { forward_head: 130.0 },
      nudges_sent: 3, nudges_suppressed: 1, confirmations_asked: 0, recalibrations: 2,
    };
    const pbt = badTotals(previous);
    previous.timeline = buildTimeline(previous.duration_s, pbt.events, pbt.seconds);
    const history = mockHistory(summary.timeline && summary.timeline.per_hour_rate);
    return { summary, previous, history };
  }
}

function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}
