"""HTTP service (CONTRACTS §3). OWNER: cloud tab. FastAPI + Mangum (Lambda arm64).

Privacy invariants (docs/RULES.md, ARCHITECTURE "개인정보"):
- A frame's JPEG bytes live only inside the request handler's local scope. They are
  decoded, handed to vision in-memory, and dropped. Never written to disk/S3/logs,
  never put in an exception message, never stored in session state.
- Only aggregate SessionSummary is persisted (DynamoDB), plus opaque session STATE (TTL 24h).
- Api key / headers are never logged.

Run locally:  uv run uvicorn nunchi.service.app:app
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

from fastapi import FastAPI, Form, Header, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from nunchi.contracts import SCHEMA_VERSION, FrameResult, SessionSummary

from . import metrics as _metrics
from .deps import get_services
from .state import make_state_store
from .summary_store import make_summary_store

# --- limits / config (CONTRACTS §3) ---------------------------------------
MAX_FRAME_BYTES = 200 * 1024            # request size cap: 200 KB (CONTRACTS §3 hard contract)
ALLOWED_FRAME_MIME = {"image/jpeg", "image/jpg", "application/octet-stream"}
T_MIN, T_MAX = 0.0, 24 * 60 * 60.0      # session-relative seconds, bounded to a day
# Server-side per-session frame-rate limit (abuse defense). Contract recommends <=2 fps
# (CONTRACTS §4); we allow a small burst then enforce a minimum spacing. Wall-clock based,
# independent of the client-supplied `t`, so a client cannot spoof it.
MAX_FRAMES_PER_WINDOW = int(os.environ.get("NUNCHI_RATE_MAX", "6"))   # frames ...
RATE_WINDOW_S = float(os.environ.get("NUNCHI_RATE_WINDOW_S", "1.0"))  # ... per this window
TRACE_MAX_PER_SESSION = int(os.environ.get("NUNCHI_TRACE_MAX", "5000"))  # bounded trace buffer
BUILD_SHA = os.environ.get("NUNCHI_BUILD_SHA", "dev")


_API_KEY_CACHE: dict[str, str | None] = {}


def _api_key_required() -> str | None:
    """Resolve the required X-Api-Key.

    Order: NUNCHI_API_KEY (direct value, local/dev/tests) wins; otherwise
    NUNCHI_API_KEY_PARAM names an SSM SecureString read once and cached (deploy path).
    Unset in both -> None (auth skipped; local only). The key value is never logged.
    """
    direct = os.environ.get("NUNCHI_API_KEY")
    if direct:
        return direct
    param = os.environ.get("NUNCHI_API_KEY_PARAM")
    if not param:
        return None
    if param in _API_KEY_CACHE:
        return _API_KEY_CACHE[param]
    value: str | None = None
    try:
        import boto3  # Lambda runtime provides boto3; local dev rarely uses the SSM path

        ssm = boto3.client("ssm")
        value = ssm.get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"] or None
    except Exception:  # noqa: BLE001 - if SSM is unreachable, fail closed below (no key resolved)
        value = None
    _API_KEY_CACHE[param] = value
    return value


def _error(code: str, message: str, status: int) -> JSONResponse:
    # Stable error-code contract. Never echoes frame bytes or secrets. Emits an EMF
    # Errors metric (code only, never the message/body).
    _metrics.error(code)
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _rate_limited(state: dict[str, Any], now: float) -> bool:
    """Server-side per-session frame-rate limit. Sliding window on wall-clock timestamps
    kept in the session state (numbers only, no frames). Mutates state in place; returns
    True when the caller is over the limit. Limits read from env at call time so they are
    tunable (and testable) without reimport."""
    max_frames = int(os.environ.get("NUNCHI_RATE_MAX", str(MAX_FRAMES_PER_WINDOW)))
    window_s = float(os.environ.get("NUNCHI_RATE_WINDOW_S", str(RATE_WINDOW_S)))
    window = [ts for ts in state.get("frame_ts", []) if now - ts < window_s]
    if len(window) >= max_frames:
        state["frame_ts"] = window  # keep the window pruned
        return True
    window.append(now)
    state["frame_ts"] = window
    return False


def create_app() -> FastAPI:
    app = FastAPI(title="nunchikochi-service", version=SCHEMA_VERSION)

    origins_env = os.environ.get("NUNCHI_CORS_ORIGINS", "")
    origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"] if not origins_env else origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["X-Api-Key", "X-Anon-Id", "Content-Type"],
    )

    store = make_state_store()
    summary_store = make_summary_store()
    svc = get_services()

    # In-process trace & summary buffers (demo scope; CONTRACTS §4 persists summary to DynamoDB in C2+).
    traces: dict[str, list[dict[str, Any]]] = {}
    summaries: dict[str, SessionSummary] = {}
    by_date: dict[str, SessionSummary] = {}

    def _check_key(x_api_key: str | None) -> JSONResponse | None:
        required = _api_key_required()
        if required is None:
            # Fail closed when an SSM key was expected but could not be resolved.
            if os.environ.get("NUNCHI_API_KEY_PARAM") and not os.environ.get("NUNCHI_API_KEY"):
                return _error("auth_unavailable", "api key not resolved", 503)
            return None  # local/dev: no key configured, auth skipped
        if x_api_key != required:
            return _error("unauthorized", "missing or invalid api key", 401)
        return None

    # --- 1. health -------------------------------------------------------
    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        vision = svc.vision
        return {
            "ok": True,
            "cv_version": getattr(vision, "cv_version", ""),
            "backend": getattr(vision, "backend", "opencv"),
            "arch": os.uname().machine,
            "build": BUILD_SHA,
            "stubs": svc.using_stubs,
        }

    # --- 2. create session ----------------------------------------------
    @app.post("/v1/sessions")
    def create_session(
        payload: dict[str, Any],
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    ):
        if (err := _check_key(x_api_key)) is not None:
            return err
        lang = payload.get("lang", "en")
        if lang not in ("en", "ko"):
            return _error("bad_request", "lang must be 'en' or 'ko'", 422)
        client_date = str(payload.get("client_date", ""))
        session_id = f"s-{int(time.time()*1000):x}-{os.urandom(3).hex()}"
        new_state = svc.vision.new_session(session_id)
        state: dict[str, Any] = {
            "vision": _to_jsonable(new_state),
            "agent_ctx": _new_agent_ctx(svc, session_id, lang),
            "date": client_date,
            "started": time.time(),
            "counts": {},
            "seconds": {},
            "longest": {},
            "nudges_sent": 0,
            "nudges_suppressed": 0,
            "confirmations_asked": 0,
            "recalibrations": 0,
            "frame_ts": [],
            # A11 timeline source: a SummaryAccumulator folded alongside the plain
            # aggregates above, stored as numbers-only JSON (see _acc_dump/_acc_load).
            "acc": _acc_dump(_new_accumulator(session_id, client_date)),
        }
        store.put(session_id, state)
        traces[session_id] = []
        _metrics.session_event("create")
        instruction = (
            "Face the camera and sit naturally for 5 seconds."
            if lang == "en"
            else "카메라를 바라보고 5초 동안 자연스럽게 앉아 주세요."
        )
        return {"session_id": session_id, "calibration": {"seconds": 5, "instruction": instruction}}

    # --- 3. frame --------------------------------------------------------
    @app.post("/v1/frames")
    async def post_frame(
        session_id: str = Form(...),
        t: float = Form(...),
        frame: UploadFile = Form(...),  # noqa: B008
        phase: str = Form(default="run"),
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    ):
        if (err := _check_key(x_api_key)) is not None:
            return err
        if phase not in ("calibrate", "run"):
            return _error("bad_request", "phase must be 'calibrate' or 'run'", 422)
        if not (T_MIN <= t <= T_MAX):
            return _error("bad_request", "t out of range", 422)
        if frame.content_type and frame.content_type not in ALLOWED_FRAME_MIME:
            return _error("unsupported_media", f"frame mime not allowed: {frame.content_type}", 415)

        # Read frame bytes into a LOCAL variable only. Enforce size cap before any session work.
        # Bytes are never stored; dropped in the finally block below.
        raw = await frame.read()
        if len(raw) > MAX_FRAME_BYTES:
            del raw
            return _error("payload_too_large", "frame exceeds 200KB", 413)
        if len(raw) == 0:
            del raw
            return _error("bad_request", "empty frame", 422)

        state = store.get(session_id)
        if state is None:
            del raw
            return _error("session_not_found", "unknown or expired session", 404)

        # Server-side frame-rate limit (abuse defense): wall-clock, per session. 429 and
        # a metric only; the frame bytes are dropped and never analysed or stored.
        if _rate_limited(state, time.time()):
            del raw
            store.put(session_id, state)  # persist the pruned window
            _metrics.rate_limited()
            return _error("rate_limited", "too many frames; slow down (<=2 fps)", 429)

        # Restore vision session state via the official serializer. A restore failure is
        # an explicit 410 (bilingual), never a silent fresh start (MISMATCH-1 fix).
        try:
            vision_state = _hydrate_vision_state(svc, state["vision"])
        except _StateInvalid:
            del raw
            return _error(
                "session_state_invalid",
                "session state could not be restored (version mismatch or corrupt) / "
                "세션 상태를 복원할 수 없습니다 (버전 불일치 또는 손상)",
                410,
            )
        try:
            result, vision_state = _run_vision(svc, vision_state, raw, t, phase)
        except Exception:  # noqa: BLE001 - must not leak frame bytes; convert any failure to a generic 500
            # Do not leak frame bytes in the error. Generic message only.
            return _error("vision_error", "frame analysis failed", 500)
        finally:
            del raw  # drop bytes promptly; GC owns the rest

        # Serialize + persist. Refuse to store a state over the 8KB cap.
        try:
            state["vision"] = _to_jsonable(vision_state)
        except _StateTooLarge:
            return _error("session_state_too_large", "session state exceeds 8KB; save refused / 세션 상태 8KB 초과로 저장 거부", 413)
        decision, state["agent_ctx"] = _run_agent(svc, state.get("agent_ctx", {}), result)
        _accumulate(state, result, decision)
        store.put(session_id, state)

        traces.setdefault(session_id, []).append(
            {
                "ts": int(time.time() * 1000),
                "session_id": session_id,
                "frame_t": t,
                "decision": decision.action,
                "reason": decision.reason,
                # FULL tool-call sequence (MISMATCH-2 fix) — includes second_look, in order.
                # Sanitized to strings/numbers only; never image bytes, keys, or raw bodies.
                "tool_calls": _safe_tool_calls(decision.tool_calls),
                "evidence": _safe_jsonable(decision.evidence),
            }
        )
        # Bound the per-session trace buffer (keep the most recent).
        buf = traces[session_id]
        if len(buf) > TRACE_MAX_PER_SESSION:
            del buf[: len(buf) - TRACE_MAX_PER_SESSION]
        _metrics.frame_processed(float(getattr(result, "latency_ms", 0.0)), decision.action)
        return {
            "result": result.to_dict(),
            "decision": decision.to_dict(),
            "calibrated": bool(result.calibrated),
        }

    # --- 4. end session --------------------------------------------------
    @app.post("/v1/sessions/{session_id}/end")
    def end_session(
        session_id: str,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
        x_anon_id: str | None = Header(default=None, alias="X-Anon-Id"),
    ):
        if (err := _check_key(x_api_key)) is not None:
            return err
        state = store.get(session_id)
        if state is None:
            return _error("session_not_found", "unknown or expired session", 404)
        summary = _build_summary(session_id, state)
        # A11: build the numbers-only timeline from the folded accumulator (if present).
        timeline = _timeline_for(state)
        summary_out = summary.to_dict()
        if timeline is not None:
            summary_out["timeline"] = timeline
        today_rate = (timeline or {}).get("per_hour_rate") if timeline else None

        # "Same user" link is the anonymous browser token, stored only as a hash
        # (USER#<hash>); the raw token never touches the DB or logs. No/invalid token =>
        # "no-record mode": this session is simply not persisted.
        user_hash = _anon_hash(x_anon_id)
        history: list[dict[str, Any]] = []
        if user_hash:
            try:
                history = summary_store.recent(user_hash, 5)  # oldest-first, pre-store
            except Exception:  # noqa: BLE001 - a store read failure must not fail /end
                history = []

        prev = by_date.get(_prev_date(summary.date)) if summary.date else None
        report = svc.agent.report(summary, prev)
        # A11 multi-session trend from the bad-posture per-hour rate (history = prior sessions).
        try:
            cmp_full = compare(summary, prev, history=history, today_rate=today_rate)
            report = {**report, "trend": cmp_full.get("trend")}
        except Exception:  # noqa: BLE001 - trend is additive; never fail /end over it
            report = {**report, "trend": None}

        summaries[session_id] = summary
        if summary.date:
            by_date[summary.date] = summary
        # Persist numbers-only daily summary for this anonymous user (if any). Same-day
        # repeat sessions must not overwrite: the sk includes a per-session suffix. The
        # session id's timestamp prefix can collide for rapid sessions, so use the whole
        # id (its random tail is unique) rather than just the first 8 chars.
        if user_hash:
            try:
                summary_store.put_day(
                    user_hash, summary.date or "", session_id, summary_out
                )
            except Exception:  # noqa: BLE001 - CONTRACTS: /end succeeds even if the record write fails
                _metrics.error("summary_persist_failed")

        store.delete(session_id)  # state no longer needed; aggregates kept
        _metrics.session_event("end")
        return {"summary": summary_out, "report": report}

    # --- 5. summary by date ---------------------------------------------
    @app.get("/v1/summary")
    def get_summary(
        date: str,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
        x_anon_id: str | None = Header(default=None, alias="X-Anon-Id"),
    ):
        if (err := _check_key(x_api_key)) is not None:
            return err
        cur = by_date.get(date)
        prev = by_date.get(_prev_date(date)) if date else None
        # A11: include the anonymous user's most recent summaries (<=5, oldest-first) so
        # the web app can draw a trend. Empty when there is no/invalid token.
        history: list[dict[str, Any]] = []
        user_hash = _anon_hash(x_anon_id)
        if user_hash:
            try:
                history = summary_store.recent(user_hash, 5)
            except Exception:  # noqa: BLE001 - read failure degrades to empty history
                history = []
        return {
            "summary": cur.to_dict() if cur else None,
            "previous": prev.to_dict() if prev else None,
            "history": history,
        }

    # --- 6. trace --------------------------------------------------------
    @app.get("/v1/trace/{session_id}")
    def get_trace(
        session_id: str,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    ):
        if (err := _check_key(x_api_key)) is not None:
            return err
        import json

        lines = traces.get(session_id, [])
        body = "\n".join(json.dumps(row, ensure_ascii=False) for row in lines)
        return PlainTextResponse(content=body, media_type="application/x-ndjson")

    return app


# --- helpers (module level so tests can target them) ----------------------
def _new_agent_ctx(svc, session_id: str, lang: str) -> dict[str, Any]:
    """Build the initial agent context as a JSON dict (stored in session state).

    Real agent: an AgentContext dataclass serialised via to_dict() (CONTRACTS §2 — JSON-serialisable).
    Stub agent: a minimal dict the StubAgent ignores apart from lang.
    """
    base = {"session_id": session_id, "session_start_ms": int(time.time() * 1000), "lang": lang}
    if svc.using_stub_agent:
        return base
    try:
        from nunchi.agent import AgentContext  # type: ignore

        return AgentContext(
            session_id=session_id, session_start_ms=base["session_start_ms"], lang=lang
        ).to_dict()
    except Exception:  # noqa: BLE001 - fall back to minimal ctx if agent context shape is unavailable
        return base


def _run_agent(svc, ctx_dict: dict[str, Any], result: FrameResult):
    """Call agent.decide with the right context shape, return (Decision, updated_ctx_dict).

    The service always persists the context as a plain dict so it round-trips through the
    state store (DynamoDB/token). For the real agent we hydrate an AgentContext, let it
    mutate, then serialise back.
    """
    if svc.using_stub_agent:
        return svc.agent.decide(ctx_dict, result), ctx_dict
    from nunchi.agent import AgentContext  # type: ignore

    ctx = AgentContext.from_dict(ctx_dict)
    decision = svc.agent.decide(ctx, result)
    return decision, ctx.to_dict()


class _StateInvalid(Exception):
    """Stored vision state could not be restored via the official SessionState.from_dict
    (version mismatch / corrupt data). Surfaced as 410, never silently reset."""


class _StateTooLarge(Exception):
    """Serialized session state exceeds the 8KB contract cap; the save is refused."""


MAX_STATE_BYTES = 8 * 1024  # CONTRACTS: session STATE blob <= 8KB


def _hydrate_vision_state(svc, state_dict: dict[str, Any]):
    """Rebuild the vision session state from stored JSON using the OFFICIAL serializer.

    Stub vision uses plain dicts (passed through). Real vision uses the V-tab
    SessionState: we restore it ONLY via SessionState.from_dict() (no direct field
    poking — that lost the private filters and 500'd every face frame, MISMATCH-1).
    A restore failure (bad/old data) raises _StateInvalid so the caller returns 410;
    we never start a fresh state behind the user's back.
    """
    if svc.using_stub_vision:
        return state_dict
    from nunchi.vision import SessionState  # type: ignore

    try:
        return SessionState.from_dict(state_dict)
    except Exception as exc:  # any restore failure is an explicit 410, not a silent reset
        raise _StateInvalid(str(type(exc).__name__)) from exc


def _run_vision(svc, vision_state, raw: bytes, t: float, phase: str):
    """Decode JPEG in-memory, call vision, return (FrameResult, new_state). Bytes never escape here."""
    if svc.using_stub_vision:
        # Stub ignores pixel content entirely; still validate it is non-empty (done by caller).
        if phase == "calibrate":
            vision_state = svc.vision.calibrate(vision_state, t)
        return svc.vision.analyze(vision_state, t), vision_state
    # Real vision path: decode then hand the ndarray over; original bytes dropped by caller.
    from nunchi.vision import decode_jpeg  # type: ignore

    frame_bgr = decode_jpeg(raw)
    # `calibrate` is V2 for real vision; call only if present (CONTRACTS §1).
    if phase == "calibrate" and hasattr(svc.vision, "calibrate"):
        svc.vision.calibrate(vision_state, frame_bgr)
    result = svc.vision.analyze(vision_state, frame_bgr, t)
    return result, vision_state


def _safe_jsonable(value: Any, _depth: int = 0) -> Any:
    """Coerce to JSON-safe primitives for the trace. Bytes/ndarray/unknown types become a
    type tag string (never their content), so no image bytes or keys can leak into a trace."""
    if _depth > 6:
        return "<deep>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 256 else value[:256] + "…"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{type(value).__name__}:{len(value)}B>"
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v, _depth + 1) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_safe_jsonable(v, _depth + 1) for v in list(value)[:50]]
    return f"<{type(value).__name__}>"


def _safe_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    """Keep the full ordered sequence of tool calls, each reduced to safe fields:
    tool (name), args (sanitized), result_summary (string). No bytes/keys."""
    out: list[dict[str, Any]] = []
    for tc in (tool_calls or []):
        if not isinstance(tc, dict):
            continue
        out.append({
            "tool": str(tc.get("tool", "")),
            "args": _safe_jsonable(tc.get("args", {})),
            "result_summary": str(tc.get("result_summary", ""))[:256],
        })
    return out


def _to_jsonable(state: Any) -> dict[str, Any]:
    """Session state must be JSON-storable (DynamoDB/token) and <= 8KB (CONTRACTS). Stub
    uses dicts; real SessionState exposes to_dict(). Images are never part of state."""
    if isinstance(state, dict):
        out = state
    elif hasattr(state, "to_dict"):
        out = state.to_dict()
    elif hasattr(state, "__dict__"):
        out = {k: v for k, v in vars(state).items() if not k.startswith("_")}
    else:
        out = {"value": state}
    if len(json.dumps(out, separators=(",", ":")).encode("utf-8")) > MAX_STATE_BYTES:
        raise _StateTooLarge("session state exceeds 8KB")
    return out


def _accumulate(state: dict[str, Any], result: FrameResult, decision) -> None:
    """Fold a frame's events + decision into the running aggregate (numbers only).

    Keeps two parallel views: the flat counts/seconds/longest dicts used by
    `_build_summary`, and a serialized SummaryAccumulator (`state["acc"]`) that also
    tracks per-event intervals so `/end` can emit the A11 `timeline` (numbers only)."""
    for ev in result.events:
        state["counts"][ev.type] = state["counts"].get(ev.type, 0) + 1
        if ev.end is not None:
            dur = max(0.0, ev.end - ev.start)
            state["seconds"][ev.type] = state["seconds"].get(ev.type, 0.0) + dur
            state["longest"][ev.type] = max(state["longest"].get(ev.type, 0.0), dur)
    if decision.action == "nudge":
        state["nudges_sent"] += 1
    elif decision.action == "suppress_focus":
        state["nudges_suppressed"] += 1
    elif decision.action == "ask_confirmation":
        state["confirmations_asked"] += 1
    elif decision.action == "request_recalibration":
        state["recalibrations"] += 1
    # A11 timeline source: fold the same frame into the SummaryAccumulator, if available.
    acc = _acc_load(state.get("acc"))
    if acc is not None:
        try:
            acc.add_frame(result)
            acc.note_decision(decision.action)
            state["acc"] = _acc_dump(acc)
        except Exception:  # noqa: BLE001 - timeline is best-effort; never fail a frame over it
            pass


def _build_summary(session_id: str, state: dict[str, Any]) -> SessionSummary:
    return SessionSummary(
        session_id=session_id,
        date=str(state.get("date", "")),
        duration_s=round(time.time() - float(state.get("started", time.time())), 3),
        counts=dict(state.get("counts", {})),
        seconds=dict(state.get("seconds", {})),
        longest_s=dict(state.get("longest", {})),
        nudges_sent=int(state.get("nudges_sent", 0)),
        nudges_suppressed=int(state.get("nudges_suppressed", 0)),
        confirmations_asked=int(state.get("confirmations_asked", 0)),
        recalibrations=int(state.get("recalibrations", 0)),
    )


def _prev_date(date: str) -> str:
    import datetime as _dt

    try:
        d = _dt.date.fromisoformat(date)
    except ValueError:
        return ""
    return (d - _dt.timedelta(days=1)).isoformat()


# --- A11 anon-id + timeline helpers (cloud tab) ---------------------------
_ANON_RE = re.compile(r"^[0-9a-fA-F]{16,64}$")


def _anon_hash(token: str | None) -> str | None:
    """Map a browser anonymous token to the DB partition suffix, or None (no-record mode).

    Accepts a 16–64 char hex token only; anything else returns None so the session is
    simply not persisted (never an error — brief §1). The raw token is never stored or
    logged: we return sha256(token).hexdigest()[:32] for use as USER#<hash>.
    """
    if not token or not _ANON_RE.match(token):
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def _new_accumulator(session_id: str, date: str):
    """Build a fresh SummaryAccumulator, or None if the agent helper is unavailable (stub-only)."""
    try:
        from nunchi.agent import SummaryAccumulator  # type: ignore
    except Exception:  # noqa: BLE001 - agent not wired; timeline simply absent
        return None
    return SummaryAccumulator(session_id=session_id, date=date)


# Fields of SummaryAccumulator that are JSON-storable (numbers/strings only). Sets and
# tuples are converted on dump/load. Image data never appears in any of these.
_ACC_FIELDS = (
    "session_id", "date", "_t_min", "_t_max", "counts", "seconds", "longest_s",
    "_open", "nudges_sent", "nudges_suppressed", "confirmations_asked", "recalibrations",
    "_bad_posture_starts", "_bad_posture_open", "_bad_posture_intervals", "_end_t",
)


def _acc_dump(acc) -> dict[str, Any] | None:
    """Serialize a SummaryAccumulator to numbers-only JSON for the session state store."""
    if acc is None:
        return None
    out: dict[str, Any] = {}
    for f in _ACC_FIELDS:
        out[f] = getattr(acc, f, None)
    # sets/tuples are not JSON types: store _counted as a list of [type, start] pairs,
    # and intervals as lists of [start, end].
    out["_counted"] = [[t, s] for (t, s) in getattr(acc, "_counted", set())]
    out["_bad_posture_intervals"] = [
        [s, e] for (s, e) in getattr(acc, "_bad_posture_intervals", [])
    ]
    return out


def _acc_load(data: dict[str, Any] | None):
    """Rebuild a SummaryAccumulator from stored JSON, or None if unavailable/invalid."""
    if not data:
        return None
    try:
        from nunchi.agent import SummaryAccumulator  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    acc = SummaryAccumulator(session_id=str(data.get("session_id", "")),
                             date=str(data.get("date", "")))
    for f in _ACC_FIELDS:
        if f in ("session_id", "date"):
            continue
        if f in data and data[f] is not None:
            setattr(acc, f, data[f])
    acc._counted = {(row[0], row[1]) for row in data.get("_counted", []) if len(row) == 2}
    acc._bad_posture_intervals = [
        (row[0], row[1]) for row in data.get("_bad_posture_intervals", []) if len(row) == 2
    ]
    return acc


def _timeline_for(state: dict[str, Any]) -> dict[str, Any] | None:
    """Finalize the session's accumulator and return the A11 timeline (numbers only), or None."""
    acc = _acc_load(state.get("acc"))
    if acc is None:
        return None
    try:
        acc.finalize()
        return acc.timeline()
    except Exception:  # noqa: BLE001 - timeline is best-effort
        return None


def compare(*args, **kwargs):  # noqa: D401 - CONTRACTS name; delegates to the agent helper
    """Lazy delegate to nunchi.agent.compare so the module imports even in stub-only builds."""
    from nunchi.agent import compare as _agent_compare  # type: ignore

    return _agent_compare(*args, **kwargs)


app = create_app()
