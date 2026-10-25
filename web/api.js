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
  constructor({ apiBase, apiKey, anonId } = {}) {
    this.apiBase = (apiBase || "").replace(/\/$/, "");
    this.apiKey = apiKey || "";
    // W17: anonymous browser id (numbers-only continuity). Sent as X-Anon-Id on every
    // request so the server can link a user's daily summaries without any login or PII.
    // CORS on the service already allows X-Anon-Id (CONTRACTS §3 allow_headers).
    this.anonId = anonId || "";
  }

  _headers(extra = {}) {
    const h = { ...extra };
    if (this.apiKey) h["X-Api-Key"] = this.apiKey;
    if (this.anonId) h["X-Anon-Id"] = this.anonId;
    return h;
  }

  async _json(res) {
    // Network/5xx = temporary (recoverable). 4xx / bad shape = hard but UI still recovers.
    if (!res.ok) {
      const err = new ApiError(`HTTP ${res.status}`, { status: res.status, temporary: res.status >= 500 });
      // Attach the server's structured `error` code when present (e.g. key_expired / key_invalid)
      // so the UI can distinguish causes. Parsing a short JSON body here keeps no secret in memory.
      try {
        const body = await res.clone().json();
        if (typeof body?.error === "string") err.code = body.error;
      } catch { /* no/!json body */ }
      throw err;
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

  // W21: request a 30-minute trial key. No X-Api-Key, no body (CONTRACTS C17 §API).
  // On 429 (ip_daily_limit) / 503 (capacity) / any error, throw an ApiError whose `.code` is the
  // server's `error` field (e.g. "ip_daily_limit", "capacity") so the UI can message precisely.
  // The returned key is handed back to the caller to hold in memory only — never stored here.
  async createTrialKey() {
    let res;
    try {
      res = await this._fetch(`${this.apiBase}/v1/keys`, { method: "POST" });
    } catch (e) {
      throw e; // network ApiError (status 0, temporary)
    }
    if (res.ok) {
      try {
        return await res.json(); // {key, expires_at, ttl_s, remaining_today}
      } catch {
        throw new ApiError("bad response shape", { status: res.status, temporary: true });
      }
    }
    // error: parse the structured body for the precise cause (don't log/keep it)
    let code = "";
    let retryAfter = 0;
    try {
      const body = await res.json();
      code = typeof body?.error === "string" ? body.error : "";
      retryAfter = Number(body?.retry_after_s) || 0;
    } catch { /* no/!json body */ }
    const err = new ApiError(`HTTP ${res.status}`, { status: res.status, temporary: res.status >= 500 });
    err.code = code;
    err.retryAfterS = retryAfter;
    return Promise.reject(err);
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
