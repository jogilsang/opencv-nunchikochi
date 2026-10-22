// demo.js — DemoApi: replays a pre-recorded synthetic session for ?demo=1. OWNER: web tab.
// Same surface as Api / MockApi (createSession, sendFrame, endSession, getSummary) so the
// app uses the exact same code path — only the data source changes (one adapter).
// Plays web/assets/demo-session.json: image-free FrameResult/Decision steps + end summary.
// This is DEMO PLAYBACK, never presented as a real measurement.

export class DemoLoadError extends Error {
  constructor(message) { super(message); this.name = "DemoLoadError"; }
}

export class DemoApi {
  constructor({ url = "assets/demo-session.json" } = {}) {
    this._url = url;
    this._data = null;
    this._i = 0;
  }

  // Load the recorded session once. Throws DemoLoadError on failure (app shows EN/KO notice).
  async load() {
    let res;
    try {
      res = await fetch(this._url, { cache: "no-store" });
    } catch {
      throw new DemoLoadError("demo fetch failed");
    }
    if (!res.ok) throw new DemoLoadError(`demo HTTP ${res.status}`);
    let json;
    try {
      json = await res.json();
    } catch {
      throw new DemoLoadError("demo JSON parse failed");
    }
    if (!json || !Array.isArray(json.steps) || json.steps.length === 0) {
      throw new DemoLoadError("demo has no steps");
    }
    this._data = json;
    this._i = 0;
    return json;
  }

  get frameIntervalMs() {
    return (this._data && this._data.frameIntervalMs) || 500;
  }

  async health() {
    return { ok: true, cv_version: "5.0.0", backend: "opencv", arch: "arm64", build: "demo" };
  }

  async createSession({ lang } = {}) {
    if (!this._data) await this.load();
    this._i = 0;
    const c = this._data.calibration || { seconds: 5 };
    return {
      session_id: "demo-session",
      calibration: {
        seconds: c.seconds || 5,
        instruction: lang === "ko" ? (c.instruction_ko || "") : (c.instruction_en || ""),
      },
    };
  }

  // Replays steps in order. During calibrate we don't advance the run timeline.
  // After the last step, the calm tail (last step) repeats so playback never dead-ends.
  async sendFrame({ phase } = {}) {
    if (!this._data) await this.load();
    const steps = this._data.steps;
    if (phase === "calibrate") {
      const first = clone(steps[0]);
      first.calibrated = false;
      if (first.result) first.result.calibrated = false;
      return first;
    }
    const idx = Math.min(this._i, steps.length - 1);
    this._i += 1;
    return clone(steps[idx]);
  }

  async endSession() {
    if (!this._data) await this.load();
    return clone(this._data.end || { summary: {}, report: { text_en: "", text_ko: "" } });
  }

  async getSummary() {
    if (!this._data) await this.load();
    return { summary: clone(this._data.end && this._data.end.summary) || null, previous: clone(this._data.previous) || null };
  }

  // Playback is complete once every recorded step has been served at least once.
  get done() {
    return !!this._data && this._i >= this._data.steps.length;
  }
}

function clone(o) {
  return o == null ? o : JSON.parse(JSON.stringify(o));
}
