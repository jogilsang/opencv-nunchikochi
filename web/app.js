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
import { PostureBuddy, samplePoseAt, describePose, EXAGGERATION } from "./buddy.js";

const params = new URLSearchParams(location.search);
const MOCK = params.get("mock") === "1";
const DEMO = params.get("demo") === "1";
const FAST = params.get("fast") === "1"; // ?demo=1&fast=1 → pre-W13 quick playback (e2e, recording)
const DEV = params.get("dev") === "1";

// Default demo playback runs at realtime speed for this long before looping/stopping, so a
// judge has time to watch the overlay, buddy, agent panel and toasts (W13 defect 4). Fast
// mode skips this and auto-advances as soon as the recorded steps are exhausted.
const DEMO_RUN_SECONDS = 75; // within the brief's 60–90s window

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
  buddy: null,           // PostureBuddy instance (W10)
  reportBuddy: null,     // PostureBuddy on the report screen (rewind replay)
  poseFixture: null,     // loaded synthetic pose series (fallback while vision has no pose)
  poseTimer: null,       // interval feeding fixture poses when the server sends none
  poseTrack: [],         // in-memory pose ring buffer for session rewind (W10 stage ②)
  demoProgressTimer: null, // realtime demo progress ticker (W13 defect 4)
  drinkUntil: 0,         // performance.now() until which the measured drink gesture is active (W14)
  quiet: true,           // W16: quiet mode on by default — alerts off, posture still recorded
  quietNotes: 0,         // count of nudges held back while quiet (shown on the status chip)
  nudgeCooldownUntil: {}, // W16: per-kind cooldown so the same alert can't re-fire rapidly
  lastToastKind: "",     // kind of the toast currently showing (for same-kind merge "+N more")
};

// W16 alert calming: keep at most ONE alert toast on screen; a new alert of the same kind
// while one is showing is merged as "+N more" instead of stacking. Per-kind cooldown stops a
// behaviour from re-nudging for a while (demo-scaled; the real cadence lives in the agent tab).
const NUDGE_COOLDOWN_MS = 8000;      // demo-scale; agent policy enforces the real 20-min cadence
const SAME_KIND_MERGE = true;

// W16 browser storage: ONLY numeric hourly bad-posture rates (no frames, no landmarks, no
// personal info), so a reload still shows the trend. Anonymous: keyed to a random browser id,
// never a login. The user can clear it from the report.
const STORE_KEY = "nunchi.rateHistory.v1";
const STORE_MAX = 20;
function loadRateHistory() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    // keep only {date, per_hour_rate} number pairs — defensive against old/odd shapes
    return arr.filter((x) => x && typeof x.per_hour_rate === "number").slice(-STORE_MAX);
  } catch { return []; }
}
function saveRateEntry(date, rate) {
  if (typeof rate !== "number") return;
  try {
    const arr = loadRateHistory();
    arr.push({ date: date || new Date().toISOString().slice(0, 10), per_hour_rate: rate });
    localStorage.setItem(STORE_KEY, JSON.stringify(arr.slice(-STORE_MAX)));
  } catch { /* storage may be unavailable (private mode) — trend just won't persist */ }
}
function clearRateHistory() { try { localStorage.removeItem(STORE_KEY); } catch {} }

// W17 anonymous browser id: numbers-only continuity without login or PII. A random token in
// localStorage links this browser's daily summaries server-side (sent as X-Anon-Id). We never
// store frames or keys. Clearing wipes the id AND the local rate numbers, and issues a new id.
const ANON_KEY = "nunchi.anonId.v1";
function getAnonId() {
  try {
    let id = localStorage.getItem(ANON_KEY);
    if (!id || !/^[0-9a-f]{32}$/.test(id)) { id = randomHex16(); localStorage.setItem(ANON_KEY, id); }
    return id;
  } catch {
    // storage unavailable (private mode): a per-tab ephemeral id still lets the server link
    // requests within this session, and nothing persists.
    if (!state._ephemeralAnon) state._ephemeralAnon = randomHex16();
    return state._ephemeralAnon;
  }
}
function randomHex16() {
  const a = new Uint8Array(16);
  (globalThis.crypto || {}).getRandomValues ? crypto.getRandomValues(a) : a.forEach((_, i) => (a[i] = Math.floor(Math.random() * 256)));
  return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("");
}
function clearAnonId() { try { localStorage.removeItem(ANON_KEY); } catch {} state._ephemeralAnon = null; }
function clearAllLocalData() { clearRateHistory(); clearAnonId(); }

// Pose rewind ring buffer: browser memory only. Never saved, sent, URL'd, or localStorage'd.
const POSE_TRACK_MAX = 3600;   // ~30 min at 2/s (fixture is ~0.5s; cap bounds memory regardless)

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

// Reveal the persistent demo marker (full-width bottom strip) + the DEMO badge, and reserve
// page space for the strip, so it is always visible but never floats over content. Idempotent.
function showDemoStrip() {
  const c = document.getElementById("demo-corner");
  if (c) c.hidden = false;
  const b = document.getElementById("demo-badge");
  if (b) b.hidden = false;
  document.body.classList.add("has-demo-strip");
}

