"""Session aggregation and day-over-day comparison. OWNER: agent tab.

Turns a stream of `FrameResult`s (OpenCV output) into a `SessionSummary` of
aggregate numbers ONLY — counts, accumulated seconds, longest streaks, plus the
agent's own nudge/confirm/recalibration tallies. These numbers are the only thing
the cloud tab persists (CONTRACTS §4: no images/landmarks). `compare` produces a
day-over-day delta with observation-based wording (never a diagnosis).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts import Event, FrameResult, SessionSummary


@dataclass
class SummaryAccumulator:
    """Folds frames/events into aggregates. Image-free; state is numbers only."""
    session_id: str
    date: str
    _t_min: float | None = None
    _t_max: float | None = None
    counts: dict[str, int] = field(default_factory=dict)
    seconds: dict[str, float] = field(default_factory=dict)
    longest_s: dict[str, float] = field(default_factory=dict)
    # ongoing event start times for seconds/longest accounting: type -> start_t
    _open: dict[str, float] = field(default_factory=dict)
    # events already counted (keyed by (type, start)) so re-seen ongoing events aren't double-counted
    _counted: set = field(default_factory=set)
    nudges_sent: int = 0
    nudges_suppressed: int = 0
    confirmations_asked: int = 0
    recalibrations: int = 0

    def add_frame(self, result: FrameResult) -> None:
        """Fold one frame's events and timestamp into the running aggregates."""
        t = float(getattr(result, "t", 0.0) or 0.0)
        self._t_min = t if self._t_min is None else min(self._t_min, t)
        self._t_max = t if self._t_max is None else max(self._t_max, t)
        for e in (result.events or []):
            if isinstance(e, Event):
                self._add_event(e, t)

    def _add_event(self, e: Event, frame_t: float) -> None:
        key = (e.type, round(e.start, 3))
        # count each distinct event once (by type+start)
        if key not in self._counted:
            self.counts[e.type] = self.counts.get(e.type, 0) + max(1, int(e.count or 1))
            self._counted.add(key)
        if e.end is None:
            # ongoing: remember start; duration accrues when it closes or session ends
            self._open.setdefault(e.type, e.start)
        else:
            dur = max(0.0, float(e.end) - float(e.start))
            self.seconds[e.type] = self.seconds.get(e.type, 0.0) + dur
            self.longest_s[e.type] = max(self.longest_s.get(e.type, 0.0), dur)
            self._open.pop(e.type, None)

    def note_decision(self, action: str) -> None:
        """Count the agent's own actions so the summary reflects what it did."""
        if action == "nudge":
            self.nudges_sent += 1
        elif action == "suppress_focus":
            self.nudges_suppressed += 1
        elif action == "ask_confirmation":
            self.confirmations_asked += 1
        elif action == "request_recalibration":
            self.recalibrations += 1

    def finalize(self, *, end_t: float | None = None) -> SessionSummary:
        """Close any ongoing events at end_t and produce the SessionSummary."""
        end = end_t if end_t is not None else (self._t_max or 0.0)
        for typ, start in list(self._open.items()):
            dur = max(0.0, end - float(start))
            self.seconds[typ] = self.seconds.get(typ, 0.0) + dur
            self.longest_s[typ] = max(self.longest_s.get(typ, 0.0), dur)
        self._open.clear()
        t0 = self._t_min or 0.0
        duration = max(0.0, end - t0)
        return SessionSummary(
            session_id=self.session_id, date=self.date,
            duration_s=round(duration, 2),
            counts=dict(self.counts),
            seconds={k: round(v, 2) for k, v in self.seconds.items()},
            longest_s={k: round(v, 2) for k, v in self.longest_s.items()},
            nudges_sent=self.nudges_sent, nudges_suppressed=self.nudges_suppressed,
            confirmations_asked=self.confirmations_asked, recalibrations=self.recalibrations,
        )


def _pct_change(today: float, prev: float) -> float | None:
    """Percent change today vs prev. None if prev is 0 (undefined)."""
    if prev == 0:
        return None
    return round((today - prev) / prev * 100.0, 1)


def _phrase(behavior: str, pct: float | None, direction: str) -> tuple[str, str]:
    """Observation-based day-over-day phrase (no diagnosis)."""
    label = {
        "forward_head": ("forward-head posture time", "화면 쪽으로 기운 시간"),
        "head_tilt": ("head-tilt time", "고개 기운 시간"),
        "blink": ("blinks", "깜빡임 수"),
        "deep_blink": ("long blinks", "길게 감은 눈"),
        "yawn": ("yawns", "하품 수"),
        "drink": ("drinks", "물 마신 횟수"),
    }.get(behavior, (behavior, behavior))
    if pct is None:
        return (f"{label[0]}: no comparable value yesterday",
                f"{label[1]}: 어제 비교값이 없어요")
    arrow_en = "up" if direction == "up" else ("down" if direction == "down" else "about the same as")
    arrow_ko = "늘었어요" if direction == "up" else ("줄었어요" if direction == "down" else "비슷해요")
    mag = abs(pct)
    if direction == "same":
        return (f"{label[0]} is {arrow_en} yesterday", f"{label[1]}은 어제와 {arrow_ko}")
    return (f"{label[0]} is {mag:.0f}% {arrow_en} vs yesterday",
            f"{label[1]}이 어제보다 {mag:.0f}% {arrow_ko}")


def compare(today: SessionSummary, previous: SessionSummary | None,
            *, same_band_pct: float = 10.0) -> dict[str, Any]:
    """Day-over-day comparison. Returns deltas + observation-based lines (EN/KO).

    Uses seconds for duration-type behaviours and counts for event-type behaviours.
    `same_band_pct`: within +-this percent is reported as "about the same".
    """
    lines_en: list[str] = []
    lines_ko: list[str] = []
    deltas: dict[str, Any] = {}

    def metric_for(b: str, s: SessionSummary) -> float:
        # duration behaviours tracked in seconds; discrete ones in counts
        if b in ("forward_head", "head_tilt"):
            return float(s.seconds.get(b, 0.0))
        return float(s.counts.get(b, s.seconds.get(b, 0.0)))

    behaviors = set(today.counts or {}) | set(today.seconds or {})
    if previous:
        behaviors |= set(previous.counts or {}) | set(previous.seconds or {})
    for b in sorted(behaviors):
        tv = metric_for(b, today)
        pv = metric_for(b, previous) if previous else 0.0
        pct = _pct_change(tv, pv) if previous else None
        if pct is None:
            direction = "na"
        elif abs(pct) <= same_band_pct:
            direction = "same"
        elif pct > 0:
            direction = "up"
        else:
            direction = "down"
        deltas[b] = {"today": tv, "previous": pv, "pct_change": pct, "direction": direction}
        en, ko = _phrase(b, pct, direction)
        lines_en.append(en)
        lines_ko.append(ko)
    return {"deltas": deltas, "lines_en": lines_en, "lines_ko": lines_ko,
            "has_previous": previous is not None}
