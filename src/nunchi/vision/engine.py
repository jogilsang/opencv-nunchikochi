"""VisionEngine — OpenCV 5 face/quality/landmark pipeline (V2 + V2b).

Pipeline: YuNet (detect) -> FaceMesh V2 ONNX (478 pts) via ``cv2.dnn`` -> geometric
metrics (EAR/MAR/roll/pitch/face_scale) -> per-metric stabilisation. A 5-second
frontal ``calibrate`` fixes a per-user baseline. ``analyze`` also fills a tiny
display-only ``overlay``. ``analyze_variant`` re-analyses the SAME frame a
different way (enhance / zoom_face / strict) WITHOUT mutating session state, for
the agent's active-perception ``second_look``. ``SessionState`` serialises to/from
a small JSON blob so a different Lambda instance resumes with identical output.

All inference is inside OpenCV (no MediaPipe/dlib/torch runtime). No frame/image
is ever stored or returned — only FrameResult / Quality / Metrics / Event /
overlay (coordinates/numbers only). V3 adds a behaviour state machine
(events.py) that turns per-frame metrics into ``FrameResult.events``.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from nunchi.contracts import SCHEMA_VERSION, FrameResult, Metrics, Quality
from nunchi.vision.calibration import Baseline, CalibrationResult, Calibrator
from nunchi.vision.enhance import enhance_bgr
from nunchi.vision.events import BehaviorStateMachine
from nunchi.vision.expression import raw_expression
from nunchi.vision.filters import FilterConfig, StabilizedMetric
from nunchi.vision.hands import PalmDetector, hand_mouth_signal
from nunchi.vision.headpose import head_pose_from_landmarks
from nunchi.vision.landmarks import (
    LandmarkExtractor,
    Landmarks,
    count_people,
    secondary_face_significant,
    select_primary_face,
)
from nunchi.vision.metrics import mouth_centre, raw_metrics
from nunchi.vision.overlay import build_overlay

_STATE_SCHEMA = "3.0"   # V10: adds head-pose baseline + pose filters. 2.0/1.0 rejected.

# Quality thresholds (BGR mean luma / Laplacian variance).
_DARK_BELOW = 50.0
_BRIGHT_ABOVE = 215.0
_BLUR_BELOW = 60.0
_FACE_PX_MIN = 24
# Strict variant uses tighter quality gates.
_STRICT_BLUR_BELOW = 120.0
_STRICT_FACE_PX_MIN = 40
_ZOOM_MARGIN = 1.6
_VARIANTS = ("enhance", "zoom_face", "strict")


def pose_disabled() -> bool:
    """Whether head-pose (overlay.pose) is turned off via the environment.

    ``NUNCHI_DISABLE_POSE=1`` disables the V10 posture-buddy pose so operators can
    A/B pose cost at runtime, or shed it as a safety valve under load, WITHOUT a
    redeploy. Default (unset/0) = pose ON. Read per call so it can flip live.
    """
    return os.environ.get("NUNCHI_DISABLE_POSE", "").strip() in ("1", "true", "True", "yes")


def expr_disabled() -> bool:
    """Whether expression numbers (overlay.expr, V14) are turned off via the env.

    ``NUNCHI_DISABLE_EXPR=1`` drops the V14 face-expression block so operators can
    A/B its cost or shed it under load WITHOUT a redeploy. Default = expr ON.
    """
    return os.environ.get("NUNCHI_DISABLE_EXPR", "").strip() in ("1", "true", "True", "yes")


@dataclass
class SessionState:
    """Per-session vision state (no frames; scalars/filters/baseline only).

    Serialises to a small JSON blob (<=8KB) so another Lambda instance can resume
    with identical output.
    """
    session_id: str
    frames_seen: int = 0
    baseline: Baseline | None = None
    calibrated: bool = False
    _calibrator: Calibrator = field(default_factory=Calibrator)
    _roll: StabilizedMetric | None = None
    _pitch: StabilizedMetric | None = None
    _scale: StabilizedMetric | None = None
    _ear: StabilizedMetric | None = None
    _mar: StabilizedMetric | None = None
    _pose_yaw: StabilizedMetric | None = None   # V10: head-pose overlay smoothing
    _pose_pitch: StabilizedMetric | None = None
    _pose_roll: StabilizedMetric | None = None
    _expr_eye_l: StabilizedMetric | None = None   # V14: expression overlay smoothing
    _expr_eye_r: StabilizedMetric | None = None
    _expr_mouth: StabilizedMetric | None = None
    _expr_smile: StabilizedMetric | None = None
    _expr_brow: StabilizedMetric | None = None
    _sm: BehaviorStateMachine | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def baseline_face_px(self) -> float | None:
        return self.baseline.face_px if self.baseline else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _STATE_SCHEMA,
            "session_id": self.session_id,
            "frames_seen": self.frames_seen,
            "calibrated": self.calibrated,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "calibrator": self._calibrator.to_dict(),
            "filters": {
                "roll": self._roll.to_dict() if self._roll else None,
                "pitch": self._pitch.to_dict() if self._pitch else None,
                "scale": self._scale.to_dict() if self._scale else None,
                "ear": self._ear.to_dict() if self._ear else None,
                "mar": self._mar.to_dict() if self._mar else None,
                "pose_yaw": self._pose_yaw.to_dict() if self._pose_yaw else None,
                "pose_pitch": self._pose_pitch.to_dict() if self._pose_pitch else None,
                "pose_roll": self._pose_roll.to_dict() if self._pose_roll else None,
                # V14: expression (overlay.expr) filters are display-only and are
                # DELIBERATELY NOT serialised — expr numbers must never enter the
                # persisted state blob (DynamoDB). After a Lambda swap the expr EMA
                # simply re-warms over a frame or two (cosmetic). See
                # tests/vision/test_expression_privacy.py.
            },
            "state_machine": self._sm.to_dict() if self._sm else None,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionState:
        if not isinstance(d, dict):
            raise ValueError("SessionState blob must be a dict")  # noqa: TRY004 (restore errors are ValueError by contract)
        # V10: schema 3.0 adds a head-pose baseline (pose_*0) + pose filters. A
        # pre-V10 blob (2.0/1.0) lacks the frontal pose reference, so reject it so
        # overlay.pose is never computed against a missing baseline. A fresh/minimal
        # blob (new_session before any serialise) carries no schema and is allowed.
        schema = d.get("schema")
        if schema is not None and schema != _STATE_SCHEMA:
            raise ValueError(
                f"unsupported SessionState schema {schema!r}; expected {_STATE_SCHEMA!r} "
                "(V10 head-pose baseline). Re-calibrate the session."
            )
        st = cls(session_id=d["session_id"], frames_seen=d.get("frames_seen", 0),
                 calibrated=d.get("calibrated", False))
        b = d.get("baseline")
        st.baseline = Baseline.from_dict(b) if b else None
        st._calibrator = Calibrator.from_dict(d["calibrator"]) if d.get("calibrator") else Calibrator()
        f = d.get("filters", {})
        st._roll = StabilizedMetric.from_dict(f["roll"]) if f.get("roll") else None
        st._pitch = StabilizedMetric.from_dict(f["pitch"]) if f.get("pitch") else None
        st._scale = StabilizedMetric.from_dict(f["scale"]) if f.get("scale") else None
        st._ear = StabilizedMetric.from_dict(f["ear"]) if f.get("ear") else None
        st._mar = StabilizedMetric.from_dict(f["mar"]) if f.get("mar") else None
        st._pose_yaw = StabilizedMetric.from_dict(f["pose_yaw"]) if f.get("pose_yaw") else None
        st._pose_pitch = StabilizedMetric.from_dict(f["pose_pitch"]) if f.get("pose_pitch") else None
        st._pose_roll = StabilizedMetric.from_dict(f["pose_roll"]) if f.get("pose_roll") else None
        # V14: expr filters are not persisted (privacy). Re-create fresh ones on
        # restore so smoothing resumes (cosmetic re-warm, no expr value recovered
        # from the blob).
        _expr_cfg = FilterConfig(ema_alpha=0.5, median_window=3)
        st._expr_eye_l = StabilizedMetric.from_config(_expr_cfg)
        st._expr_eye_r = StabilizedMetric.from_config(_expr_cfg)
        st._expr_mouth = StabilizedMetric.from_config(_expr_cfg)
        st._expr_smile = StabilizedMetric.from_config(_expr_cfg)
        st._expr_brow = StabilizedMetric.from_config(_expr_cfg)
        sm = d.get("state_machine")
        st._sm = BehaviorStateMachine.from_dict(sm) if sm else None
        st.extra = d.get("extra", {})
        return st


def runtime_info() -> dict[str, Any]:
    """Runtime backend/arch evidence for /healthz — derived, never a config claim."""
    info = cv2.getBuildInformation()
    low = info.lower()
    backend = "cool" if ("cool" in low or "opencv optimized" in low) else "opencv"
    arch = "unknown"
    for line in info.splitlines():
        if line.strip().lower().startswith("baseline:"):
            arch = line.split(":", 1)[1].strip() or arch
            break
    return {"cv_version": cv2.__version__, "backend": backend, "arch": arch}


class VisionEngine:
    """Loads YuNet + FaceMesh once and analyses frames."""

    def __init__(self, models_dir: str, *, backend: str = "opencv",
                 filter_config: FilterConfig | None = None) -> None:
        self._models_dir = Path(models_dir)
        self._requested_backend = backend
        info = runtime_info()
        self.cv_version = info["cv_version"]
        self.backend = info["backend"]
        self._filter_cfg = filter_config or FilterConfig()
        self._lm = LandmarkExtractor(self._models_dir)
        self._palm = PalmDetector(self._models_dir)   # V7: optional, for 'drink'
        self.drink_supported = self._palm.available

    # -- public API (contract) ------------------------------------------------

    def new_session(self, session_id: str) -> SessionState:
        st = SessionState(session_id=session_id)
        st._calibrator = Calibrator()
        st._roll = StabilizedMetric.from_config(self._filter_cfg)
        st._pitch = StabilizedMetric.from_config(self._filter_cfg)
        st._scale = StabilizedMetric.from_config(self._filter_cfg)
        st._ear = StabilizedMetric.from_config(FilterConfig(ema_alpha=0.6, median_window=3))
        st._mar = StabilizedMetric.from_config(FilterConfig(ema_alpha=0.6, median_window=3))
        st._pose_yaw = StabilizedMetric.from_config(self._filter_cfg)
        st._pose_pitch = StabilizedMetric.from_config(self._filter_cfg)
        st._pose_roll = StabilizedMetric.from_config(self._filter_cfg)
        # V14 expression smoothing: responsive but jitter-damped. alpha 0.5 +
        # median 3 keeps lag well under 200ms at the ~2fps frame cadence.
        _expr_cfg = FilterConfig(ema_alpha=0.5, median_window=3)
        st._expr_eye_l = StabilizedMetric.from_config(_expr_cfg)
        st._expr_eye_r = StabilizedMetric.from_config(_expr_cfg)
        st._expr_mouth = StabilizedMetric.from_config(_expr_cfg)
        st._expr_smile = StabilizedMetric.from_config(_expr_cfg)
        st._expr_brow = StabilizedMetric.from_config(_expr_cfg)
        st._sm = BehaviorStateMachine()
        return st

    def calibrate(self, state: SessionState, frame_bgr: np.ndarray, t: float = 0.0) -> CalibrationResult:
        q = self.quality(frame_bgr)
        lm = self._extract(frame_bgr)
        pts = lm.pts if (lm and lm.ok) else None
        reason = "" if q.ok else (q.issues[0] if q.issues else "low_quality")
        # V10: accumulate the frontal head-pose so overlay.pose is reported relative
        # to the calibrated frontal. Pose needs the frame size + a face scale.
        pose = None
        if pts is not None and frame_bgr is not None and getattr(frame_bgr, "size", 0):
            H, W = frame_bgr.shape[0], frame_bgr.shape[1]
            face_px = float(lm.bbox[3]) if (lm and lm.bbox) else 0.0
            pose = head_pose_from_landmarks(pts, W, H, face_px)
        res = state._calibrator.feed(pts, q.ok and pts is not None, reason, t, pose=pose)
        if res.done and res.baseline is not None:
            state.baseline = res.baseline
            state.calibrated = True
        return res

    def quality(self, frame_bgr: np.ndarray, *, strict: bool = False) -> Quality:
        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            return Quality(ok=False, issues=["no_face"])
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        brightness = float(gray.mean())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        faces = self._lm.detect_faces(frame_bgr)
        n = len(faces)
        primary = select_primary_face(faces, frame_bgr.shape[1], frame_bgr.shape[0]) if n else None
        # face_px reflects the SUBJECT (primary/largest) face, not an incidental
        # first YuNet row (V5: fixes face_too_small judged on a background box).
        face_px = int(primary[3]) if primary is not None else 0
        # multiple_faces only for a genuine 2nd person (comparable size); a small
        # background/spurious detection must not flag it (V5 sweep: YuNet raised
        # multiple_faces on texture/crowds in almost every clean frame).
        real_multi = primary is not None and secondary_face_significant(faces, primary)

        blur_thr = _STRICT_BLUR_BELOW if strict else _BLUR_BELOW
        face_min = _STRICT_FACE_PX_MIN if strict else _FACE_PX_MIN
        issues: list[str] = []
        if brightness < _DARK_BELOW:
            issues.append("too_dark")
        elif brightness > _BRIGHT_ABOVE:
            issues.append("too_bright")
        if sharpness < blur_thr:
            issues.append("blurry")
        if n == 0:
            issues.append("no_face")
        elif real_multi:
            issues.append("multiple_faces")
        if primary is not None and face_px < face_min:
            issues.append("face_too_small")

        return Quality(ok=not issues, brightness=round(brightness, 2),
                       sharpness=round(sharpness, 2), face_px=face_px, issues=issues)  # type: ignore[arg-type]

    def analyze(self, state: SessionState, frame_bgr: np.ndarray, t: float) -> FrameResult:
        """Analyse one frame -> FrameResult; updates session filters/state."""
        return self._analyze(state, frame_bgr, t, mutate=True)

    def analyze_variant(self, state: SessionState, frame_bgr: np.ndarray, t: float,
                        variant: str) -> FrameResult:
        """Re-analyse the SAME frame a different way, WITHOUT mutating state.

        - ``enhance``: CLAHE+gamma, then re-detect/re-estimate (helps dark/low-contrast).
        - ``zoom_face``: crop a looser box around the face and 2x upscale, re-mesh
          (helps small/far faces).
        - ``strict``: same frame, tighter quality gates (re-judge confidence).
        Raises ValueError on an unknown variant. If the variant is worse, the
        result is returned in the same shape for the agent to compare.
        """
        if variant not in _VARIANTS:
            raise ValueError(f"unknown variant {variant!r}; expected one of {_VARIANTS}")
        if variant == "enhance":
            work = enhance_bgr(frame_bgr) if (frame_bgr is not None and getattr(frame_bgr, "size", 0)) else frame_bgr
            return self._analyze(state, work, t, mutate=False)
        if variant == "zoom_face":
            work = self._zoom_on_face(frame_bgr)
            return self._analyze(state, work if work is not None else frame_bgr, t, mutate=False)
        # strict
        return self._analyze(state, frame_bgr, t, mutate=False, strict=True)

    # -- internals ------------------------------------------------------------

    def _extract(self, frame_bgr: np.ndarray) -> Landmarks | None:
        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            return None
        return self._lm.extract_best(frame_bgr)

    def _zoom_on_face(self, frame_bgr: np.ndarray) -> np.ndarray | None:
        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            return None
        faces = self._lm.detect_faces(frame_bgr)
        if not faces:
            return None
        H, W = frame_bgr.shape[:2]
        x, y, w, h = select_primary_face(faces, W, H)[:4]
        cx, cy = x + w / 2.0, y + h / 2.0
        side = max(w, h) * _ZOOM_MARGIN
        x0 = int(max(0, cx - side / 2.0)); y0 = int(max(0, cy - side / 2.0))
        x1 = int(min(W, x0 + side)); y1 = int(min(H, y0 + side))
        crop = frame_bgr[y0:y1, x0:x1]
        if crop.size == 0 or crop.shape[0] < 2 or crop.shape[1] < 2:
            return None
        return cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    def _head_pose(self, state: SessionState, lm: Landmarks, W: int, H: int,
                   *, mutate: bool) -> dict[str, float] | None:
        """Head pose (overlay.pose) relative to the calibration frontal, smoothed.

        Returns the CONTRACTS dict {yaw_deg,pitch_deg,roll_deg,depth,conf} or None
        if the solve fails. Deltas are vs the calibrated frontal pose (0 = frontal).
        depth = current face height / calibrated face height (reuses face_scale).
        On the real path (mutate) the angles are EMA-smoothed via the session
        filters; on variants we smooth on a copy-free direct value (no state write).
        """
        if lm.pts is None:
            return None
        face_px = float(lm.bbox[3]) if lm.bbox else 0.0
        raw = head_pose_from_landmarks(lm.pts, W, H, face_px)
        if raw is None:
            return None
        b = state.baseline
        yaw = raw["yaw_deg"] - (b.pose_yaw0 if b else 0.0)
        pitch = raw["pitch_deg"] - (b.pose_pitch0 if b else 0.0)
        roll = raw["roll_deg"] - (b.pose_roll0 if b else 0.0)
        if mutate and state._pose_yaw and state._pose_pitch and state._pose_roll:
            yaw = state._pose_yaw.update(yaw).smoothed
            pitch = state._pose_pitch.update(pitch).smoothed
            roll = state._pose_roll.update(roll).smoothed
        depth = 1.0
        if b and b.face_px:
            depth = round(face_px / float(b.face_px), 3) if face_px else 1.0
        return {
            "yaw_deg": round(float(yaw), 2),
            "pitch_deg": round(float(pitch), 2),
            "roll_deg": round(float(roll), 2),
            "depth": float(depth),
            "conf": float(raw["conf"]),
        }

    def _expression(self, state: SessionState, lm: Landmarks, *, mutate: bool,
                    conf: float | None) -> dict[str, Any] | None:
        """V14 face-expression numbers for ``overlay.expr`` (display-only).

        Returns ``{eye_l,eye_r,mouth_open,smile,brow_raise}`` (each 0..1 or None),
        normalised to the calibration baseline and EMA-smoothed on the real path.
        NOT emotion — only measured face movement. When confidence is low
        (``conf`` below a floor, e.g. a bad head-pose solve) all fields are None so
        the web doll freezes rather than twitching on noise. Returns None if there
        are no landmarks. On variants (mutate=False) it computes but does not write
        the session filters.
        """
        if lm.pts is None:
            return None
        b = state.baseline
        # References: prefer calibrated per-user values; fall back to sane spans
        # so expression still works before calibration (eyes/mouth only).
        ear_open = b.ear_open if b else 0.25
        ear_low = b.ear_p10 if b else 0.10
        mar_rest = b.mar_rest if b else 0.0
        smile_rest = b.smile_rest if b else None
        brow_rest = b.brow_rest if b else None
        raw = raw_expression(
            lm.pts, ear_open=ear_open, ear_low=ear_low, mar_rest=mar_rest,
            smile_rest=smile_rest, brow_rest=brow_rest,
        )
        # Confidence gate: if the pose solve conf is known and poor, don't report
        # noisy expression (null = web freezes the face). Threshold mirrors the
        # posture doll's "estimation unstable" behaviour.
        if conf is not None and conf < 0.3:
            return {k: None for k in raw}

        filt = {
            "eye_l": state._expr_eye_l, "eye_r": state._expr_eye_r,
            "mouth_open": state._expr_mouth, "smile": state._expr_smile,
            "brow_raise": state._expr_brow,
        }
        out: dict[str, Any] = {}
        for key, val in raw.items():
            if val is None:
                out[key] = None
                continue
            f = filt.get(key)
            if mutate and f is not None:
                val = f.update(float(val)).smoothed
            out[key] = round(float(val), 3)
        return out

    def _analyze(self, state: SessionState, frame_bgr: np.ndarray, t: float,
                 *, mutate: bool, strict: bool = False) -> FrameResult:
        t0 = time.perf_counter()
        if mutate:
            state.frames_seen += 1

        q = self.quality(frame_bgr, strict=strict)
        lm = self._extract(frame_bgr)
        face_present = bool(lm and lm.ok)
        persons = 0
        if frame_bgr is not None and getattr(frame_bgr, "size", 0):
            faces = self._lm.detect_faces(frame_bgr)
            persons = count_people(faces, frame_bgr.shape[1], frame_bgr.shape[0])
            persons = max(persons, 1 if face_present else 0)

        metrics = Metrics()
        overlay = None
        H, W = (frame_bgr.shape[0], frame_bgr.shape[1]) if (frame_bgr is not None and getattr(frame_bgr, "size", 0)) else (0, 0)
        raw_ear = raw_mar = None
        hand_mouth = None
        hand_mouth_dy = None
        if face_present and lm.pts is not None:
            metrics = raw_metrics(lm.pts, baseline_face_px=state.baseline_face_px)
            raw_ear, raw_mar = metrics.ear, metrics.mar   # fast signals (pre-smoothing)
            # V7 drink: palm-near-mouth proximity (only on the real analyze path,
            # never on variants, so second_look/zoom_face can't create 'drink').
            # V12: also carry the signed vertical offset (dy) so the behaviour
            # layer can require the hand to be AT/ABOVE the mouth and to have risen
            # (a keyboard hand / chin-rest is near by distance but below the mouth).
            if mutate and self._palm.available:
                palms = self._palm.detect(frame_bgr)
                mouth = mouth_centre(lm.pts)
                # normalise by calibrated face height if available, else current bbox
                fpx = float(state.baseline_face_px) if state.baseline_face_px else float(lm.bbox[3] if lm.bbox else 0)
                sig = hand_mouth_signal(palms, mouth, fpx)
                if sig is not None:
                    hand_mouth = sig.dist
                    hand_mouth_dy = sig.dy
                    metrics.hand_mouth_dist = round(sig.dist, 3)
            if mutate:
                if metrics.head_roll_deg is not None:
                    metrics.head_roll_deg = round(state._roll.update(metrics.head_roll_deg).smoothed, 2)
                if metrics.head_pitch_proxy is not None:
                    metrics.head_pitch_proxy = round(state._pitch.update(metrics.head_pitch_proxy).smoothed, 4)
                if metrics.face_scale is not None:
                    metrics.face_scale = round(state._scale.update(metrics.face_scale).smoothed, 3)
                if metrics.ear is not None:
                    state._ear.update(metrics.ear)
                if metrics.mar is not None:
                    state._mar.update(metrics.mar)
            overlay = build_overlay(lm.pts, lm.bbox, W, H)
            # V10 head pose for the web "posture doll": yaw/pitch (solvePnP) +
            # eye-line roll, reported RELATIVE to the calibrated frontal and EMA-
            # smoothed. On variants (mutate=False) we still compute a pose for
            # display but do not update the session filters. If the solve fails or
            # the face is bad, pose stays absent (web freezes the doll).
            # NUNCHI_DISABLE_POSE=1 skips it (runtime A/B / load-shed switch, V11).
            if overlay is not None and not pose_disabled():
                pose = self._head_pose(state, lm, W, H, mutate=mutate)
                if pose is not None:
                    overlay["pose"] = pose
            # V14 face-expression numbers for the web "face doll" (expr follows the
            # user's eyes/mouth/brows). Numbers only, normalised to the baseline,
            # never pixels. Gated by the pose confidence when available so noise
            # doesn't jitter the doll. NUNCHI_DISABLE_EXPR=1 sheds it live.
            if overlay is not None and not expr_disabled():
                pose_conf = overlay.get("pose", {}).get("conf") if isinstance(overlay.get("pose"), dict) else None
                expr = self._expression(state, lm, mutate=mutate, conf=pose_conf)
                if expr is not None:
                    overlay["expr"] = expr

        # V3 behaviour state machine: only on the real analyze path (not variants).
        # Blinks/yawns read the RAW fast EAR/MAR so a brief closure isn't smoothed
        # away; tilt/forward_head read the SMOOTHED slow metrics. ``away`` needs
        # the no-face case too, so this runs regardless of face_present.
        events: list = []
        if mutate and state._sm is not None:
            events = state._sm.update(
                face_present=face_present,
                quality_ok=q.ok,
                ear=raw_ear,
                mar=raw_mar,
                roll=metrics.head_roll_deg,
                pitch=metrics.head_pitch_proxy,
                face_scale=metrics.face_scale,
                hand_mouth_dist=hand_mouth,
                hand_mouth_dy=hand_mouth_dy,
                baseline=state.baseline,
                t=float(t),
            )

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return FrameResult(
            schema=SCHEMA_VERSION,
            session_id=state.session_id,
            t=float(t),
            face_present=face_present,
            persons=persons,
            metrics=metrics,
            quality=q,
            events=events,
            overlay=overlay,
            calibrated=state.calibrated,
            latency_ms=round(latency_ms, 2),
            backend=self.backend,
            cv_version=self.cv_version,
        )
