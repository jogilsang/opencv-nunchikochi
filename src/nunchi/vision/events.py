"""Behaviour state machine (V3): per-frame metrics -> time-interval ``Event``s.

Turns the noisy per-frame geometry (EAR/MAR/roll/pitch/face_scale, plus
face-present/quality) into discrete behaviour intervals the agent can act on:

  T1  away          face absent for >= N seconds
      head_tilt     |roll - baseline roll| over threshold, held
      forward_head  face bigger (scale) and/or chin-down (pitch) vs baseline, held
  T2  blink         EAR drops below a per-user fraction of the calibrated open EAR
      deep_blink    a deeper/longer closure (drowsiness signal)
      yawn          MAR rises above a per-user multiple of resting MAR, held
  T3  drink         palm centre held near the mouth (optional palm model; V7).
                    If the palm model is absent, hand_mouth_dist is None and
                    drink is never emitted — see note below.

All thresholds live in one place (:class:`BehaviorThresholds`) and are applied
**relative to the calibration baseline** so naturally narrow eyes / wide mouths
are not mislabelled. Hysteresis (filters.Hysteresis) debounces the on/off edges.

``confidence`` (0..1) scales with how far past the enter threshold the signal
sits, so the agent's ``second_look``/nudge logic has a meaningful number.

Honest sampling limit: at <= 2 fps a 200 ms blink is usually missed between
frames, so a blink *rate* is unreliable. We therefore expose a PERCLOS-like
"eyes-closed fraction" aggregate instead of pretending to count every blink;
single-frame closures we do catch are emitted as ``blink``/``deep_blink`` but
are an **under-count** (documented in vision/README.md).

Pure Python/NumPy on scalars — no image, no model. Fully serialisable so a
restored Lambda instance continues the same intervals.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from nunchi.contracts import Event
from nunchi.vision.calibration import Baseline
from nunchi.vision.filters import Hysteresis

_STATE_SCHEMA = "1.0"

# drink needs the palm detector (OpenCV Zoo palm_detection_mediapipe, Apache-2.0,
# cv2.dnn 5.0, ~3.9MB). It is OPTIONAL: if the model file is absent the engine
# passes hand_mouth_dist=None and ``drink`` is simply never emitted (the rest of
# vision is unaffected). We use only the palm bbox CENTRE near the mouth, held —
# no cup detection, no 21-pt hand model. Conservative by design (false-positive
# risks: chin rest, mouth cover, yawn-with-hand) — see docs/eval/DRINK_FEASIBILITY.md.
SUPPORTED_BEHAVIORS: tuple[str, ...] = ("away", "head_tilt", "forward_head", "blink", "deep_blink", "yawn", "drink")
UNSUPPORTED_BEHAVIORS: tuple[str, ...] = ()


@dataclass
class BehaviorThresholds:
    """All behaviour thresholds in one place. Relative-to-baseline where possible.

    Defaults are conservative starting points; real-clip tuning happens in the
    V4/U1 harness. Fractions/multiples are vs the per-user calibration baseline.
    """
    # away: face missing this many seconds -> away (and a short grace so a 1-frame
    # drop isn't "away"). Uses wall-clock t, robust to variable fps.
    away_seconds: float = 3.0

    # head_tilt: degrees of roll away from baseline roll_zero. enter > exit (hysteresis).
    tilt_enter_deg: float = 12.0
    tilt_exit_deg: float = 8.0
    tilt_hold_s: float = 1.0           # must persist this long before it's an event
    tilt_conf_full_deg: float = 25.0   # roll delta that maps to confidence 1.0

    # forward_head: face_scale (height vs baseline) and pitch delta vs baseline.
    # Either strong scale growth OR chin-down pitch, held, counts.
    fwd_scale_enter: float = 1.18      # face 18% bigger than calibrated
    fwd_scale_exit: float = 1.10
    fwd_pitch_enter: float = 0.06      # pitch proxy delta vs baseline (dimensionless)
    fwd_pitch_exit: float = 0.035
    fwd_hold_s: float = 1.5
    fwd_conf_full_scale: float = 1.45  # scale that maps to confidence 1.0

    # blink / deep_blink: EAR as a fraction of baseline open-eye EAR (ear_open).
    # Closed when EAR < frac * ear_open. deep = lower fraction (more closed).
    blink_frac: float = 0.70           # enter "eyes narrowing/closing"
    blink_exit_frac: float = 0.80      # re-open above this * ear_open
    deep_frac: float = 0.45            # deep closure (drowsiness)
    # a closure held at least this long is "sustained" (eyes-closed / micro-sleep);
    # shorter ones are counted as a (likely under-counted) single blink.
    closed_sustained_s: float = 0.7

    # yawn: MAR as a multiple of resting MAR (mar_rest), held.
    yawn_mult: float = 1.8             # mouth opening vs rest to enter
    yawn_exit_mult: float = 1.4
    yawn_hold_s: float = 1.2
    yawn_conf_full_mult: float = 3.0   # MAR multiple mapping to confidence 1.0

    # drink: palm centre near the mouth (hand_mouth_dist = dist / face_height).
    # Conservative: must be close AND held, since chin-rest / mouth-cover look
    # similar. enter < exit (closer = smaller distance).
    drink_enter: float = 0.9           # hand within ~0.9 face-heights of mouth
    drink_exit: float = 1.3
    drink_hold_s: float = 1.2          # sustained to count (a quick pass is not a drink)
    drink_conf_full: float = 0.4       # distance (closer) mapping to confidence ~1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BehaviorThresholds:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else min(x, 1.0)


@dataclass
class _Track:
    """One ongoing behaviour interval in progress (before it becomes a closed Event)."""
    active: bool = False               # hysteresis latch / sustained flag
    start_t: float | None = None       # when the raw signal first crossed enter
    emitted: bool = False              # whether we've emitted a 'start' (ongoing) Event
    peak: float = 0.0                  # peak confidence-driver seen this interval
    count: int = 0                     # completed intervals of this behaviour

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> _Track:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BehaviorStateMachine:
    """Holds per-behaviour tracks + hysteresis latches; updated once per analysed frame.

    ``update`` returns the list of Events that STARTED, are ONGOING, or ENDED on
    this frame (``end is None`` while ongoing). Aggregates (eyes-closed fraction)
    are kept for a PERCLOS-like summary.
    """
    th: BehaviorThresholds = field(default_factory=BehaviorThresholds)
    tracks: dict[str, _Track] = field(default_factory=dict)
    # hysteresis latches (created lazily once baseline/thresholds known)
    _tilt: Hysteresis | None = None
    _fwd: Hysteresis | None = None
    _blink: Hysteresis | None = None
    _yawn: Hysteresis | None = None
    _drink: Hysteresis | None = None
    _last_face_t: float | None = None  # last time a face was present
    # PERCLOS-like aggregates (sampling-limited; see module docstring)
    frames_eval: int = 0               # frames with a usable EAR
    frames_eye_closed: int = 0         # of those, frames below blink_frac

    def _track(self, name: str) -> _Track:
        t = self.tracks.get(name)
        if t is None:
            t = _Track()
            self.tracks[name] = t
        return t

    def _ensure_latches(self) -> None:
        th = self.th
        if self._tilt is None:
            self._tilt = Hysteresis(enter=th.tilt_enter_deg, exit=th.tilt_exit_deg, direction="above")
        if self._fwd is None:
            # fwd uses a derived scalar (max of scale/pitch "excess"); latch on 1.0 boundary
            self._fwd = Hysteresis(enter=1.0, exit=0.6, direction="above")
        if self._blink is None:
            # blink works on EAR fraction of baseline: closed when fraction < enter
            self._blink = Hysteresis(enter=th.blink_frac, exit=th.blink_exit_frac, direction="below")
        if self._yawn is None:
            self._yawn = Hysteresis(enter=th.yawn_mult, exit=th.yawn_exit_mult, direction="above")
        if self._drink is None:
            # hand_mouth_dist: smaller = closer. closed (near) when below enter.
            self._drink = Hysteresis(enter=th.drink_enter, exit=th.drink_exit, direction="below")

    # -- main entry ---------------------------------------------------------

    def update(self, *, face_present: bool, quality_ok: bool, ear: float | None,
               mar: float | None, roll: float | None, pitch: float | None,
               face_scale: float | None, baseline: Baseline | None, t: float,
               hand_mouth_dist: float | None = None) -> list[Event]:
        """Advance the machine by one frame; return Events touching this frame."""
        self._ensure_latches()
        events: list[Event] = []

        # --- T1 away (independent of quality: a missing face IS the signal) ----
        events += self._update_away(face_present, t)

        # Frames we cannot trust for shape-based behaviours: hold intervals open
        # but do not start/confirm new ones (brief described: "보류").
        trustworthy = face_present and quality_ok and baseline is not None
        if not trustworthy:
            # keep ongoing head_tilt/forward_head/yawn/blink as-is (no confirm),
            # re-emit them as ongoing so the agent still sees them.
            events += self._reemit_ongoing(t)
            return events

        assert baseline is not None
        events += self._update_tilt(roll, baseline, t)
        events += self._update_forward_head(face_scale, pitch, baseline, t)
        events += self._update_eyes(ear, baseline, t)
        events += self._update_yawn(mar, baseline, t)
        events += self._update_drink(hand_mouth_dist, t)
        return events

    # -- behaviours ---------------------------------------------------------

    def _update_away(self, face_present: bool, t: float) -> list[Event]:
        tr = self._track("away")
        if face_present:
            self._last_face_t = t
            if tr.active:
                # end the away interval
                tr.active = False
                tr.emitted = False
                tr.count += 1
                return [Event(type="away", start=tr.start_t or t, end=t,
                              confidence=1.0, count=tr.count)]
            return []
        # face absent
        if self._last_face_t is None:
            self._last_face_t = t  # first frame ever had no face; start the clock
        gone_for = t - (self._last_face_t if self._last_face_t is not None else t)
        if not tr.active and gone_for >= self.th.away_seconds:
            tr.active = True
            tr.start_t = self._last_face_t
            tr.emitted = True
            return [Event(type="away", start=tr.start_t or t, end=None, confidence=1.0,
                          count=tr.count + 1)]
        if tr.active:
            return [Event(type="away", start=tr.start_t or t, end=None, confidence=1.0,
                          count=tr.count + 1)]
        return []

    def _update_tilt(self, roll: float | None, baseline: Baseline, t: float) -> list[Event]:
        if roll is None:
            return self._decay("head_tilt", t)
        delta = abs(roll - baseline.roll_zero)
        assert self._tilt is not None
        latched = self._tilt.update(delta)
        return self._hold_and_emit("head_tilt", latched, delta, self.th.tilt_hold_s,
                                   self._tilt_conf(delta), t)

    def _update_forward_head(self, face_scale: float | None, pitch: float | None,
                             baseline: Baseline, t: float) -> list[Event]:
        if face_scale is None and pitch is None:
            return self._decay("forward_head", t)
        th = self.th
        scale_excess = 0.0
        if face_scale is not None and th.fwd_scale_enter > 1.0:
            scale_excess = (face_scale - 1.0) / (th.fwd_scale_enter - 1.0)
        pitch_excess = 0.0
        if pitch is not None and th.fwd_pitch_enter > 0:
            pitch_excess = (pitch - baseline.pitch_frontal) / th.fwd_pitch_enter
        driver = max(scale_excess, pitch_excess)        # 1.0 == at enter threshold
        assert self._fwd is not None
        latched = self._fwd.update(driver)
        conf = self._fwd_conf(face_scale, pitch, baseline)
        return self._hold_and_emit("forward_head", latched, driver, th.fwd_hold_s, conf, t)

    def _update_eyes(self, ear: float | None, baseline: Baseline, t: float) -> list[Event]:
        if ear is None or baseline.ear_open <= 0:
            return self._decay("blink", t)
        frac = ear / baseline.ear_open          # 1.0 = fully open as at calibration
        self.frames_eval += 1
        assert self._blink is not None
        closed = self._blink.update(frac)       # True while below blink_frac..exit band
        if frac < self.th.blink_frac:
            self.frames_eye_closed += 1

        tr = self._track("blink")
        out: list[Event] = []
        if closed:
            if tr.start_t is None:
                tr.start_t = t
            tr.peak = max(tr.peak, 1.0 - frac)   # deeper closure -> higher peak
            # ongoing: classify deep vs normal by current fraction
            is_deep = frac < self.th.deep_frac
            held = (t - tr.start_t) >= self.th.closed_sustained_s
            kind = "deep_blink" if (is_deep or held) else "blink"
            conf = self._blink_conf(frac, held)
            tr.active = True
            out.append(Event(type=kind, start=tr.start_t, end=None, confidence=conf,
                             count=tr.count + 1))
        else:
            if tr.active and tr.start_t is not None:
                # closure ended -> emit the completed interval
                tr.count += 1
                dur = t - tr.start_t
                is_deep = tr.peak >= (1.0 - self.th.deep_frac) or dur >= self.th.closed_sustained_s
                kind = "deep_blink" if is_deep else "blink"
                out.append(Event(type=kind, start=tr.start_t, end=t,
                                 confidence=self._blink_conf_peak(tr.peak, dur), count=tr.count))
            tr.active = False
            tr.start_t = None
            tr.peak = 0.0
        return out

    def _update_yawn(self, mar: float | None, baseline: Baseline, t: float) -> list[Event]:
        if mar is None or baseline.mar_rest <= 0:
            return self._decay("yawn", t)
        mult = mar / baseline.mar_rest
        assert self._yawn is not None
        latched = self._yawn.update(mult)
        return self._hold_and_emit("yawn", latched, mult, self.th.yawn_hold_s,
                                   self._yawn_conf(mult), t)

    def _update_drink(self, hand_mouth_dist: float | None, t: float) -> list[Event]:
        """drink = palm centre near the mouth, HELD (conservative). No palm /
        no model -> hand_mouth_dist is None -> never fires."""
        if hand_mouth_dist is None:
            return self._decay("drink", t)
        assert self._drink is not None
        near = self._drink.update(hand_mouth_dist)          # True while below enter..exit
        # driver for hold/peak: closeness (bigger = closer), bounded >=0
        driver = max(0.0, self.th.drink_enter - hand_mouth_dist)
        return self._hold_and_emit("drink", near, driver, self.th.drink_hold_s,
                                   self._drink_conf(hand_mouth_dist), t)

    # -- shared hold/emit logic (for latched, duration-gated behaviours) -----

    def _hold_and_emit(self, name: str, latched: bool, driver: float, hold_s: float,
                       conf: float, t: float) -> list[Event]:
        tr = self._track(name)
        if latched:
            if tr.start_t is None:
                tr.start_t = t
            tr.peak = max(tr.peak, driver)
            held = (t - tr.start_t) >= hold_s
            if held:
                tr.active = True
                tr.emitted = True
                return [Event(type=name, start=tr.start_t, end=None, confidence=conf,  # type: ignore[arg-type]
                              count=tr.count + 1)]
            return []   # crossing threshold but not held long enough yet
        # not latched -> close if we had emitted an ongoing interval
        if tr.active and tr.emitted and tr.start_t is not None:
            tr.count += 1
            ev = Event(type=name, start=tr.start_t, end=t, confidence=conf, count=tr.count)  # type: ignore[arg-type]
            tr.active = False; tr.emitted = False; tr.start_t = None; tr.peak = 0.0
            return [ev]
        tr.active = False; tr.start_t = None; tr.peak = 0.0
        return []

    def _decay(self, name: str, t: float) -> list[Event]:
        """Metric missing this frame: close an ongoing interval conservatively."""
        tr = self.tracks.get(name)
        if tr and tr.active and tr.emitted and tr.start_t is not None:
            tr.count += 1
            ev = Event(type=name, start=tr.start_t, end=t, confidence=0.5, count=tr.count)  # type: ignore[arg-type]
            tr.active = False; tr.emitted = False; tr.start_t = None; tr.peak = 0.0
            return [ev]
        return []

    def _reemit_ongoing(self, t: float) -> list[Event]:
        """On an untrusted frame, re-surface ongoing (already-emitted) intervals
        without confirming new ones, so the agent keeps seeing them (held)."""
        out: list[Event] = []
        for name, tr in self.tracks.items():
            if name == "away":
                continue
            if tr.active and tr.emitted and tr.start_t is not None:
                out.append(Event(type=name, start=tr.start_t, end=None, confidence=0.5,  # type: ignore[arg-type]
                                 count=tr.count + 1))
        return out

    # -- confidence maps ----------------------------------------------------

    def _tilt_conf(self, delta: float) -> float:
        th = self.th
        span = max(1e-6, th.tilt_conf_full_deg - th.tilt_enter_deg)
        return _clamp01((delta - th.tilt_enter_deg) / span)

    def _fwd_conf(self, face_scale: float | None, pitch: float | None, baseline: Baseline) -> float:
        th = self.th
        c_scale = 0.0
        if face_scale is not None:
            span = max(1e-6, th.fwd_conf_full_scale - th.fwd_scale_enter)
            c_scale = (face_scale - th.fwd_scale_enter) / span
        c_pitch = 0.0
        if pitch is not None:
            dp = pitch - baseline.pitch_frontal
            span = max(1e-6, th.fwd_pitch_enter * 2.0 - th.fwd_pitch_enter)
            c_pitch = (dp - th.fwd_pitch_enter) / span
        return _clamp01(max(c_scale, c_pitch))

    def _blink_conf(self, frac: float, held: bool) -> float:
        # fully closed (frac ~0) -> ~1; at enter boundary -> ~0. held adds weight.
        base = _clamp01((self.th.blink_frac - frac) / max(1e-6, self.th.blink_frac))
        return _clamp01(base + (0.2 if held else 0.0))

    def _blink_conf_peak(self, peak: float, dur: float) -> float:
        # peak is (1 - frac_min). map onto 0..1 with a small duration bonus.
        return _clamp01(peak + (0.15 if dur >= self.th.closed_sustained_s else 0.0))

    def _yawn_conf(self, mult: float) -> float:
        th = self.th
        span = max(1e-6, th.yawn_conf_full_mult - th.yawn_mult)
        return _clamp01((mult - th.yawn_mult) / span)

    def _drink_conf(self, dist: float) -> float:
        # closer than drink_enter -> rising toward 1.0 at drink_conf_full.
        th = self.th
        span = max(1e-6, th.drink_enter - th.drink_conf_full)
        return _clamp01((th.drink_enter - dist) / span)

    # -- aggregates & serialisation ----------------------------------------

    def eyes_closed_fraction(self) -> float:
        """PERCLOS-like: fraction of evaluated frames with eyes below blink_frac.
        Sampling-limited at low fps — a trend/ratio, not a blink count."""
        return (self.frames_eye_closed / self.frames_eval) if self.frames_eval else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _STATE_SCHEMA,
            "th": self.th.to_dict(),
            "tracks": {k: v.to_dict() for k, v in self.tracks.items()},
            "tilt": self._tilt.to_dict() if self._tilt else None,
            "fwd": self._fwd.to_dict() if self._fwd else None,
            "blink": self._blink.to_dict() if self._blink else None,
            "yawn": self._yawn.to_dict() if self._yawn else None,
            "drink": self._drink.to_dict() if self._drink else None,
            "last_face_t": self._last_face_t,
            "frames_eval": self.frames_eval,
            "frames_eye_closed": self.frames_eye_closed,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BehaviorStateMachine:
        if not isinstance(d, dict) or "th" not in d:
            raise ValueError("invalid BehaviorStateMachine blob")
        try:
            sm = cls(th=BehaviorThresholds.from_dict(d["th"]))
            sm.tracks = {k: _Track.from_dict(v) for k, v in d.get("tracks", {}).items()}
            sm._tilt = Hysteresis.from_dict(d["tilt"]) if d.get("tilt") else None
            sm._fwd = Hysteresis.from_dict(d["fwd"]) if d.get("fwd") else None
            sm._blink = Hysteresis.from_dict(d["blink"]) if d.get("blink") else None
            sm._yawn = Hysteresis.from_dict(d["yawn"]) if d.get("yawn") else None
            sm._drink = Hysteresis.from_dict(d["drink"]) if d.get("drink") else None
            sm._last_face_t = d.get("last_face_t")
            sm.frames_eval = int(d.get("frames_eval", 0))
            sm.frames_eye_closed = int(d.get("frames_eye_closed", 0))
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"corrupt BehaviorStateMachine blob: {e}") from e
        return sm
