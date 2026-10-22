// app.js — screen state machine + wiring. OWNER: web tab.
// Flow: start -> (camera error?) -> calibrate(5s) -> run(nudge/confirm/quality) -> report.
// ?mock=1 runs the whole thing with no camera and no server.

import { STRINGS, setLang, getLang, t } from "./i18n.js";
import { Api } from "./api.js";
import { MockApi } from "./mock.js";
import { DemoApi, DemoLoadError } from "./demo.js";
import { Capture, CAM, isSecure } from "./capture.js";
import { drawOverlay, clearOverlay } from "./overlay.js";
import { buildShareCard, downloadBlob } from "./sharecard.js";

const params = new URLSearchParams(location.search);
const MOCK = params.get("mock") === "1";
const DEMO = params.get("demo") === "1";
const DEV = params.get("dev") === "1";

// Live-mode access key. Memory only: never written to state, localStorage, the URL, or logs.
let liveKey = "";

const state = {
  cfg: { apiBase: "http://localhost:8000", apiKey: "", lang: "en", fps: 2 },
  mode: "",              // "demo" | "live" — chosen on the start screen (W6)
  api: null,
  capture: null,
  sessionId: null,
  startTime: 0,
  lastNudgeAt: 0,
  recentEvents: [],   // {type, at}
  confirmOpen: false,
  tempErrorTimer: null,
  overlayOn: true,
  lastOverlay: null,     // last FrameResult.overlay for redraw
  lastReport: null,      // {summary, report, previous} for share card / re-render
  agentLog: [],          // [{ts, action, reason, tools, evidence, needsHuman, highlight}]
  agentShowAll: false,
  bytesWindow: [],       // [{at, bytes}] for dev KB/s
};

// ---------- config ----------
async function loadConfig() {
  try {
    const res = await fetch("config.json", { cache: "no-store" });
    if (res.ok) Object.assign(state.cfg, await res.json());
  } catch {
    // config.json is optional (gitignored). example values are fine for mock.
  }
  const qlang = params.get("lang");
  if (qlang) state.cfg.lang = qlang;
  setLang(state.cfg.lang);
}

// ---------- i18n render ----------
function applyI18n() {
  document.documentElement.lang = getLang();
  for (const el of document.querySelectorAll("[data-i18n]")) {
    const v = t(el.getAttribute("data-i18n"));
    if (typeof v === "string") el.textContent = v;
  }
  // privacy bullet list
  const ul = document.getElementById("privacy-points");
  ul.innerHTML = "";
  for (const line of STRINGS[getLang()].privacyPoints) {
    const li = document.createElement("li");
    li.textContent = line;
    ul.appendChild(li);
  }
  document.getElementById("lang-en").classList.toggle("active", getLang() === "en");
  document.getElementById("lang-ko").classList.toggle("active", getLang() === "ko");
}

// ---------- screens ----------
function show(id) {
  for (const s of document.querySelectorAll(".screen")) s.classList.toggle("active", s.id === id);
}

// ---------- start ----------
function initStart() {
  const consent = document.getElementById("consent");
  const btn = document.getElementById("btn-start");
  const hint = document.getElementById("start-hint");
  const livePanel = document.getElementById("live-panel");
  const keyInput = document.getElementById("live-key");
  const demoCard = document.getElementById("mode-demo");
  const liveCard = document.getElementById("mode-live");

  // badges for ?mock / ?demo deep-links
  if (MOCK) document.getElementById("mock-badge").hidden = false;
  if (DEMO) {
    const b = document.getElementById("demo-badge");
    if (b) b.hidden = false;
    const c = document.getElementById("demo-corner");
    if (c) c.hidden = false;
  }

  // Gate the Start button on: mode chosen + consent + (live => key present & service not down).
  const refresh = () => {
    let ok = !!state.mode && consent.checked;
    let msg = "";
    if (!state.mode) { msg = t("modePick"); ok = false; }
    else if (state.mode === "live") {
      if (!liveKey) { msg = t("liveKeyMissing"); ok = false; }
      else if (!state.cfg.apiBase) { msg = t("liveNoConfig"); ok = false; }
    }
    btn.disabled = !ok;
    hint.textContent = ok ? "" : msg;
    hint.classList.toggle("warn", !!msg && (state.mode === "live"));
  };

  const selectMode = (mode) => {
    state.mode = mode;
    demoCard.setAttribute("aria-checked", String(mode === "demo"));
    liveCard.setAttribute("aria-checked", String(mode === "live"));
    livePanel.hidden = mode !== "live";
    if (mode === "live") checkService();
    refresh();
    if (mode === "live") keyInput.focus();
  };

  demoCard.addEventListener("click", () => selectMode("demo"));
  liveCard.addEventListener("click", () => selectMode("live"));
  // keyboard: Enter/Space on a role=radio card selects it
  for (const [card, mode] of [[demoCard, "demo"], [liveCard, "live"]]) {
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectMode(mode); }
    });
  }

  // Access key: memory only. We read it into the module-level `liveKey` and never persist it.
  keyInput.addEventListener("input", () => { liveKey = keyInput.value; refresh(); });

  consent.addEventListener("change", refresh);
  btn.addEventListener("click", () => {
    if (state.mode === "live") beginSession({ live: true });
    else beginSession(); // demo / mock
  });

  // Deep-link convenience: ?demo / ?mock preselect the no-camera path.
  if (DEMO || MOCK) selectMode("demo");
  else refresh();
}