// Hide the demo marker + badge and release the reserved page space. Used when a mode other
// than demo is chosen so a live session is never labelled as playback (W13 defect 2).
function hideDemoStrip() {
  const c = document.getElementById("demo-corner");
  if (c) c.hidden = true;
  const b = document.getElementById("demo-badge");
  if (b) b.hidden = true;
  document.body.classList.remove("has-demo-strip");
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
  if (DEMO) showDemoStrip();

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
    // Honesty: the "Demo playback — not a real camera" strip + badge belong to demo mode
    // only. Show them when Demo is picked; hide for Live so a real camera session is never
    // mislabelled as playback (W13 defect 2). ?demo deep-link keeps the strip regardless.
    if (mode === "demo") showDemoStrip();
    else if (!DEMO) hideDemoStrip();
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
    const probe = new Api({ apiBase: state.cfg.apiBase, apiKey: liveKey || state.cfg.apiKey, anonId: getAnonId() });
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
    // Loop (realtime pacing) unless fast mode is requested. Fast = one-shot auto-advance.
    state.api = new DemoApi({ loop: !FAST });
    try {
      await state.api.load();
    } catch (e) {
      showDemoLoadError();
      return;
    }
    // badge/corner also show here when demo is picked without the ?demo deep-link
    showDemoStrip();
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

  // Live (real camera + real server) or mock — never demo (the demo branch returned above).
  // Ensure the demo strip/badge are not showing so a real/mock session is never labelled as
  // playback (honesty — W13 defect 2).
  hideDemoStrip();
  state.api = useMock
    ? new MockApi()
    : new Api({ apiBase: state.cfg.apiBase, apiKey: liveKey || state.cfg.apiKey, anonId: getAnonId() });
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

// ---------- posture buddy (W10) ----------
// Loads the synthetic pose fixture once (numbers only). While vision (V10) doesn't yet
// emit FrameResult.overlay.pose, we drive the buddy from this fixture on a timer; when a
// real pose arrives on a frame we use that instead (see handleFrame).
async function loadPoseFixture() {
  if (state.poseFixture) return state.poseFixture;
  try {
    const res = await fetch("assets/pose-fixture.json", { cache: "no-store" });
    if (res.ok) state.poseFixture = await res.json();
  } catch { /* fixture optional; buddy simply stays neutral */ }
  return state.poseFixture;
}

// Record one pose sample into the in-memory rewind buffer (browser memory only).
function recordPose(pose) {
  if (!pose) return;
  const at = (performance.now() - state.startTime) / 1000;
  state.poseTrack.push({
    at,
    yaw: pose.yaw_deg || 0,
    pitch: pose.pitch_deg || 0,
    roll: pose.roll_deg || 0,
    depth: pose.depth == null ? 1 : pose.depth,
    conf: pose.conf == null ? 1 : pose.conf,
  });
  if (state.poseTrack.length > POSE_TRACK_MAX) state.poseTrack.shift();
  // Reveal + refresh the run-screen rewind timeline once a short history exists,
  // regardless of whether poses come from the fixture feed or real frames.
  if (state.poseTrack.length >= 6) {
    const rewindWrap = document.getElementById("buddy-rewind");
    if (rewindWrap && rewindWrap.hidden && document.getElementById("screen-run")?.classList.contains("active")) {
      rewindWrap.hidden = false;
    }
    if (state._refreshRunMarks) state._refreshRunMarks();
  }
}

// Measured drink gesture (W14): a `drink` event opens a short window during which the buddy's
// right arm is raised toward the mouth. The arm itself animates in buddy.js over ~1.5s.
const DRINK_GESTURE_MS = 1600;
function markDrinking() { state.drinkUntil = performance.now() + DRINK_GESTURE_MS; }
function isDrinkingNow() { return performance.now() < state.drinkUntil; }

async function initBuddy() {
  const canvas = document.getElementById("buddy-canvas");
  if (!canvas) return;
  // tear down any previous instance (new session)
  if (state.buddy) { try { state.buddy.dispose(); } catch {} state.buddy = null; }
  const stateEl = document.getElementById("buddy-state");
  const buddy = new PostureBuddy(canvas, {
    t,
    onAria: (text) => {
      const label = fmtTpl(t("buddyAria"), { state: text });
      canvas.setAttribute("aria-label", label);
      if (stateEl) stateEl.textContent = text; // visible text too (not colour-only)
    },
  });
  state.buddy = buddy;
  const is3d = await buddy.init();
  // 2D fallback note (console-error-free either way)
  const note = document.getElementById("buddy-2dnote");
  if (note) note.hidden = !!is3d;

  // controls
  const bind = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  bind("buddy-front", () => buddy.setView(0, 0));
  bind("buddy-side", () => buddy.setView(70, 0));
  bind("buddy-top", () => buddy.setView(0, 60));
  bind("buddy-reset", () => buddy.resetView());
  const ghost = document.getElementById("buddy-ghost");
  if (ghost) { ghost.checked = false; ghost.onchange = () => buddy.setGhost(ghost.checked); }

  // Prime with the fixture so the buddy is alive even before the first pose frame.
  await loadPoseFixture();
  state.rewindScrubbing = false;
  startBuddyFixtureFeed();

  // Run-screen rewind: reveal once we have a few samples; scrub pauses the live feed.
  const rewindWrap = document.getElementById("buddy-rewind");
  const slider = document.getElementById("rewind-slider");
  const marks = document.getElementById("rewind-marks");
  const timeEl = document.getElementById("rewind-time");
  const liveBtn = document.getElementById("rewind-live");
  if (slider) {
    const onLive = (live) => {
      state.rewindScrubbing = !live;
      if (live && !state.usingRealPose) startBuddyFixtureFeed();
    };
    state._refreshRunMarks = bindRewind({
      slider, marks, timeEl, buddy, track: state.poseTrack, liveBtn, onLive,
    });
    if (rewindWrap) rewindWrap.hidden = true;
  }
}

// Drive the buddy from the fixture timeline on a 30fps-ish cadence (the buddy caps render
// at 30fps internally). Stops as soon as a real pose arrives from the server.
function startBuddyFixtureFeed() {
  stopBuddyFixtureFeed();
  if (!state.poseFixture || !state.buddy) return;
  const t0 = performance.now();
  const dur = fixtureDuration(state.poseFixture);
  const unsureEl = document.getElementById("buddy-unsure");
  state.poseTimer = setInterval(() => {
    if (state.usingRealPose || !state.buddy || state.rewindScrubbing) return;
    const elapsed = ((performance.now() - t0) / 1000) % (dur || 1);
    const pose = samplePoseAt(state.poseFixture, elapsed);
    if (!pose) return;
    state.buddy.setPose(pose);
    recordPose(pose);
    if (unsureEl) unsureEl.hidden = !(pose.conf != null && pose.conf < 0.5);
    // reveal + refresh the rewind timeline once we have a short history
    const rewindWrap = document.getElementById("buddy-rewind");
    if (rewindWrap && state.poseTrack.length >= 6) rewindWrap.hidden = false;
    if (state._refreshRunMarks) state._refreshRunMarks();
  }, 120);
}
function stopBuddyFixtureFeed() {
  if (state.poseTimer) { clearInterval(state.poseTimer); state.poseTimer = null; }
}
function fixtureDuration(fx) {
  const s = fx && fx.samples;
  return s && s.length ? s[s.length - 1].t : 0;
}

// ---------- session rewind (W10 stage 2) ----------
// Replays the in-memory pose track (browser memory only). The slider scrubs; "Live" resumes.
// Forward-head spans (depth above threshold) are drawn as warm marks on the timeline.
const FWD_MARK_DEPTH = 1.08; // depth above this = "head forward" span on the timeline

function poseFromTrackAt(track, tSec) {
  if (!track || track.length === 0) return null;
  if (tSec <= track[0].at) return trackToPose(track[0]);
  if (tSec >= track[track.length - 1].at) return trackToPose(track[track.length - 1]);
  for (let i = 1; i < track.length; i++) {
    if (tSec <= track[i].at) {
      const a = track[i - 1], b = track[i];
      const span = b.at - a.at || 1;
      const k = (tSec - a.at) / span;
      const L = (x, y) => x + (y - x) * k;
      return { yaw_deg: L(a.yaw, b.yaw), pitch_deg: L(a.pitch, b.pitch), roll_deg: L(a.roll, b.roll), depth: L(a.depth, b.depth), conf: Math.min(a.conf, b.conf) };
    }
  }
  return trackToPose(track[track.length - 1]);
}
function trackToPose(s) { return { yaw_deg: s.yaw, pitch_deg: s.pitch, roll_deg: s.roll, depth: s.depth, conf: s.conf }; }

function drawRewindMarks(canvas, track) {
  if (!canvas || !track || track.length === 0) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  const t0 = track[0].at, t1 = track[track.length - 1].at;
  const dur = Math.max(0.001, t1 - t0);
  // base track
  ctx.fillStyle = "#2a3850";
  ctx.fillRect(0, H / 2 - 1, W, 2);
  // forward-head spans in warm amber (text label carries meaning too — not colour-only)
  ctx.fillStyle = "#eda354";
  for (const s of track) {
    if (s.depth > FWD_MARK_DEPTH) {
      const x = ((s.at - t0) / dur) * W;
      ctx.fillRect(Math.max(0, x - 1), 0, 3, H);
    }
  }
}

// Wire a timeline slider + marks canvas to a buddy, scrubbing the given track.
function bindRewind({ slider, marks, timeEl, buddy, track, liveBtn, onLive }) {
  if (!slider) return;
  const refresh = () => drawRewindMarks(marks, track);
  refresh();
  const dur = track.length ? (track[track.length - 1].at - track[0].at) : 0;
  const t0 = track.length ? track[0].at : 0;
  const onScrub = () => {
    if (onLive) onLive(false); // entering scrub mode pauses live feed
    const frac = Number(slider.value) / 100;
    const tSec = t0 + frac * dur;
    const pose = poseFromTrackAt(track, tSec);
    if (pose && buddy) buddy.setPose(pose);
    if (timeEl) {
      const label = fmtTpl(t("rewindTimeLabel"), { t: tSec.toFixed(1), state: describePose(pose, t) });
      timeEl.textContent = label;
    }
  };
  slider.oninput = onScrub;
  if (liveBtn && onLive) liveBtn.onclick = () => { onLive(true); slider.value = "100"; };
  return refresh;
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
  initQuietMode();
  renderAgentLog();
  state.poseTrack = [];
  state.usingRealPose = false;
  initBuddy();
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
  initDemoRunControls();
}

// Demo-only run controls (W13 defect 4): a "Skip to report" button and, in default
// (non-fast) demo mode, a realtime progress bar. The demo never auto-advances in default
// mode — it loops until the judge presses Skip or End. Fast mode (?demo=1&fast=1) keeps the
// pre-W13 auto-advance and shows neither control.
function initDemoRunControls() {
  const skip = document.getElementById("btn-skip");
  const prog = document.getElementById("demo-progress");
  const bar = document.getElementById("demo-progress-bar");
  const note = document.getElementById("demo-progress-note");
  stopDemoProgress();
  const isDemo = DEMO || state.mode === "demo";
  const showControls = isDemo && !FAST;
  if (skip) {
    skip.hidden = !showControls;
    if (showControls) skip.onclick = () => { stopDemoProgress(); endSession(); };
  }
  if (!prog || !bar || !note) return;
  prog.hidden = !showControls;
  if (!showControls) return;
  const total = DEMO_RUN_SECONDS;
  const t0 = performance.now();
  bar.style.width = "0%";
  note.textContent = fmtTpl(t("demoProgress"), { elapsed: 0, total });
  state.demoProgressTimer = setInterval(() => {
    if (!document.getElementById("screen-run")?.classList.contains("active")) { stopDemoProgress(); return; }
    const elapsed = (performance.now() - t0) / 1000;
    const frac = Math.min(1, elapsed / total);
    bar.style.width = `${Math.round(frac * 100)}%`;
    if (elapsed >= total) {
      note.textContent = t("demoProgressLoop"); // playback keeps looping; judge ends it
    } else {
      note.textContent = fmtTpl(t("demoProgress"), { elapsed: Math.round(elapsed), total });
    }
  }, 500);
}
function stopDemoProgress() {
  if (state.demoProgressTimer) { clearInterval(state.demoProgressTimer); state.demoProgressTimer = null; }
}

// ---------- quiet mode (W16) ----------
// Default ON: no toasts — just a calm status chip + the recorded count. Posture keeps being
// recorded either way (agent panel + report are unaffected). Turning it off opts into gentle
// nudge toasts. No sound and no flashing in either mode.
function initQuietMode() {
  const toggle = document.getElementById("quiet-toggle");
  const chip = document.getElementById("quiet-chip");
  if (!toggle || !chip) return;
  state.quietNotes = 0;
  toggle.checked = state.quiet;
  const apply = () => {
    state.quiet = toggle.checked;
    if (state.quiet) clearToasts(); // leaving loud→quiet removes any standing toasts
    updateQuietChip();
  };
  toggle.onchange = apply;
  updateQuietChip();
}

function updateQuietChip() {
  const chip = document.getElementById("quiet-chip");
  if (!chip) return;
  chip.hidden = !state.quiet;
  if (!state.quiet) { chip.textContent = ""; return; }
  if (state.quietNotes > 0) {
    chip.textContent = fmtTpl(t("quietChipNudge"), { n: state.quietNotes });
    chip.classList.add("has-notes");
  } else {
    chip.textContent = t("quietChipWatching");
    chip.classList.remove("has-notes");
  }
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
  // posture buddy drink gesture (W14): the `drink` behaviour (palm-near-mouth) is a MEASURED
  // event. When it appears, raise the buddy's right arm toward the mouth for the gesture, then
  // let it fall. Works for both the real-pose path and the fixture feed.
  const drinking = Array.isArray(result.events) && result.events.some((e) => e && e.type === "drink");
  if (drinking) markDrinking();
  // overlay: server may omit it (null) -> draw nothing
  state.lastOverlay = result.overlay || null;
  const canvas = document.getElementById("run-overlay");
  if (state.overlayOn) drawOverlay(canvas, state.lastOverlay);
  else clearOverlay(canvas);
  // posture buddy (W10/W14): if the server sent a real pose, drive the buddy from it and stop
  // the fixture feed. Numbers only — overlay.pose is {yaw,pitch,roll,depth,conf}. The measured
  // drink event (above) is merged in so the arm raises.
  const realPose = result.overlay && result.overlay.pose;
  if (realPose && state.buddy) {
    state.usingRealPose = true;
    stopBuddyFixtureFeed();
    const posed = { ...realPose, drinking: isDrinkingNow() };
    state.buddy.setPose(posed);
    recordPose(posed);
    const unsureEl = document.getElementById("buddy-unsure");
    if (unsureEl) unsureEl.hidden = !(realPose.conf != null && realPose.conf < 0.5);
  }
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
    // Human-in-the-loop question always needs an answer — even in quiet mode. It still
    // never stacks (state.confirmOpen guards a single prompt).
    showConfirm(d);
  } else if (d.action === "nudge" || d.action === "request_recalibration") {
    // W16: a nudge is a soft alert. In quiet mode we don't toast — we just count it for the
    // status chip and the report. Otherwise, a per-kind cooldown + single-toast merge keeps
    // alerts from piling up or re-firing rapidly.
    const kind = d.action === "request_recalibration" ? "recalibration" : (d.reason || "nudge");
    if (state.quiet) {
      state.quietNotes += 1;
      updateQuietChip();
      return;
    }
    const now = performance.now();
    const until = state.nudgeCooldownUntil[kind] || 0;
    if (now < until) {
      // same behaviour still in cooldown: merge into the showing toast as "+N more"
      if (SAME_KIND_MERGE) bumpToastMore(kind);
      return;
    }
    state.nudgeCooldownUntil[kind] = now + NUDGE_COOLDOWN_MS;
    showNudge(d, kind);
  }
}

