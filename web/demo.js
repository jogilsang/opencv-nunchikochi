// demo.js — DemoApi: replays a pre-recorded synthetic session for ?demo=1. OWNER: web tab.
// Same surface as Api / MockApi (createSession, sendFrame, endSession, getSummary) so the
// app uses the exact same code path — only the data source changes (one adapter).
// Plays web/assets/demo-session.json: image-free FrameResult/Decision steps + end summary.
// This is DEMO PLAYBACK, never presented as a real measurement.

export class DemoLoadError extends Error {
  constructor(message) { super(message); this.name = "DemoLoadError"; }
}

export class DemoApi {
  constructor({ url = "assets/demo-session.json", loop = false } = {}) {
    this._url = url;
    this._data = null;
    this._i = 0;
    // loop=true (default demo pacing): replay wraps forever and `done` never trips, so the
    // run screen stays up at realtime speed until the judge ends it (W13 defect 4).
    // loop=false (fast mode ?demo=1&fast=1 / e2e / recording): serve each step once, then
    // `done` flips true and the app auto-advances to the report — the pre-W13 behaviour.
    this._loop = !!loop;
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
  // Loop mode wraps around so playback never dead-ends; one-shot mode holds on the last
  // (calm) step and flips `done` so the app can auto-advance to the report.
  async sendFrame({ phase } = {}) {
    if (!this._data) await this.load();
    const steps = this._data.steps;
    if (phase === "calibrate") {
      const first = clone(steps[0]);
      first.calibrated = false;
      if (first.result) first.result.calibrated = false;
      return first;
    }
    let idx;
    if (this._loop) {
      idx = this._i % steps.length;      // wrap forever
    } else {
      idx = Math.min(this._i, steps.length - 1); // hold on the last step
    }
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

  // Playback is "done" only in one-shot mode once every recorded step has been served at
  // least once. In loop mode it never trips (the judge ends the session explicitly).
  get done() {
    return !this._loop && !!this._data && this._i >= this._data.steps.length;
  }
}

function clone(o) {
  return o == null ? o : JSON.parse(JSON.stringify(o));
}