// Probe the configured service and show an honest status line (arch / OpenCV version).
// Never invents values: if a field is absent, it's omitted. Updates the Start gate too.
async function checkService() {
  const statusEl = document.getElementById("live-status");
  const refreshStart = () => document.getElementById("consent").dispatchEvent(new Event("change"));
  if (!state.cfg.apiBase) {
    setLiveStatus(statusEl, "down", t("liveNoConfig"), null);
    refreshStart();
    return;
  }
  setLiveStatus(statusEl, "", t("liveStatusChecking"), null);
  try {
    const probe = new Api({ apiBase: state.cfg.apiBase, apiKey: liveKey || state.cfg.apiKey });
    const h = await probe.health(); // {ok, cv_version, backend, arch, build}
    const bits = [];
    if (h && h.arch) bits.push(h.arch);                       // e.g. arm64 (AWS Graviton)
    if (h && h.backend) bits.push(h.backend);                 // e.g. opencv
    if (h && h.cv_version) bits.push("OpenCV " + h.cv_version);
    const runtime = bits.length ? `${t("runtimePrefix")} ${bits.join(" · ")}` : "";
    setLiveStatus(statusEl, "up", t("liveStatusUp"), runtime);
  } catch (e) {
    setLiveStatus(statusEl, "down", t("liveUnreachable"), null);
  }
  refreshStart();
}

function setLiveStatus(el, cls, text, runtime) {
  el.className = "live-status" + (cls ? " " + cls : "");
  el.innerHTML = "";
  const led = document.createElement("span"); led.className = "led"; led.setAttribute("aria-hidden", "true");
  const t1 = document.createElement("span"); t1.textContent = text;
  el.append(led, t1);
  if (runtime) { const r = document.createElement("span"); r.className = "runtime"; r.textContent = " · " + runtime; el.append(r); }
}

// ---------- error screen (camera + network/http/session) ----------
// One friendly, recoverable screen. Each state = cause + next action in one line.
const ERROR_MAP = {
  [CAM.DENIED]: { title: "camDeniedTitle", body: "camDeniedBody", retry: "retry", showMock: true },
  [CAM.NONE]: { title: "camNoneTitle", body: "camNoneBody", retry: "retry", showMock: true },
  [CAM.INSECURE]: { title: "camInsecureTitle", body: "camInsecureBody", retry: "retry", showMock: true },
  [CAM.ERROR]: { title: "camNoneTitle", body: "camNoneBody", retry: "retry", showMock: true },
  busy: { title: "errBusyTitle", body: "errBusy", retry: "retry", showMock: true },
  offline: { title: "errOfflineTitle", body: "errOffline", retry: "retry", showMock: true },
  slow: { title: "errSlowTitle", body: "errSlow", retry: "retry", showMock: false },
  unauthorized: { title: "err401Title", body: "err401", retry: "retry", showMock: true },
  rate_limited: { title: "err429Title", body: "err429", retry: "retry", showMock: false },
  server: { title: "err5xxTitle", body: "err5xx", retry: "retry", showMock: true },
  expired: { title: "errExpiredTitle", body: "errExpired", retry: "restart", showMock: false },
};

// Map an ApiError (status) to an error kind.
function errorKindFromStatus(status) {
  if (status === 0) return navigator.onLine === false ? "offline" : "server";
  if (status === 401 || status === 403) return "unauthorized";
  if (status === 404 || status === 410) return "expired";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "server";
  return "server";
}

function showError(kind, { onRetry } = {}) {
  const cfg = ERROR_MAP[kind] || ERROR_MAP[CAM.ERROR];
  document.getElementById("camerr-title").textContent = t(cfg.title);
  document.getElementById("camerr-body").textContent = t(cfg.body);
  const retryBtn = document.getElementById("btn-retry");
  const mockBtn = document.getElementById("btn-tomock");
  retryBtn.textContent = t(cfg.retry);
  retryBtn.onclick = onRetry || (() => beginSession());
  mockBtn.hidden = !cfg.showMock;
  show("screen-camerror");
  retryBtn.focus();
}

// kept name for camera statuses; delegates to showError
function showCamError(status) {
  showError(status);
}

