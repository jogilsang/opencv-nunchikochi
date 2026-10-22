// api.js — HTTP client for CONTRACTS §3. OWNER: web tab.
// All calls go through here so mock mode can swap this with the same surface.

export class ApiError extends Error {
  constructor(message, { status = 0, temporary = false } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.temporary = temporary; // UI shows "temporary issue" + recoverable
  }
}

export class Api {
  constructor({ apiBase, apiKey } = {}) {
    this.apiBase = (apiBase || "").replace(/\/$/, "");
    this.apiKey = apiKey || "";
  }

  _headers(extra = {}) {
    const h = { ...extra };
    if (this.apiKey) h["X-Api-Key"] = this.apiKey;
    return h;
  }

  async _json(res) {
    // Network/5xx = temporary (recoverable). 4xx / bad shape = hard but UI still recovers.
    if (!res.ok) {
      throw new ApiError(`HTTP ${res.status}`, { status: res.status, temporary: res.status >= 500 });
    }
    try {
      return await res.json();
    } catch {
      throw new ApiError("bad response shape", { status: res.status, temporary: true });
    }
  }

  async health() {
    const res = await this._fetch(`${this.apiBase}/healthz`, { headers: this._headers() });
    return this._json(res);
  }

  async createSession({ clientDate, lang }) {
    const res = await this._fetch(`${this.apiBase}/v1/sessions`, {
      method: "POST",
      headers: this._headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ client_date: clientDate, lang }),
    });
    return this._json(res);
  }

  // frameBlob: JPEG Blob. phase: "calibrate" | "run".
  async sendFrame({ sessionId, t, frameBlob, phase }) {
    const fd = new FormData();
    fd.append("session_id", sessionId);
    fd.append("t", String(t));
    if (phase) fd.append("phase", phase);
    fd.append("frame", frameBlob, "f.jpg");
    const res = await this._fetch(`${this.apiBase}/v1/frames`, {
      method: "POST",
      headers: this._headers(), // let browser set multipart boundary
      body: fd,
    });
    return this._json(res);
  }

  async endSession(sessionId) {
    const res = await this._fetch(`${this.apiBase}/v1/sessions/${encodeURIComponent(sessionId)}/end`, {
      method: "POST",
      headers: this._headers(),
    });
    return this._json(res);
  }

  async getSummary(date) {
    const q = date ? `?date=${encodeURIComponent(date)}` : "";
    const res = await this._fetch(`${this.apiBase}/v1/summary${q}`, { headers: this._headers() });
    return this._json(res);
  }

  async _fetch(url, opts) {
    try {
      return await fetch(url, opts);
    } catch (e) {
      throw new ApiError("network", { status: 0, temporary: true });
    }
  }
}
