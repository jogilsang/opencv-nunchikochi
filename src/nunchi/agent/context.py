"""Agent context and policy configuration. OWNER: agent tab (see docs/RULES.md).

All objects here are JSON-serialisable (dataclasses of primitives) so the same
context can be carried in a session token or a DynamoDB state record by the
cloud tab. No frames/images ever appear here (privacy, CONTRACTS §2).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Behaviours the agent nudges about when sustained, with a default cooldown (s).
# Rationale (README): forward_head/head_tilt are postural and benefit from a long
# gap so we are not nagging; blink-related signals use a longer gap still.
SUSTAINED_BEHAVIORS = ("forward_head", "head_tilt", "deep_blink")


@dataclass
class PolicyConfig:
    """Thresholds separated from logic so they can be tuned without touching rules.

    Defaults chosen to be conservative (fewer, higher-signal nudges). All times in seconds.
    """
    # (1) sustained signal -> nudge
    sustained_min_s: float = 180.0            # a behaviour must persist this long before a nudge
    nudge_cooldown_s: dict[str, float] = field(
        default_factory=lambda: {
            # Calmer defaults (A11 user feedback: "alerts feel too real-time"):
            # >=20 min between nudges of the same behaviour.
            "forward_head": 1200.0,           # 20 min between posture nudges
            "head_tilt": 1200.0,
            "deep_blink": 1200.0,             # 20 min; eye-strain signals no longer more frequent
            "default": 1200.0,
        }
    )
    daily_nudge_cap: int = 20                 # hard ceiling on nudges per session/day
    # A11: a rolling-hour ceiling so a long session can't drip 1 nudge every cooldown
    # forever. Counts nudges in the last 3600 s of session time.
    max_nudges_per_hour: int = 3
    # A11: confirm toasts (asking the human yes/no) are the most intrusive; keep them rare
    # and never fire the same kind twice in a row.
    max_confirms_per_hour: int = 2
    # A11: suppress a confirm if the previous confirm was the same kind. Set False to
    # reproduce pre-A11 behaviour (used by the before/after measurement in A12).
    confirm_no_repeat_kind: bool = True

    # (2) focus window -> suppress
    focus_min_quiet_s: float = 120.0          # low posture change + low blink for this long = focus
    focus_blink_rate_max: float = 0.20        # blinks/s at or below this counts as "low blink"
    focus_posture_change_max: float = 3.0     # degrees of roll change tolerated to still be "quiet"

    # (3) quality bad -> recalibration / guidance; repeated -> confirmation
    quality_repeat_for_confirm: int = 3       # this many consecutive bad-quality frames -> ask human
    # A11: a transient bad frame should not pop a warning; only surface a quality issue
    # once it has persisted at least this long.
    quality_warn_min_sustained_s: float = 30.0

    # (4) low confidence band -> ask_confirmation
    low_conf_lo: float = 0.40
    low_conf_hi: float = 0.60

    # active perception (second_look): re-analyse with OpenCV before asking a human
    second_look_enabled: bool = True
    # which variant to try for low-confidence events (zoom in to get a closer look)
    low_conf_variant: str = "zoom_face"

    # LLM planner (mode="llm"): only used on ambiguous moments
    llm_max_calls: int = 20                   # hard per-session cap on LLM calls
    llm_timeout_s: float = 3.0                # per-FRAME soft timeout -> rules fallback
    llm_report_timeout_s: float = 15.0        # end-of-session report runs once -> longer budget

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentContext:
    """Mutable per-session state the decision loop reads and updates. JSON-serialisable."""
    session_id: str = ""
    session_start_ms: int = 0

    # last nudge bookkeeping (for cooldown + daily cap)
    last_nudge_ms_by_type: dict[str, int] = field(default_factory=dict)
    nudges_sent: int = 0
    nudges_suppressed: int = 0
    confirmations_asked: int = 0
    recalibrations: int = 0

    # A11 rolling-hour alert limiting (session-relative seconds; deterministic + testable)
    nudge_ts: list[float] = field(default_factory=list)      # session-t of each nudge sent
    confirm_ts: list[float] = field(default_factory=list)    # session-t of each confirm asked
    last_confirm_about: str = ""                             # last confirm kind (no same-kind in a row)
    # A11 digest: signals suppressed purely to stay quiet still get counted for the report.
    suppressed_digest: dict[str, int] = field(default_factory=dict)
    # A11 quality: session-t when the current run of bad-quality frames began (None = quality ok)
    bad_quality_since_t: float | None = None

    # active-perception bookkeeping
    second_looks: int = 0                  # how many times OpenCV re-analysed
    second_look_resolved: int = 0          # re-analysis that avoided a human / recalibration

    # LLM planner bookkeeping (mode="llm")
    llm_calls: int = 0                     # LLM calls made this session (capped)

    # focus / away tracking
    in_focus: bool = False
    away_since_t: float | None = None      # session-t when user left; None = present

    # quality streak
    bad_quality_streak: int = 0

    # ongoing sustained behaviours: type -> session-t when it started
    sustained_since: dict[str, float] = field(default_factory=dict)

    # per-type confidence thresholds, raised when a human denies an event
    conf_threshold: dict[str, float] = field(default_factory=dict)

    # pending confirmation the user has been asked (one at a time)
    pending_confirmation: dict[str, Any] | None = None

    # user settings
    do_not_disturb: bool = False
    lang: str = "en"

    # rolling window of recent events (summaries only, not frames) for get_metrics_window
    recent: list[dict[str, Any]] = field(default_factory=list)
    recent_cap: int = 200

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AgentContext:
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (d or {}).items() if k in known})

    def record_recent(self, entry: dict[str, Any]) -> None:
        self.recent.append(entry)
        if len(self.recent) > self.recent_cap:
            self.recent = self.recent[-self.recent_cap:]

    def note_suppressed(self, reason: str) -> None:
        """A11 digest: count a signal we chose to stay quiet about (keeps the record)."""
        self.suppressed_digest[reason] = self.suppressed_digest.get(reason, 0) + 1

    def _within_hour(self, stamps: list[float], now_t: float) -> int:
        """Count timestamps within the last 3600 s of session time (rolling hour).

        Future stamps (s > now_t) do not count; only [now_t-3600, now_t] does.
        """
        return sum(1 for s in stamps if 0.0 <= now_t - s < 3600.0)