function initCamError() {
  document.getElementById("btn-retry").addEventListener("click", () => beginSession());
  document.getElementById("btn-tomock").addEventListener("click", () => {
    beginSession({ forceMock: true });
  });
}

// ---------- session lifecycle ----------
async function beginSession({ forceMock = false, live = false } = {}) {
  const useMock = MOCK || forceMock;
  // Demo mode: replay a recorded session (no camera, no server). Chosen on the start
  // screen (state.mode === "demo") or via ?demo=1. Mock/forceMock take precedence.
  const useDemo = !useMock && !live && (DEMO || state.mode === "demo");
  if (useDemo) {
    state.api = new DemoApi();
    try {
      await state.api.load();
    } catch (e) {
      showDemoLoadError();
      return;
    }
    // badge/corner also show here when demo is picked without the ?demo deep-link
    const b = document.getElementById("demo-badge"); if (b) b.hidden = false;
    const c = document.getElementById("demo-corner"); if (c) c.hidden = false;
    state.capture = new Capture({ fps: state.cfg.fps, mock: true });
    state.recentEvents = [];
    state.lastNudgeAt = 0;
    clearToasts();
    await state.capture.start(); // canvas fake source, always OK
    const sess = await state.api.createSession({ lang: getLang() });
    state.sessionId = sess.session_id;
    await calibrate(sess.calibration || { seconds: 5 });
    return;
  }

  // Live (real camera + real server) or mock. For live we use the configured apiBase and
  // the key the judge pasted (memory only); mock swaps both out.
  state.api = useMock
    ? new MockApi()
    : new Api({ apiBase: state.cfg.apiBase, apiKey: liveKey || state.cfg.apiKey });
  state.capture = new Capture({ fps: state.cfg.fps, mock: useMock });
  state.recentEvents = [];
  state.lastNudgeAt = 0;
  clearToasts();

  const camStatus = await state.capture.start();
  if (camStatus !== CAM.OK) {
    showCamError(camStatus);
    return;
  }

  // create session (server or mock)
  let sess;
  try {
    const clientDate = new Date().toISOString().slice(0, 10);
    sess = await state.api.createSession({ clientDate, lang: getLang() });
  } catch (e) {
    const status = e && typeof e.status === "number" ? e.status : 0;
    showError(errorKindFromStatus(status));
    state.capture.stop();
    return;
  }
  state.sessionId = sess.session_id;
  await calibrate(sess.calibration || { seconds: 5 });
}

// Demo data could not be loaded — show an EN/KO notice on the error screen (recoverable).
function showDemoLoadError() {
  document.getElementById("camerr-title").textContent = t("demoLoadTitle");
  document.getElementById("camerr-body").textContent = t("demoLoadBody");
  const retryBtn = document.getElementById("btn-retry");
  const mockBtn = document.getElementById("btn-tomock");
  retryBtn.textContent = t("retry");
  retryBtn.onclick = () => beginSession();
  mockBtn.hidden = true;
  show("screen-camerror");
  retryBtn.focus();
}

// ---------- calibrate ----------
async function calibrate(calib) {
  show("screen-calibrate");
  const seconds = Math.max(1, calib.seconds || 5);
  const countEl = document.getElementById("calib-count");
  const progEl = document.getElementById("calib-progress");
  mirrorInto("calib-canvas");

  state.startTime = performance.now();
  // Pump calibrate frames (phase=calibrate) while counting down; errors are non-fatal here.
  state.capture.startPump(async (blob, tSec) => {
    try {
      await state.api.sendFrame({ sessionId: state.sessionId, t: tSec, frameBlob: blob, phase: "calibrate" });
    } catch { /* calibration frames tolerate drops */ }
  });

  const total = seconds * 1000;
  const t0 = performance.now();
  await new Promise((resolve) => {
    const tick = () => {
      const elapsed = performance.now() - t0;
      const remain = Math.max(0, Math.ceil((total - elapsed) / 1000));
      countEl.textContent = String(remain);
      progEl.style.width = `${Math.min(100, (elapsed / total) * 100)}%`;
      if (elapsed >= total) return resolve();
      requestAnimationFrame(tick);
    };
    tick();
  });

  state.capture.stopPump();
  startRun();
}

