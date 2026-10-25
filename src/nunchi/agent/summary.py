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

# A11: what counts as "bad posture" for the per-window timeline. deep_blink is a fatigue
# signal, not a posture one, so it is deliberately excluded (brief §2).
BAD_POSTURE = ("forward_head", "head_tilt")

# Window sizes for the bad-posture timeline, in seconds.
_WINDOWS = {"5m": 300.0, "10m": 600.0, "30m": 1800.0, "60m": 3600.0}


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
    # A11: (start, end) intervals (session-relative seconds) of each "bad posture" event,
    # used to bucket both counts and seconds into 5/10/30/60-minute windows. Numbers only.
    _bad_posture_starts: list[float] = field(default_factory=list)
    _bad_posture_open: dict[str, float] = field(default_factory=dict)   # type -> start (ongoing)
    _bad_posture_intervals: list[tuple[float, float]] = field(default_factory=list)
    _end_t: float | None = None                                        # set by finalize()

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
            # A11: record bad-posture event starts for the timeline (by first sighting)
            if e.type in BAD_POSTURE:
                self._bad_posture_starts.append(float(e.start))
        if e.end is None:
            # ongoing: remember start; duration accrues when it closes or session ends
            self._open.setdefault(e.type, e.start)
            if e.type in BAD_POSTURE:
                self._bad_posture_open.setdefault(e.type, float(e.start))
        else:
            dur = max(0.0, float(e.end) - float(e.start))
            self.seconds[e.type] = self.seconds.get(e.type, 0.0) + dur
            self.longest_s[e.type] = max(self.longest_s.get(e.type, 0.0), dur)
            self._open.pop(e.type, None)
            if e.type in BAD_POSTURE:
                self._bad_posture_open.pop(e.type, None)
                self._bad_posture_intervals.append((float(e.start), float(e.end)))

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
        # A11: close any ongoing bad-posture intervals at session end
        for typ, start in list(self._bad_posture_open.items()):
            self._bad_posture_intervals.append((float(start), end))
        self._bad_posture_open.clear()
        self._end_t = end
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

    # ---- A11: per-window bad-posture timeline ---------------------------------
    def timeline(self) -> dict[str, Any]:
        """Bucket bad-posture events into 5/10/30/60-minute windows from session start.

        Returns {"bad_posture": {"5m":[{start_s,events,seconds},...], ...},
                 "per_hour_rate": float|None}. Numbers only; `finalize()` must run first
        (it closes open intervals). per_hour_rate is null for sessions under 10 minutes.
        """
        t0 = self._t_min or 0.0
        end = getattr(self, "_end_t", None)
        if end is None:
            end = self._t_max or 0.0
        duration = max(0.0, end - t0)
        intervals = self._bad_posture_intervals
        buckets: dict[str, list[dict[str, Any]]] = {}
        for name, width in _WINDOWS.items():
            rows: list[dict[str, Any]] = []
            start = t0
            # one row per window from session start up to (and including) the end
            while start < end or start == t0:
                b_start, b_end = start, start + width
                events = sum(1 for (s, _e) in intervals if b_start <= s < b_end)
                seconds = 0.0
                for (s, e) in intervals:
                    lo, hi = max(s, b_start), min(e, b_end)
                    if hi > lo:
                        seconds += hi - lo
                rows.append({"start_s": round(b_start - t0, 2),
                             "events": events, "seconds": round(seconds, 2)})
                start += width
                if start - t0 >= duration:
                    break
            buckets[name] = rows
        total_events = len(intervals)
        per_hour_rate = (round(total_events / (duration / 3600.0), 2)
                         if duration >= 600.0 and duration > 0 else None)
        return {"bad_posture": buckets, "per_hour_rate": per_hour_rate}


