"""Shared data contracts. OWNER: conductor (Claude). Change only via the conductor (see docs/RULES.md).

Everything crossing a component boundary is one of these types and is JSON-serialisable via `to_dict()`.
No image data ever appears in any contract type (privacy: frames are never persisted or returned).
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional

SCHEMA_VERSION = "1.0"

BehaviorType = Literal["away", "head_tilt", "forward_head", "blink", "deep_blink", "yawn", "drink"]
ActionType = Literal["none", "nudge", "request_recalibration", "ask_confirmation", "suppress_focus"]
QualityIssue = Literal["too_dark", "too_bright", "blurry", "face_too_small", "face_cut_off", "no_face", "multiple_faces"]


@dataclass
class Quality:
    """Per-frame input quality, computed by OpenCV. Drives agent decisions (e.g. ask for light)."""
    ok: bool = True
    brightness: float = 0.0          # mean luma 0-255
    sharpness: float = 0.0           # variance of Laplacian
    face_px: int = 0                 # face bbox height in pixels at analysed resolution
    issues: List[QualityIssue] = field(default_factory=list)


@dataclass
class Metrics:
    """Geometric measurements. Unitless or degrees; None = could not be measured this frame."""
    ear: Optional[float] = None              # eye aspect ratio (mean of both eyes)
    mar: Optional[float] = None              # mouth aspect ratio
    head_roll_deg: Optional[float] = None    # head tilt in the image plane
    head_pitch_proxy: Optional[float] = None # forward/down proxy relative to calibration (0 = baseline)
    face_scale: Optional[float] = None       # face height / calibrated face height (>1 = closer to screen)
    shoulder_ear_ratio: Optional[float] = None
    hand_mouth_dist: Optional[float] = None  # normalised by face height; small = hand near mouth


@dataclass
class Event:
    """A behaviour interval (start/end are session-relative seconds). `end` is None while ongoing."""
    type: BehaviorType
    start: float
    end: Optional[float] = None
    confidence: float = 0.0
    count: int = 1


@dataclass
class FrameResult:
    """Output of `nunchi.vision.analyze`. The only vision→rest-of-system payload."""
    schema: str = SCHEMA_VERSION
    session_id: str = ""
    t: float = 0.0                           # session-relative seconds
    face_present: bool = False
    persons: int = 0
    metrics: Metrics = field(default_factory=Metrics)
    quality: Quality = field(default_factory=Quality)
    events: List[Event] = field(default_factory=list)       # events started/ended/ongoing at this frame
    calibrated: bool = False
    latency_ms: float = 0.0                  # vision wall time for this frame
    backend: str = "opencv"                  # "opencv" | "cool" (set from runtime evidence, not config claims)
    cv_version: str = ""
    overlay: Optional[Dict[str, Any]] = None  # display-only geometry, NEVER pixels: {"face":[x,y,w,h], "points":{"eye_l":[x,y],...}, "pose":{...}} in 0-1 image coords; not persisted

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Decision:
    """Output of `nunchi.agent.decide`. `trace` explains which visual evidence changed the action."""
    action: ActionType = "none"
    message: str = ""                        # user-facing text (EN primary, KO optional via `message_ko`)
    message_ko: str = ""
    reason: str = ""                         # short machine-readable reason, e.g. "quality:too_dark"
    needs_human: bool = False                # human-in-the-loop requested
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)   # [{"tool","args","result_summary"}]
    evidence: Dict[str, Any] = field(default_factory=dict)           # the metrics/events that drove this
    cooldown_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SessionSummary:
    """Aggregates only. This (plus nothing else) is persisted."""
    session_id: str
    date: str                                # YYYY-MM-DD (user local date supplied by client)
    duration_s: float = 0.0
    counts: Dict[str, int] = field(default_factory=dict)             # behaviour -> count
    seconds: Dict[str, float] = field(default_factory=dict)          # behaviour -> accumulated seconds
    longest_s: Dict[str, float] = field(default_factory=dict)
    nudges_sent: int = 0
    nudges_suppressed: int = 0
    confirmations_asked: int = 0
    recalibrations: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def now_ms() -> int:
    return int(time.time() * 1000)