// ---------- run ----------
function startRun() {
  show("screen-run");
  mirrorInto("run-canvas");
  resetMetricsUi();
  state.startTime = performance.now();
  state.lastOverlay = null;
  state.agentLog = [];
  clearOverlay(document.getElementById("run-overlay"));
  initOverlayToggle();
  initAgentPanel();
  renderAgentLog();
  state.capture.startPump(async (blob, tSec) => {
    if (blob && typeof blob.size === "number") recordBytes(blob.size);
    try {
      const resp = await state.api.sendFrame({ sessionId: state.sessionId, t: tSec, frameBlob: blob, phase: "run" });
      handleFrame(resp, tSec);
      state.runErrors = 0;
      // Demo playback: when the recorded sequence is exhausted, end and show the report.
      if (DEMO && state.api && state.api.done) {
        state.capture.stopPump();
        setTimeout(() => endSession(), 700); // small beat so the last frame is visible
      }
    } catch (e) {
      // Classify: hard errors (auth/expired) → full error screen; transient → banner + backoff.
      const status = e && typeof e.status === "number" ? e.status : 0;
      const kind = errorKindFromStatus(status);
      if (kind === "unauthorized" || kind === "expired") {
        state.capture.stopPump();
        state.capture.stop();
        showError(kind, kind === "expired" ? { onRetry: () => beginSession() } : undefined);
        return;
      }
      // transient (offline/server/rate limit): keep running, show banner; pump backs off on throw
      state.runErrors = (state.runErrors || 0) + 1;
      flashTempError();
      throw e; // let capture pump apply exponential backoff
    }
  });
  document.getElementById("btn-end").onclick = () => endSession();
}

function initOverlayToggle() {
  const toggle = document.getElementById("overlay-toggle");
  const canvas = document.getElementById("run-overlay");
  const apply = () => {
    // Checkbox meaning is literal: checked = overlay shown. Label stays "Show what OpenCV sees".
    state.overlayOn = toggle.checked;
    canvas.classList.toggle("hidden", !toggle.checked);
    if (state.overlayOn) drawOverlay(canvas, state.lastOverlay);
    else clearOverlay(canvas);
  };
  toggle.checked = state.overlayOn;
  toggle.onchange = apply;
  apply();
}

function handleFrame(resp, tSec = 0) {
  // Guard against shapes that don't match the contract — recover, don't crash.
  if (!resp || typeof resp !== "object" || !resp.result) {
    flashTempError();
    return;
  }
  hideTempError();
  const { result, decision } = resp;
  const qualityPoor = result.quality && result.quality.ok === false;
  renderMetrics(result.metrics || {}, qualityPoor);
  renderQuality(result.quality || {});
  renderEvents(result.events || []);
  // overlay: server may omit it (null) -> draw nothing
  state.lastOverlay = result.overlay || null;
  const canvas = document.getElementById("run-overlay");
  if (state.overlayOn) drawOverlay(canvas, state.lastOverlay);
  else clearOverlay(canvas);
  // agent activity: record every decision (incl. "none") for the evidence panel
  recordAgentDecision(decision, tSec);
  if (decision && decision.action && decision.action !== "none") handleDecision(decision);
}

// ---------- agent activity panel ----------
function recordAgentDecision(d, tSec) {
  if (!d || typeof d !== "object") return;
  const action = typeof d.action === "string" ? d.action : "none";
  const tools = Array.isArray(d.tool_calls) ? d.tool_calls : [];
  const usedSecondLook = tools.some((tc) => tc && tc.tool === "second_look");
  const highlight = usedSecondLook || action === "ask_confirmation";
  state.agentLog.unshift({
    ts: formatClock(),
    action,
    reason: typeof d.reason === "string" ? d.reason : "",
    tools,
    needsHuman: !!d.needs_human,
    usedSecondLook,
    highlight,
  });
  if (state.agentLog.length > 60) state.agentLog.length = 60;
  renderAgentLog();
}

function renderAgentLog() {
  const log = document.getElementById("agent-log");
  const empty = document.getElementById("agent-empty");
  if (!log) return;
  const rows = state.agentShowAll ? state.agentLog : state.agentLog.filter((r) => r.action !== "none");
  log.innerHTML = "";
  empty.hidden = rows.length !== 0;
  for (const r of rows) {
    const li = document.createElement("li");
    li.className = "agent-row " + (r.action === "none" ? "none" : "") + (r.highlight ? " highlight" : "") + (r.needsHuman ? " needs-human" : "");
    // timestamp + icon + action (icon is decorative; text carries meaning — not colour-only)
    const head = document.createElement("div");
    const ts = span("ts", r.ts);
    const ico = span("ico", actionIcon(r.action));
    ico.setAttribute("aria-hidden", "true");
    const act = span("act", t(`action_${r.action}`) || r.action);
    head.append(ts, ico, act);
    if (r.reason) head.append(span("reason", `· ${r.reason}`));
    li.appendChild(head);
    // "OpenCV re-checked before asking you" emphasis
    if (r.usedSecondLook) {
      const re = span("recheck", `↻ ${t("agentRechecked")}`);
      li.appendChild(re);
    }
    // tool calls (names localized; no raw args/coords shown)
    if (r.tools.length) {
      const toolNames = r.tools
        .map((tc) => (tc && tc.tool ? (t(`tool_${tc.tool}`) || tc.tool) : null))
        .filter(Boolean)
        .join(" · ");
      if (toolNames) li.appendChild(span("tools", `${t("agentTool")}: ${toolNames}`));
    }
    log.appendChild(li);
  }
}