def summary_dict(summary: SessionSummary, acc: SummaryAccumulator | None = None) -> dict[str, Any]:
    """Serialise a SessionSummary to JSON, adding the A11 `timeline` field when available.

    Backward compatible: callers that do not pass an accumulator get the plain summary
    dict (consumers treat a missing `timeline` as null). CONTRACT-CHANGE requested so the
    cloud tab persists these numbers-only fields; see docs/CONTRACTS.md §4.
    """
    out = summary.to_dict()
    if acc is not None:
        out["timeline"] = acc.timeline()
    return out


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
            *, same_band_pct: float = 10.0,
            history: list[Any] | None = None, today_rate: float | None = None) -> dict[str, Any]:
    """Day-over-day comparison plus an optional multi-session trend (A11).

    Uses seconds for duration-type behaviours and counts for event-type behaviours.
    `same_band_pct`: within +-this percent is reported as "about the same".
    `history`: most-recent N (<=5) prior sessions, each a SessionSummary or a
    serialised summary dict carrying `timeline.per_hour_rate`; used to build a
    `trend` (improving / same / worsening) from the bad-posture per-hour rate.
    `today_rate`: today's bad-posture per_hour_rate (None if the session is < 10 min).
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
    result = {"deltas": deltas, "lines_en": lines_en, "lines_ko": lines_ko,
              "has_previous": previous is not None}
    result["trend"] = _trend(today_rate, history, same_band_pct=same_band_pct)
    return result


def _rate_of(s: Any) -> float | None:
    """Extract bad-posture per_hour_rate from a summary dict or an object, if present."""
    if s is None:
        return None
    if isinstance(s, dict):
        tl = s.get("timeline") or {}
        r = tl.get("per_hour_rate") if isinstance(tl, dict) else None
        return float(r) if isinstance(r, (int, float)) else None
    r = getattr(s, "per_hour_rate", None)
    return float(r) if isinstance(r, (int, float)) else None


def _trend(today_rate: float | None, history: list[Any] | None,
           *, same_band_pct: float = 10.0) -> dict[str, Any]:
    """Compare today's bad-posture per-hour rate to the mean of up to 5 prior sessions.

    Lower is better (fewer bad-posture events/hour). Returns direction + EN/KO line.
    """
    prior = [r for r in (_rate_of(h) for h in (history or [])) if r is not None][:5]
    if today_rate is None or not prior:
        return {"direction": "na", "today_rate": today_rate, "baseline_rate": None,
                "n": len(prior),
                "line_en": "No earlier sessions to compare with yet.",
                "line_ko": "아직 비교할 이전 기록이 없어요."}
    baseline = round(sum(prior) / len(prior), 2)
    if baseline == 0:
        pct = None
    else:
        pct = round((today_rate - baseline) / baseline * 100.0, 1)
    if pct is not None and abs(pct) <= same_band_pct:
        direction = "same"
    elif today_rate < baseline:
        direction = "improving"
    elif today_rate > baseline:
        direction = "worsening"
    else:
        direction = "same"
    if direction == "improving":
        line_en = (f"Fewer bad-posture events this time: {today_rate}/h vs a "
                   f"{baseline}/h average over your last {len(prior)} sessions.")
        line_ko = (f"이번에 나쁜 자세가 더 줄었어요: 시간당 {today_rate}회 "
                   f"(최근 {len(prior)}회 평균 {baseline}회).")
    elif direction == "worsening":
        line_en = (f"More bad-posture events this time: {today_rate}/h vs a "
                   f"{baseline}/h average over your last {len(prior)} sessions.")
        line_ko = (f"이번엔 나쁜 자세가 더 늘었어요: 시간당 {today_rate}회 "
                   f"(최근 {len(prior)}회 평균 {baseline}회).")
    else:
        line_en = (f"About the same as before: {today_rate}/h vs a {baseline}/h "
                   f"average over your last {len(prior)} sessions.")
        line_ko = (f"이전과 비슷해요: 시간당 {today_rate}회 "
                   f"(최근 {len(prior)}회 평균 {baseline}회).")
    return {"direction": direction, "today_rate": today_rate, "baseline_rate": baseline,
            "n": len(prior), "pct_change": pct, "line_en": line_en, "line_ko": line_ko}
