"""5-second frontal calibration -> per-user baseline.

Called per frame during the calibration phase. Accumulates good frames (face
present, acceptable quality) and, once enough time/frames are collected, fixes a
baseline: EAR median (open-eye reference), mouth MAR median, face height (px),
frontal pitch proxy, and roll zero. Behaviour thresholds (V3) are derived from
these, so people with naturally narrow eyes are not mislabelled.

No image is stored. The baseline is scalars only.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import numpy as np

from nunchi.vision import expression as X
from nunchi.vision import metrics as M


@dataclass
class Baseline:
    """Fixed per-user reference, produced when calibration completes."""
    ear_open: float                 # median EAR over calibration (eyes open)
    ear_p10: float                  # 10th pct — low end of open-eye EAR spread
    mar_rest: float                 # median resting mouth MAR
    face_px: float                  # median face height (px) at calibration distance
    pitch_frontal: float            # median pitch proxy when looking straight
    roll_zero: float                # median roll (deg) — usually ~0
    samples: int = 0
    # V10 head-pose baseline (solvePnP yaw/pitch + eye-line roll) at frontal.
    # overlay.pose is reported RELATIVE to these (0 = calibrated frontal).
    pose_yaw0: float = 0.0
    pose_pitch0: float = 0.0
    pose_roll0: float = 0.0
    # V14 expression references (resting neutral). overlay.expr is normalised to
    # these so a naturally wide mouth / narrow eyes is not mislabelled. Defaulted
    # so a pre-V14 baseline (which lacks them) deserialises; expression then falls
    # back to mean-EAR span / absolute spans where a reference is missing.
    smile_rest: float | None = None   # resting lip-corner spread/raise proxy
    brow_rest: float | None = None    # resting brow-eye distance proxy (None if unreliable)

    def to_dict(self) -> dict:
        return {"ear_open": self.ear_open, "ear_p10": self.ear_p10, "mar_rest": self.mar_rest,
                "face_px": self.face_px, "pitch_frontal": self.pitch_frontal,
                "roll_zero": self.roll_zero, "samples": self.samples,
                "pose_yaw0": self.pose_yaw0, "pose_pitch0": self.pose_pitch0,
                "pose_roll0": self.pose_roll0,
                "smile_rest": self.smile_rest, "brow_rest": self.brow_rest}

    @classmethod
    def from_dict(cls, d: dict) -> Baseline:
        return cls(ear_open=d["ear_open"], ear_p10=d["ear_p10"], mar_rest=d["mar_rest"],
                   face_px=d["face_px"], pitch_frontal=d["pitch_frontal"],
                   roll_zero=d["roll_zero"], samples=d.get("samples", 0),
                   pose_yaw0=d.get("pose_yaw0", 0.0), pose_pitch0=d.get("pose_pitch0", 0.0),
                   pose_roll0=d.get("pose_roll0", 0.0),
                   smile_rest=d.get("smile_rest"), brow_rest=d.get("brow_rest"))


@dataclass
class CalibrationResult:
    """Progress/outcome of one calibrate() call (vision-internal type, not a contract)."""
    done: bool = False
    progress: float = 0.0           # 0..1 of the required window
    baseline: Baseline | None = None
    ok_frame: bool = False          # was this frame usable?
    reason: str = ""                # why a frame was rejected / status, e.g. "no_face", "too_dark"
    seconds_collected: float = 0.0

    def to_dict(self) -> dict:
        return {"done": self.done, "progress": self.progress,
                "baseline": self.baseline.to_dict() if self.baseline else None,
                "ok_frame": self.ok_frame, "reason": self.reason,
                "seconds_collected": self.seconds_collected}

    @classmethod
    def from_dict(cls, d: dict) -> CalibrationResult:
        b = d.get("baseline")
        return cls(done=d.get("done", False), progress=d.get("progress", 0.0),
                   baseline=Baseline.from_dict(b) if b else None,
                   ok_frame=d.get("ok_frame", False), reason=d.get("reason", ""),
                   seconds_collected=d.get("seconds_collected", 0.0))


@dataclass
class Calibrator:
    """Accumulates calibration samples over a target window (seconds)."""
    seconds: float = 5.0
    min_samples: int = 15
    _ears: list[float] = field(default_factory=list)
    _mars: list[float] = field(default_factory=list)
    _face_px: list[float] = field(default_factory=list)
    _pitch: list[float] = field(default_factory=list)
    _roll: list[float] = field(default_factory=list)
    _pose_yaw: list[float] = field(default_factory=list)
    _pose_pitch: list[float] = field(default_factory=list)
    _pose_roll: list[float] = field(default_factory=list)
    _smile: list[float] = field(default_factory=list)   # V14 resting smile proxy
    _brow: list[float] = field(default_factory=list)     # V14 resting brow-eye dist
    _t_start: float | None = None
    _t_last: float | None = None

    def reset(self) -> None:
        self._ears.clear(); self._mars.clear(); self._face_px.clear()
        self._pitch.clear(); self._roll.clear()
        self._pose_yaw.clear(); self._pose_pitch.clear(); self._pose_roll.clear()
        self._smile.clear(); self._brow.clear()
        self._t_start = None; self._t_last = None

    def feed(self, pts: np.ndarray | None, quality_ok: bool, quality_reason: str, t: float,
             pose: dict | None = None) -> CalibrationResult:
        """Feed one calibration frame. ``pts`` None or bad quality -> rejected (retryable).

        ``pose`` (optional) is the raw per-frame head pose dict (V10) from
        ``headpose.head_pose_from_landmarks``; its yaw/pitch/roll form the frontal
        pose baseline used to report ``overlay.pose`` as a relative value.
        """
        if pts is None:
            return CalibrationResult(ok_frame=False, reason=quality_reason or "no_face",
                                     progress=self._progress(t), seconds_collected=self._elapsed(t))
        if not quality_ok:
            return CalibrationResult(ok_frame=False, reason=quality_reason or "low_quality",
                                     progress=self._progress(t), seconds_collected=self._elapsed(t))

        if self._t_start is None:
            self._t_start = t
        self._t_last = t
        roll = M.head_roll_deg(pts)
        self._ears.append(M.mean_ear(pts, roll_deg=roll))   # V6: roll-aligned EAR
        self._mars.append(M.mouth_aspect_ratio(pts))
        self._face_px.append(M.face_height(pts))
        self._pitch.append(M.pitch_proxy(pts))
        self._roll.append(roll)
        # V14: resting expression references (None samples are skipped so a bad
        # frame doesn't poison the median).
        s_rest = X.smile_proxy_raw(pts)
        if s_rest is not None:
            self._smile.append(s_rest)
        b_rest = X.brow_eye_distance_raw(pts)
        if b_rest is not None:
            self._brow.append(b_rest)
        if pose is not None:
            self._pose_yaw.append(float(pose.get("yaw_deg", 0.0)))
            self._pose_pitch.append(float(pose.get("pitch_deg", 0.0)))
            self._pose_roll.append(float(pose.get("roll_deg", 0.0)))

        progress = self._progress(t)
        if progress >= 1.0 and len(self._ears) >= self.min_samples:
            return CalibrationResult(done=True, progress=1.0, ok_frame=True,
                                     baseline=self._finalise(), seconds_collected=self._elapsed(t),
                                     reason="complete")
        return CalibrationResult(ok_frame=True, progress=progress, seconds_collected=self._elapsed(t),
                                 reason="collecting")

    # -- internals ----------------------------------------------------------

    def _elapsed(self, t: float) -> float:
        return 0.0 if self._t_start is None else max(0.0, t - self._t_start)

    def _progress(self, t: float) -> float:
        return min(1.0, self._elapsed(t) / self.seconds) if self.seconds > 0 else 1.0

    def _finalise(self) -> Baseline:
        ears = sorted(self._ears)
        p10 = ears[max(0, int(len(ears) * 0.1) - 1)] if ears else 0.0
        return Baseline(
            ear_open=round(statistics.median(self._ears), 4),
            ear_p10=round(p10, 4),
            mar_rest=round(statistics.median(self._mars), 4),
            face_px=round(statistics.median(self._face_px), 2),
            pitch_frontal=round(statistics.median(self._pitch), 4),
            roll_zero=round(statistics.median(self._roll), 2),
            samples=len(self._ears),
            pose_yaw0=round(statistics.median(self._pose_yaw), 2) if self._pose_yaw else 0.0,
            pose_pitch0=round(statistics.median(self._pose_pitch), 2) if self._pose_pitch else 0.0,
            pose_roll0=round(statistics.median(self._pose_roll), 2) if self._pose_roll else 0.0,
            smile_rest=round(statistics.median(self._smile), 4) if self._smile else None,
            brow_rest=round(statistics.median(self._brow), 4) if self._brow else None,
        )

    def to_dict(self) -> dict:
        """Serialise in-progress calibration (for Lambda restore mid-calibration)."""
        return {
            "seconds": self.seconds, "min_samples": self.min_samples,
            "ears": [round(x, 5) for x in self._ears],
            "mars": [round(x, 5) for x in self._mars],
            "face_px": [round(x, 3) for x in self._face_px],
            "pitch": [round(x, 5) for x in self._pitch],
            "roll": [round(x, 3) for x in self._roll],
            "pose_yaw": [round(x, 3) for x in self._pose_yaw],
            "pose_pitch": [round(x, 3) for x in self._pose_pitch],
            "pose_roll": [round(x, 3) for x in self._pose_roll],
            "smile": [round(x, 5) for x in self._smile],
            "brow": [round(x, 5) for x in self._brow],
            "t_start": self._t_start, "t_last": self._t_last,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Calibrator:
        c = cls(seconds=d.get("seconds", 5.0), min_samples=d.get("min_samples", 15))
        c._ears = list(d.get("ears", []))
        c._mars = list(d.get("mars", []))
        c._face_px = list(d.get("face_px", []))
        c._pitch = list(d.get("pitch", []))
        c._roll = list(d.get("roll", []))
        c._pose_yaw = list(d.get("pose_yaw", []))
        c._pose_pitch = list(d.get("pose_pitch", []))
        c._pose_roll = list(d.get("pose_roll", []))
        c._smile = list(d.get("smile", []))
        c._brow = list(d.get("brow", []))
        c._t_start = d.get("t_start")
        c._t_last = d.get("t_last")
        return c