function actionIcon(action) {
  return {
    none: "·",
    nudge: "↑",
    ask_confirmation: "?",
    request_recalibration: "⟳",
    suppress_focus: "⠿",
    second_look: "↻",
  }[action] || "•";
}

function initAgentPanel() {
  const panel = document.getElementById("agent-panel");
  const openBtn = document.getElementById("btn-agent");
  const closeBtn = document.getElementById("btn-agent-close");
  const showAll = document.getElementById("agent-showall");
  const setOpen = (open) => {
    panel.hidden = !open;
    openBtn.setAttribute("aria-expanded", String(open));
    if (open) { renderAgentLog(); closeBtn.focus(); } else { openBtn.focus(); }
  };
  openBtn.onclick = () => setOpen(panel.hidden);
  closeBtn.onclick = () => setOpen(false);
  showAll.checked = state.agentShowAll;
  showAll.onchange = () => { state.agentShowAll = showAll.checked; renderAgentLog(); };
  panel.hidden = true;
  openBtn.setAttribute("aria-expanded", "false");
}

function span(cls, text) {
  const s = document.createElement("span");
  s.className = cls;
  s.textContent = text;
  return s;
}
function formatClock() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

// ---------- dev-mode frame throughput (KB/s) ----------
function recordBytes(bytes) {
  const now = performance.now();
  state.bytesWindow.push({ at: now, bytes });
  state.bytesWindow = state.bytesWindow.filter((b) => now - b.at < 3000);
  if (!DEV) return;
  const total = state.bytesWindow.reduce((a, b) => a + b.bytes, 0);
  const kbs = (total / 1024) / 3;
  const el = document.getElementById("dev-stats");
  if (el) { el.hidden = false; el.textContent = `${t("devStats")}: ${kbs.toFixed(1)} KB/s`; }
}

function renderMetrics(m, qualityPoor = false) {
  setMetric("m-ear", m.ear, (v) => v.toFixed(2), (v) => clamp01((v - 0.1) / 0.3), qualityPoor);
  setMetric("m-roll", m.head_roll_deg, (v) => `${v.toFixed(0)}°`, (v) => clamp01(Math.abs(v) / 25), qualityPoor);
  setMetric("m-scale", m.face_scale, (v) => `${v.toFixed(2)}×`, (v) => clamp01((v - 0.8) / 0.6), qualityPoor);
}
function setMetric(id, val, fmt, barFn, qualityPoor) {
  const el = document.getElementById(id);
  const valEl = el.querySelector(".value");
  const bar = el.querySelector(".bar > span");
  const missing = val === null || val === undefined || Number.isNaN(val);
  if (missing) {
    // Correction 3: when quality is poor / no face, show an explicit "measuring" skeleton
    // instead of an empty dash, so the panel doesn't look broken.
    el.classList.remove("na");
    el.classList.toggle("skeleton", qualityPoor);
    el.classList.toggle("na", !qualityPoor);
    valEl.textContent = qualityPoor ? t("measuring") : "—";
    if (!qualityPoor) bar.style.width = "0%";
    return;
  }
  el.classList.remove("na", "skeleton");
  valEl.textContent = fmt(val);
  bar.style.width = `${Math.round(barFn(val) * 100)}%`;
}

function renderQuality(q) {
  const banner = document.getElementById("quality-banner");
  if (q.ok === false && Array.isArray(q.issues) && q.issues.length) {
    const txt = q.issues.map((i) => t(`quality_issue.${i}`)).join(", ");
    banner.textContent = t("qualityBanner") + txt;
    banner.classList.add("show");
  } else {
    banner.classList.remove("show");
  }
}

function renderEvents(events) {
  const now = performance.now();
  for (const e of events) {
    // record each ongoing/started event once by type+start
    const key = `${e.type}@${e.start}`;
    if (!state.recentEvents.find((r) => r.key === key)) {
      state.recentEvents.unshift({ key, type: e.type, at: now });
    }
  }
  state.recentEvents = state.recentEvents.slice(0, 6);
  const host = document.getElementById("event-chips");
  host.innerHTML = "";
  for (const r of state.recentEvents) {
    const chip = document.createElement("span");
    chip.className = "chip" + (now - r.at < 3000 ? " fresh" : "");
    chip.textContent = t(`behavior.${r.type}`);
    host.appendChild(chip);
  }
}

// ---------- decision: nudge / confirmation ----------
function handleDecision(d) {
  if (d.action === "ask_confirmation") {
    showConfirm(d);
  } else if (d.action === "nudge") {
    showNudge(d);
  } else if (d.action === "request_recalibration") {
    // surface as a gentle nudge in the demo (full re-calibrate loop is agent/cloud territory)
    showNudge(d);
  }
}