// Add/increment a "+N more" tag on the currently showing nudge toast of this kind, so repeated
// same-kind alerts during cooldown don't stack as separate toasts (W16 calming).
function bumpToastMore(kind) {
  const host = document.getElementById("toast-host");
  if (!host) return;
  const toast = host.querySelector(`.toast[data-kind="${cssEscape(kind)}"]:not(.confirm)`)
    || host.querySelector(".toast:not(.confirm)");
  if (!toast) return;
  const n = (Number(toast.dataset.more) || 0) + 1;
  toast.dataset.more = String(n);
  let tag = toast.querySelector(".more");
  if (!tag) { tag = document.createElement("span"); tag.className = "more"; toast.querySelector(".msg")?.appendChild(tag); }
  tag.textContent = " " + fmtTpl(t("toastMore"), { n });
}
function cssEscape(s) { return String(s).replace(/["\\]/g, "\\$&"); }

function msgFor(d) {
  return getLang() === "ko" && d.message_ko ? d.message_ko : (d.message || "");
}

function showNudge(d, kind = "nudge") {
  const toast = toastEl(msgFor(d), false);
  toast.dataset.kind = kind;
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

// W16: the alert queue is limited to a single nudge toast — a new nudge evicts any older
// nudge rather than stacking (same-kind repeats merge as "+N more" before reaching here).
// A human-in-the-loop confirm is a separate prompt (guarded by state.confirmOpen) and is
// never silently removed by this cap.
const MAX_NUDGE_TOASTS = 1;
function toastEl(message, isConfirm) {
  const host = document.getElementById("toast-host");
  const toast = document.createElement("div");
  toast.className = "toast" + (isConfirm ? " confirm" : "");
  const p = document.createElement("p");
  p.className = "msg";
  p.textContent = message;
  toast.appendChild(p);
  host.appendChild(toast);
  // Cap the number of *nudge* (non-confirm) toasts. Evict the oldest nudges first; a confirm
  // prompt is left alone so a question to the user is never dropped.
  if (!isConfirm) {
    let nudges = host.querySelectorAll(".toast:not(.confirm)");
    while (nudges.length > MAX_NUDGE_TOASTS) {
      const victim = nudges[0];
      if (!victim || victim === toast) break;
      victim.remove();
      nudges = host.querySelectorAll(".toast:not(.confirm)");
    }
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
  stopBuddyFixtureFeed();
  stopDemoProgress();
  let data;
  try {
    data = await state.api.endSession(state.sessionId);
  } catch {
    // Build a minimal recoverable report so the demo never dead-ends.
    data = { summary: { duration_s: (performance.now() - state.startTime) / 1000, nudges_sent: 0, nudges_suppressed: 0, confirmations_asked: 0, counts: {} }, report: { text_en: "", text_ko: "" } };
  }
  // comparison needs today's + recent summaries (GET /v1/summary). Non-fatal.
  // Real contract: /end carries report.trend; GET /v1/summary carries history (oldest-first).
  let previous = null, history = null, example = false;
  const trend = (data.report && data.report.trend) || null;
  try {
    const date = (data.summary && data.summary.date) || new Date().toISOString().slice(0, 10);
    const sum = await state.api.getSummary(date);
    if (sum && sum.previous) previous = sum.previous;
    if (sum && Array.isArray(sum.history)) history = sum.history;
    example = !!(sum && sum.example);
  } catch { /* comparison is optional */ }
  state.capture.stop();
  clearToasts();
  state.lastReport = { summary: data.summary || {}, report: data.report || {}, previous, history, trend, example };
  renderReport(state.lastReport);
  show("screen-report");
}

// Build the report-screen rewind buddy from the captured pose track (memory only).
// Hidden if no poses were captured. Starts paused at the first sample; slider scrubs.
async function initReportBuddy() {
  const wrap = document.getElementById("report-buddy-wrap");
  const canvas = document.getElementById("report-buddy-canvas");
  if (!wrap || !canvas) return;
  const track = state.poseTrack.slice();
  if (state.reportBuddy) { try { state.reportBuddy.dispose(); } catch {} state.reportBuddy = null; }
  if (track.length < 2) { wrap.hidden = true; return; }
  wrap.hidden = false;
  const buddy = new PostureBuddy(canvas, { t });
  state.reportBuddy = buddy;
  await buddy.init();
  // start paused on the first frame (don't animate a live feed here)
  buddy.setPose(trackToPose(track[0]));
  const slider = document.getElementById("report-rewind-slider");
  const marks = document.getElementById("report-rewind-marks");
  const timeEl = document.getElementById("report-rewind-time");
  if (slider) {
    slider.value = "0";
    bindRewind({ slider, marks, timeEl, buddy, track, liveBtn: null, onLive: null });
    // prime the time label at t0
    slider.dispatchEvent(new Event("input"));
  }
}

function renderReport({ summary: s, report: rep, previous, history, trend, example }) {
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

  // W16: posture record timeline (bad-posture per 5/10/30/60-min slice)
  renderTimeline(s.timeline, s.duration_s);
  // W16/W17: persist this session's hourly rate once per report (real mode only; demo is
  // sample data and must not touch storage), then render the earlier-session comparison using
  // the server-provided trend (report.trend) and history (oldest-first).
  const thisRate = s.timeline && s.timeline.per_hour_rate;
  if (!example && typeof thisRate === "number") saveRateEntry(s.date, thisRate);
  renderHistory({ summary: s, history, trend, example });

  // posture buddy rewind replay (W10 stage 2) — built from the in-memory pose track
  initReportBuddy();

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

// ---------- W16: posture-record timeline ----------
// Bad-posture counts per 5/10/30/60-min slice (provisional A11 contract). Tabs switch the
// slice; a bar chart (orange = bad posture) shows per-slice counts with an accessible alt
// text + a "show as table" fallback. Short sessions show a gentle "not enough data" note.
const TL_UNITS = [
  { key: "5m", label: "tl5m" }, { key: "10m", label: "tl10m" },
  { key: "30m", label: "tl30m" }, { key: "60m", label: "tl60m" },
];
function renderTimeline(timeline, durationS) {
  const card = document.getElementById("report-timeline");
  if (!card) return;
  const bad = (timeline && timeline.bad_posture) || {};
  const rate = timeline && timeline.per_hour_rate;
  const rateEl = document.getElementById("tl-rate");
  // Total bad-posture events this session (sum the finest slice we have, 5m).
  const totalEvents = (Array.isArray(bad["5m"]) ? bad["5m"] : [])
    .reduce((a, s) => a + (s && s.events || 0), 0);
  const mins = Math.max(0, Math.round((durationS || 0) / 60));
  if (rateEl) {
    if (typeof rate === "number") {
      rateEl.textContent = fmtTpl(t("timelineRate"), { n: rate });
    } else if (totalEvents > 0) {
      // W19: hourly rate withheld under 10 min (not statistically meaningful) but the raw
      // count IS shown so a short, hands-on session never looks empty.
      rateEl.textContent = fmtTpl(t("timelineShortCount"), { min: mins, events: totalEvents });
    } else {
      rateEl.textContent = t("timelineNoEvents");
    }
  }

  const tabs = Array.from(card.querySelectorAll(".tl-tab"));
  let unit = card.dataset.unit || "5m";
  if (!bad[unit]) unit = TL_UNITS.find((u) => bad[u.key])?.key || "5m";

  const draw = () => {
    card.dataset.unit = unit;
    for (const b of tabs) b.setAttribute("aria-selected", String(b.dataset.unit === unit));
    const slices = Array.isArray(bad[unit]) ? bad[unit] : [];
    drawTimelineChart(unit, slices);
    drawTimelineTable(unit, slices);
  };
  for (const b of tabs) b.onclick = () => { unit = b.dataset.unit; draw(); };

  // table toggle
  const tgl = document.getElementById("tl-toggle-view");
  const tableWrap = document.getElementById("tl-table-wrap");
  const chart = document.getElementById("tl-chart");
  if (tgl && tableWrap && chart) {
    const setTableShown = (show) => {
      tableWrap.hidden = !show;
      chart.hidden = show;
      tgl.setAttribute("aria-pressed", String(show));
      tgl.textContent = show ? t("timelineChart") : t("timelineTable");
    };
    setTableShown(false);
    tgl.onclick = () => setTableShown(tableWrap.hidden);
  }
  draw();
}

function sliceLabel(unit, i) {
  const stepMin = { "5m": 5, "10m": 10, "30m": 30, "60m": 60 }[unit] || 5;
  const from = i * stepMin, to = (i + 1) * stepMin;
  return fmtTpl(t("timelineSliceLabel"), { from, to });
}

function drawTimelineChart(unit, slices) {
  const chart = document.getElementById("tl-chart");
  const short = document.getElementById("tl-short");
  if (!chart) return;
  chart.innerHTML = "";
  // No bars to draw (single slice with zero events). Collapse the empty bar area; the summary
  // line above already states "No bad posture detected this session" (W19), so the extra
  // "not enough data" note would be redundant — keep it hidden.
  const totalEvents = slices.reduce((a, b) => a + (b.events || 0), 0);
  if (slices.length <= 1 && totalEvents === 0) {
    if (short) short.hidden = true;
    chart.setAttribute("aria-label", t("timelineNoEvents"));
    chart.hidden = true;
    return;
  }
  if (short) short.hidden = true;
  chart.hidden = false;
  const max = Math.max(1, ...slices.map((s) => s.events || 0));
  const unitLabel = t(TL_UNITS.find((u) => u.key === unit)?.label || "tl5m");
  const altParts = [fmtTpl(t("timelineAltIntro"), { unit: unitLabel })];
  for (let i = 0; i < slices.length; i++) {
    const n = slices[i].events || 0;
    const label = sliceLabel(unit, i);
    const col = document.createElement("div");
    col.className = "tl-bar";
    const fill = document.createElement("div");
    fill.className = "bar-fill";
    fill.style.height = `${Math.round((n / max) * 96) + 2}px`;
    const num = document.createElement("div"); num.className = "bar-n"; num.textContent = String(n);
    const xlab = document.createElement("div"); xlab.className = "bar-x"; xlab.textContent = label;
    col.append(num, fill, xlab);
    col.setAttribute("aria-hidden", "true"); // the chart's aria-label carries the full reading
    chart.appendChild(col);
    altParts.push(fmtTpl(t("timelineBarAria"), { label, n }));
  }
  chart.setAttribute("aria-label", altParts.join(" "));
}

function drawTimelineTable(unit, slices) {
  const tbody = document.querySelector("#tl-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  for (let i = 0; i < slices.length; i++) {
    const tr = document.createElement("tr");
    const td1 = document.createElement("td"); td1.textContent = sliceLabel(unit, i);
    const td2 = document.createElement("td"); td2.textContent = String(slices[i].events || 0);
    tr.append(td1, td2);
    tbody.appendChild(tr);
  }
}

// ---------- W16/W17: compared-with-earlier-sessions ----------
// Shows the per-hour bad-posture rate across recent sessions as a small bar chart, with the
// server's observational trend sentence (report.trend.line_en/ko). `history` is the real
// GET /v1/summary history (oldest-first, each carrying timeline.per_hour_rate + date). In real
// mode the server is the source of truth; local stored numbers are only a fallback when the
// server returns no history. In demo mode we show the sample history under an "Example data"
// label (never passed off as real) and never touch localStorage.
function renderHistory({ summary, history, trend, example }) {
  const card = document.getElementById("report-history");
  const chart = document.getElementById("history-chart");
  const trendEl = document.getElementById("history-trend");
  const noneEl = document.getElementById("history-none");
  const badge = document.getElementById("history-example");
  const exNote = document.getElementById("history-example-note");
  const storedRow = document.getElementById("report-stored");
  if (!card || !chart) return;

  const thisRate = summary && summary.timeline && summary.timeline.per_hour_rate;
  const rateOf = (h) => (h && h.timeline && typeof h.timeline.per_hour_rate === "number") ? h.timeline.per_hour_rate : (typeof h?.per_hour_rate === "number" ? h.per_hour_rate : null);
  const isExample = !!example;

  // earlier sessions (oldest-first). Server history wins; otherwise fall back to local stored
  // numbers (real mode only — demo must not read/write storage).
  let earlier = Array.isArray(history) ? history.map((h) => ({ date: h.date, rate: rateOf(h) })).filter((h) => h.rate != null) : [];
  let usingLocalFallback = false;
  if (!isExample && earlier.length === 0) {
    const stored = loadRateHistory();
    // the last stored entry is this session (just saved) — earlier = all but the last
    earlier = stored.slice(0, -1).map((h) => ({ date: h.date, rate: h.per_hour_rate }));
    usingLocalFallback = earlier.length > 0;
  }
  // newest bar = this session
  const series = earlier.slice(-4).map((h) => ({ date: h.date, rate: h.rate, isThis: false }));
  if (typeof thisRate === "number") series.push({ date: summary.date, rate: thisRate, isThis: true });

  if (badge) badge.hidden = !isExample;
  if (exNote) exNote.hidden = !isExample;
  // stored-numbers row + clear button (real mode only, when something is actually stored)
  if (storedRow) {
    const hasStored = !isExample && loadRateHistory().length > 0;
    storedRow.hidden = !hasStored;
    const clearBtn = document.getElementById("btn-clear-stored");
    if (clearBtn) clearBtn.onclick = () => {
      clearAllLocalData(); // wipe stored numbers AND the anon id (a fresh id is issued on next request)
      clearBtn.textContent = t("storedCleared");
      setTimeout(() => (clearBtn.textContent = t("storedClear")), 1500);
      renderHistory({ summary, history, trend, example }); // re-render with nothing stored
    };
  }

  // Bars we can actually draw (any series point that has a numeric rate). This session is a
  // bar only when its rate is known (>=10 min); a short session contributes no bar and we must
  // not fabricate a value for it (W19).
  const rated = series.filter((p) => typeof p.rate === "number");
  const earlierRated = rated.filter((p) => !p.isThis);
  const thisKnown = typeof thisRate === "number";

  // Nothing to show at all → first-record guidance (no earlier rates on record).
  if (earlierRated.length === 0 && !thisKnown) {
    chart.innerHTML = "";
    chart.hidden = true;
    chart.setAttribute("aria-label", t("historyNone"));
    if (noneEl) { noneEl.hidden = false; noneEl.textContent = t("historyNone"); }
    if (trendEl) trendEl.textContent = (trend && (trend.line_en || trend.line_ko)) ? trendLine(trend) : "";
    return;
  }
  // A single known point (only this session, no earlier) also can't form a trend yet.
  if (rated.length < 2 && thisKnown && earlierRated.length === 0) {
    chart.innerHTML = "";
    chart.hidden = true;
    chart.setAttribute("aria-label", t("historyNone"));
    if (noneEl) { noneEl.hidden = false; noneEl.textContent = t("historyNone"); }
    if (trendEl) trendEl.textContent = (trend && (trend.line_en || trend.line_ko)) ? trendLine(trend) : "";
    return;
  }
  if (noneEl) noneEl.hidden = true;
  chart.hidden = false;

  // trend sentence:
  // - this session too short (rate null) but earlier records exist → say so, show earlier bars.
  // - otherwise prefer the server's ready-made localized line, else derive from direction.
  if (trendEl) {
    if (!thisKnown && earlierRated.length >= 1) {
      trendEl.textContent = t("historyShortThis");
    } else if (trend && (trend.line_en || trend.line_ko)) {
      trendEl.textContent = trendLine(trend);
    } else {
      trendEl.textContent = t(`trend${cap((trend && trend.direction) || localTrend(rated.map((p) => p.rate)))}`) || "";
    }
  }

  // bar chart
  chart.innerHTML = "";
  const max = Math.max(1, ...rated.map((p) => p.rate));
  const altParts = [];
  for (const p of series) {
    const n = typeof p.rate === "number" ? p.rate : 0;
    const col = document.createElement("div");
    col.className = "tl-bar" + (p.isThis ? " is-this" : "");
    const fill = document.createElement("div"); fill.className = "bar-fill";
    fill.style.height = `${Math.round((n / max) * 96) + 2}px`;
    const num = document.createElement("div"); num.className = "bar-n"; num.textContent = String(n);
    const xlab = document.createElement("div"); xlab.className = "bar-x";
    xlab.textContent = p.isThis ? t("historyThis") : shortDate(p.date);
    col.append(num, fill, xlab);
    col.setAttribute("aria-hidden", "true");
    chart.appendChild(col);
    altParts.push(fmtTpl(t("historyBarAria"), { date: p.isThis ? t("historyThis") : shortDate(p.date), n }));
  }
  const lead = (trendEl && trendEl.textContent) ? trendEl.textContent + " " : "";
  chart.setAttribute("aria-label", lead + altParts.join(" "));
}

// Server trend carries ready EN/KO sentences; pick the active language.
function trendLine(trend) {
  if (!trend) return "";
  return getLang() === "ko" ? (trend.line_ko || trend.line_en || "") : (trend.line_en || trend.line_ko || "");
}

function localTrend(rates) {
  if (rates.length < 2) return "same";
  const latest = rates[rates.length - 1];
  const earlier = rates.slice(0, -1);
  const mean = earlier.reduce((a, b) => a + b, 0) / earlier.length;
  const rel = mean ? (latest - mean) / mean : 0;
  if (rel <= -0.1) return "improving";
  if (rel >= 0.1) return "worsening";
  return "same";
}
function cap(s) { return String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1); }
function shortDate(d) { const s = String(d || ""); return s.length >= 10 ? s.slice(5) : s; }

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
  // tear down buddies so a new session starts clean (frees WebGL contexts)
  if (state.reportBuddy) { try { state.reportBuddy.dispose(); } catch {} state.reportBuddy = null; }
  if (state.buddy) { try { state.buddy.dispose(); } catch {} state.buddy = null; }
  state.poseTrack = [];
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
    fast: FAST,
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
    // W10 posture buddy: report mode + a describable state, never image/landmark data.
    buddyReady: () => !!state.buddy,
    buddyIs3D: () => !!(state.buddy && state.buddy.mode3d),
    buddyExaggeration: () => EXAGGERATION,
    buddyState: () => (state.buddy ? describePose(state.buddy._lastPose, t) : ""),
    // W14: report the figure's parts (head/neck/shoulders/arms/…), triangle budget, and the
    // smoothed right-arm raise (0..1) so tests can see the drink gesture move the arm.
    buddyParts: () => (state.buddy ? state.buddy.parts() : []),
    buddyTriangles: () => (state.buddy ? (state.buddy.triangleCount || 0) : 0),
    buddyArmRaise: () => (state.buddy ? Number((state.buddy.shown?.rightArmRaise ?? 0).toFixed(3)) : 0),
    buddyTorsoLean: () => (state.buddy ? Number((state.buddy.shown?.torsoLean ?? 0).toFixed(3)) : 0),
    setBuddyDrinking: (on) => { if (on) markDrinking(); else state.drinkUntil = 0; if (state.buddy) state.buddy.setDrinking(!!on); },
    forceBuddyArmRaise: (v) => { if (state.buddy) state.buddy.forceArmRaise(v); },
    poseTrackLen: () => state.poseTrack.length,
    reportBuddyReady: () => !!state.reportBuddy,
    rewindScrub: (frac) => {
      const sl = document.getElementById("report-rewind-slider");
      if (sl) { sl.value = String(Math.round(Math.max(0, Math.min(1, frac)) * 100)); sl.dispatchEvent(new Event("input")); }
    },
    rewindState: () => (state.reportBuddy ? describePose(state.reportBuddy._lastPose, t) : ""),
    setBuddyPose: (p) => { if (state.buddy) { state.usingRealPose = true; stopBuddyFixtureFeed(); state.buddy.setPose(p); recordPose(p); const u = document.getElementById("buddy-unsure"); if (u) u.hidden = !(p && p.conf != null && p.conf < 0.5); } },
    buddySetView: (az, el) => { if (state.buddy) state.buddy.setView(az, el); },
    // W16 test hooks: quiet mode + alert queue + report cards (numbers/labels only).
    isQuiet: () => state.quiet,
    quietNotes: () => state.quietNotes,
    setQuiet: (on) => { const el = document.getElementById("quiet-toggle"); if (el) { el.checked = !!on; el.dispatchEvent(new Event("change")); } },
    toastCount: () => document.querySelectorAll("#toast-host .toast").length,
    nudgeToastCount: () => document.querySelectorAll("#toast-host .toast:not(.confirm)").length,
    feedDecision: (d, tSec = 0) => { recordAgentDecision(d, tSec); if (d && d.action && d.action !== "none") handleDecision(d); },
    timelineUnit: () => document.getElementById("report-timeline")?.dataset.unit || "",
    setTimelineUnit: (u) => { const b = document.querySelector(`.tl-tab[data-unit="${u}"]`); if (b) b.click(); },
    timelineBarCount: () => document.querySelectorAll("#tl-chart .tl-bar").length,
    historyTrend: () => (document.getElementById("history-trend")?.textContent || "").trim(),
    historyExampleShown: () => !document.getElementById("history-example")?.hidden,
    storedRateCount: () => loadRateHistory().length,
    clearStored: () => clearAllLocalData(),
    // W17 anon-id hooks: report the id + whether the live Api will send X-Anon-Id (value only,
    // never a frame/key). Used by e2e to prove the header is sent and clearing re-issues an id.
    anonId: () => { try { return localStorage.getItem(ANON_KEY) || ""; } catch { return state._ephemeralAnon || ""; } },
    apiAnonId: () => (state.api && state.api.anonId) || "",
    ensureAnonId: () => getAnonId(),
    // W19 test hook: render the report screen from a crafted payload (short session / events-0
    // / earlier-only). Lets e2e exercise the short-session paths without a real 10-min session.
    renderReportWith: (data) => { show("screen-report"); state.lastReport = data; renderReport(data); },
    timelineRate: () => (document.getElementById("tl-rate")?.textContent || "").trim(),
    historyBarCount: () => document.querySelectorAll("#history-chart .tl-bar").length,
    historyNoneShown: () => !document.getElementById("history-none")?.hidden,
  };
})();