function msgFor(d) {
  return getLang() === "ko" && d.message_ko ? d.message_ko : (d.message || "");
}

function showNudge(d) {
  const now = performance.now();
  if (now - state.lastNudgeAt < 1500) return; // avoid stacking in demo
  state.lastNudgeAt = now;
  const toast = toastEl(msgFor(d), false);
  toast.setAttribute("role", "status");
  const row = document.createElement("div");
  row.className = "btn-row";
  const ok = document.createElement("button");
  ok.className = "btn";
  ok.textContent = t("yes");
  ok.onclick = () => toast.remove();
  row.appendChild(ok);
  toast.appendChild(row);
  autoDismiss(toast, 6000);
}

function showConfirm(d) {
  if (state.confirmOpen) return;
  state.confirmOpen = true;
  const toast = toastEl(msgFor(d), true);
  // human-in-the-loop prompt: announce assertively and move focus for keyboard users
  toast.setAttribute("role", "alertdialog");
  toast.setAttribute("aria-label", msgFor(d));
  const row = document.createElement("div");
  row.className = "btn-row";
  const yes = document.createElement("button");
  yes.className = "btn";
  yes.textContent = t("yes");
  const no = document.createElement("button");
  no.className = "btn ghost";
  no.textContent = t("no");
  const prevFocus = document.activeElement;
  const close = () => {
    toast.remove();
    state.confirmOpen = false;
    if (prevFocus && prevFocus.focus) prevFocus.focus();
  };
  yes.onclick = close;
  no.onclick = close;
  row.append(yes, no);
  toast.appendChild(row);
  yes.focus();
}

const MAX_TOASTS = 2; // keep at most 2 total so nudges never bury the live metric cards (W5 ①)
function toastEl(message, isConfirm) {
  const host = document.getElementById("toast-host");
  const toast = document.createElement("div");
  toast.className = "toast" + (isConfirm ? " confirm" : "");
  const p = document.createElement("p");
  p.className = "msg";
  p.textContent = message;
  toast.appendChild(p);
  host.appendChild(toast);
  // Cap the stack to MAX_TOASTS. Evict the oldest *dismissible* toasts first so a
  // human-in-the-loop confirm prompt is never silently removed; only fall back to
  // removing the oldest overall if every remaining toast is a confirm.
  while (host.children.length > MAX_TOASTS) {
    const victim = host.querySelector(".toast:not(.confirm)") || host.firstElementChild;
    if (!victim || victim === toast) break;
    victim.remove();
  }
  return toast;
}
function autoDismiss(el, ms) { setTimeout(() => el.remove(), ms); }
function clearToasts() { document.getElementById("toast-host").innerHTML = ""; state.confirmOpen = false; }

function flashTempError() {
  const el = document.getElementById("temp-error");
  el.classList.add("show");
  clearTimeout(state.tempErrorTimer);
  state.tempErrorTimer = setTimeout(() => el.classList.remove("show"), 2500);
}
function hideTempError() { document.getElementById("temp-error").classList.remove("show"); }

// ---------- end + report ----------
async function endSession() {
  state.capture.stopPump();
  let data;
  try {
    data = await state.api.endSession(state.sessionId);
  } catch {
    // Build a minimal recoverable report so the demo never dead-ends.
    data = { summary: { duration_s: (performance.now() - state.startTime) / 1000, nudges_sent: 0, nudges_suppressed: 0, confirmations_asked: 0, counts: {} }, report: { text_en: "", text_ko: "" } };
  }
  // comparison needs today's + yesterday's summary (GET /v1/summary). Non-fatal.
  let previous = null;
  try {
    const date = (data.summary && data.summary.date) || new Date().toISOString().slice(0, 10);
    const sum = await state.api.getSummary(date);
    if (sum && sum.previous) previous = sum.previous;
  } catch { /* comparison is optional */ }
  state.capture.stop();
  clearToasts();
  state.lastReport = { summary: data.summary || {}, report: data.report || {}, previous };
  renderReport(state.lastReport);
  show("screen-report");
}

function renderReport({ summary: s, report: rep, previous }) {
  s = s || {};
  rep = rep || {};
  // number cards
  const cards = document.getElementById("report-cards");
  cards.innerHTML = "";
  const addCard = (n, k) => {
    const c = document.createElement("div");
    c.className = "num-card";
    c.innerHTML = `<div class="n"></div><div class="k"></div>`;
    c.querySelector(".n").textContent = n;
    c.querySelector(".k").textContent = k;
    cards.appendChild(c);
  };
  const mins = Math.round((s.duration_s || 0) / 60);
  addCard(`${mins} ${t("min")}`, t("reportDuration"));
  addCard(String(s.nudges_sent ?? 0), t("reportNudges"));
  addCard(String(s.nudges_suppressed ?? 0), t("reportSuppressed"));
  addCard(String(s.confirmations_asked ?? 0), t("reportConfirms"));

  // narrative text
  const text = getLang() === "ko" ? (rep.text_ko || rep.text_en) : (rep.text_en || rep.text_ko);
  document.getElementById("report-text").textContent = text || "";

  // highlights
  const hl = document.getElementById("report-highlights");
  hl.innerHTML = "";
  const highlights = Array.isArray(rep.highlights) ? rep.highlights.slice(0, 3) : [];
  for (const h of highlights) {
    const li = document.createElement("li");
    li.textContent = String(h);
    hl.appendChild(li);
  }
  hl.parentElement.querySelector(".sub")?.classList.toggle("hidden", highlights.length === 0);

  // comparison vs yesterday
  renderCompare(s, previous);

  // behaviour breakdown table
  renderBreakdown(s);

  // actions
  document.getElementById("btn-copy").onclick = () => copySummary(s, text);
  document.getElementById("btn-new").onclick = () => { show("screen-start"); resetStart(); };
  document.getElementById("btn-download").onclick = () => downloadShareCard(s, highlights);
}

// "N% more/less than yesterday" — observational only, a few meaningful metrics.
function renderCompare(s, previous) {
  const host = document.getElementById("report-compare");
  host.innerHTML = "";
  if (!previous) {
    const p = document.createElement("div");
    p.className = "first";
    p.textContent = t("compareFirst");
    host.appendChild(p);
    return;
  }
  const rows = [
    { k: t("reportDuration"), now: s.duration_s || 0, prev: previous.duration_s || 0 },
    { k: t("reportNudges"), now: s.nudges_sent ?? 0, prev: previous.nudges_sent ?? 0 },
    { k: t("behavior.forward_head"), now: (s.seconds && s.seconds.forward_head) || 0, prev: (previous.seconds && previous.seconds.forward_head) || 0 },
  ];
  for (const r of rows) {
    const pill = document.createElement("div");
    pill.className = "pill";
    const k = document.createElement("span");
    k.className = "k";
    k.textContent = r.k;
    const v = document.createElement("span");
    const { cls, label } = trend(r.now, r.prev);
    v.className = cls;
    v.textContent = label;
    pill.append(k, v);
    host.appendChild(pill);
  }
}

function trend(now, prev) {
  if (!prev) return { cls: "trend-flat", label: t("compareSame") };
  const pct = Math.round(((now - prev) / prev) * 100);
  if (pct > 3) return { cls: "trend-up", label: fmtTpl(t("compareUp"), { pct: Math.abs(pct) }) };
  if (pct < -3) return { cls: "trend-down", label: fmtTpl(t("compareDown"), { pct: Math.abs(pct) }) };
  return { cls: "trend-flat", label: t("compareSame") };
}
function fmtTpl(tpl, vars) {
  return String(tpl).replace(/\{(\w+)\}/g, (_, k) => (k in vars ? vars[k] : `{${k}}`));
}

function renderBreakdown(s) {
  const tbody = document.querySelector("#report-breakdown tbody");
  tbody.innerHTML = "";
  const counts = s.counts || {};
  const seconds = s.seconds || {};
  const longest = s.longest_s || {};
  const keys = Array.from(new Set([...Object.keys(counts), ...Object.keys(seconds), ...Object.keys(longest)]));
  keys.sort((a, b) => (counts[b] || 0) - (counts[a] || 0));
  if (keys.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "empty";
    td.textContent = "—";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const k of keys) {
    const tr = document.createElement("tr");
    const cells = [
      t(`behavior.${k}`),
      counts[k] != null ? `${counts[k]} ${t("times")}` : "—",
      seconds[k] != null ? fmtSeconds(seconds[k]) : "—",
      longest[k] != null ? fmtSeconds(longest[k]) : "—",
    ];
    for (const c of cells) {
      const td = document.createElement("td");
      td.textContent = c;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function fmtSeconds(sec) {
  sec = Math.round(sec);
  if (sec >= 60) return `${Math.round(sec / 60)} ${t("min")}`;
  return `${sec} ${t("sec")}`;
}

async function downloadShareCard(s, highlights) {
  const btn = document.getElementById("btn-download");
  const prev = btn.textContent;
  try {
    const blob = await buildShareCard(s, highlights);
    const fname = `nunchikochi-${s.date || "session"}.png`;
    downloadBlob(blob, fname);
  } catch {
    btn.textContent = t("tempError");
    setTimeout(() => (btn.textContent = prev), 1500);
  }
}

function copySummary(s, text) {
  const lines = [
    `Nunchikochi — ${s.date || ""}`,
    `${t("reportDuration")}: ${Math.round((s.duration_s || 0) / 60)} ${t("min")}`,
    `${t("reportNudges")}: ${s.nudges_sent ?? 0}  ${t("reportSuppressed")}: ${s.nudges_suppressed ?? 0}`,
    text || "",
  ];
  const payload = lines.join("\n");
  const done = () => {
    const b = document.getElementById("btn-copy");
    b.textContent = t("copied");
    setTimeout(() => (b.textContent = t("copyCard")), 1500);
  };
  if (navigator.clipboard?.writeText) navigator.clipboard.writeText(payload).then(done, done);
  else done();
}

function resetStart() {
  document.getElementById("consent").checked = false;
  document.getElementById("btn-start").disabled = true;
}
function resetMetricsUi() {
  for (const id of ["m-ear", "m-roll", "m-scale"]) {
    const el = document.getElementById(id);
    el.classList.add("na");
    el.classList.remove("skeleton");
    el.querySelector(".value").textContent = "—";
    el.querySelector(".bar > span").style.width = "0%";
  }
  document.getElementById("event-chips").innerHTML = "";
  document.getElementById("quality-banner").classList.remove("show");
}

// Mirror the capture preview source into an on-screen canvas (so one <video>/<canvas> feeds many screens).
function mirrorInto(canvasId) {
  const dst = document.getElementById(canvasId);
  const ctx = dst.getContext("2d");
  const src = state.capture.previewSource();
  const draw = () => {
    if (!document.getElementById(canvasId).isConnected) return;
    try {
      if (state.capture.mock) ctx.drawImage(src, 0, 0, dst.width, dst.height);
      else if (src.videoWidth) ctx.drawImage(src, 0, 0, dst.width, dst.height);
    } catch { /* source not ready */ }
    requestAnimationFrame(draw);
  };
  draw();
}

// ---------- privacy modal ----------
function initPrivacyModal() {
  const modal = document.getElementById("privacy-modal");
  const openBtn = document.getElementById("btn-privacy");
  const closeBtn = document.getElementById("btn-privacy-close");
  const delBtn = document.getElementById("btn-privacy-delete");
  let lastFocus = null;
  const open = () => {
    lastFocus = document.activeElement;
    modal.hidden = false;
    closeBtn.focus();
    document.addEventListener("keydown", onKey);
  };
  const close = () => {
    modal.hidden = true;
    document.removeEventListener("keydown", onKey);
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  };
  const onKey = (e) => {
    if (e.key === "Escape") close();
    if (e.key === "Tab") trapFocus(e, modal);
  };
  openBtn.onclick = open;
  closeBtn.onclick = close;
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  // DELETE endpoint is not in the contract yet — UI-only acknowledgement.
  // TODO(contract): add `DELETE /v1/summary?date=…` (or session) so this actually removes data.
  delBtn.onclick = () => {
    delBtn.textContent = t("copied"); // reuse "Copied/복사됨" as a done tick
    setTimeout(() => (delBtn.textContent = t("privacyDelete")), 1500);
  };
}

function trapFocus(e, container) {
  const focusables = container.querySelectorAll('button, [href], input, [tabindex]:not([tabindex="-1"])');
  if (!focusables.length) return;
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

// ---------- helpers ----------
function clamp01(x) { return Math.max(0, Math.min(1, x)); }

// ---------- language toggle ----------
function initLang() {
  const relang = (lang) => {
    setLang(lang);
    applyI18n();
    // re-render the report in the new language if it's showing
    if (document.getElementById("screen-report").classList.contains("active") && state.lastReport) {
      renderReport(state.lastReport);
    }
    // re-render agent log (action/tool labels are localized)
    if (!document.getElementById("agent-panel").hidden) renderAgentLog();
  };
  document.getElementById("lang-en").addEventListener("click", () => relang("en"));
  document.getElementById("lang-ko").addEventListener("click", () => relang("ko"));
}

// ---------- boot ----------
(async function main() {
  await loadConfig();
  applyI18n();
  initLang();
  initStart();
  initCamError();
  initPrivacyModal();
  // Expose a tiny hook for Playwright/debugging without leaking internals.
  window.__nunchi = {
    get screen() { return document.querySelector(".screen.active")?.id; },
    mock: MOCK,
    demo: DEMO,
    get mode() { return state.mode; },
    // W6: report whether a live key is held in memory and that it is NOT persisted.
    // We return only booleans/length — never the key value itself.
    hasLiveKey: () => liveKey.length > 0,
    liveKeyLen: () => liveKey.length,
    // test helpers: drive error states + inspect agent log (no real failures needed)
    showError: (kind) => showError(kind),
    errorKindFromStatus,
    agentCount: () => state.agentLog.length,
    agentActions: () => state.agentLog.map((r) => r.action),
  };
})();
