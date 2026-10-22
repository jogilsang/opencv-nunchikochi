"""Per-metric stabilisation: EMA / median smoothing + hysteresis thresholding.

Why: raw landmark metrics are noisy frame-to-frame. Slow signals (roll, pitch,
face_scale) are smoothed; the fast signal (EAR for blinks) keeps a *raw* value
alongside a lightly smoothed one so a single-frame blink is not averaged away.
Hysteresis (separate enter/exit thresholds) prevents flicker at the boundary —
used by the V3 state machine, exposed here as a reusable primitive.

Pure Python/NumPy, deterministic, no image or model.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class FilterConfig:
    """Smoothing / hysteresis parameters (per metric). Tunable via dataclass."""
    ema_alpha: float = 0.4          # 0..1; higher = more responsive, less smooth
    median_window: int = 5          # odd; 1 disables median
    enter_threshold: float = 0.0    # cross below (for EAR) / above depending on sign
    exit_threshold: float = 0.0


class EmaFilter:
    """Exponential moving average. ``value`` is None until first update."""

    def __init__(self, alpha: float = 0.4) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self._alpha = alpha
        self.value: float | None = None

    def update(self, x: float) -> float:
        self.value = x if self.value is None else self._alpha * x + (1 - self._alpha) * self.value
        return self.value

    def reset(self) -> None:
        self.value = None

    def to_dict(self) -> dict:
        return {"alpha": self._alpha, "value": self.value}

    @classmethod
    def from_dict(cls, d: dict) -> EmaFilter:
        f = cls(alpha=d["alpha"])
        f.value = d.get("value")
        return f


class MedianFilter:
    """Sliding-window median; robust to single-frame spikes."""

    def __init__(self, window: int = 5) -> None:
        if window < 1 or window % 2 == 0:
            raise ValueError("window must be a positive odd integer")
        self._buf: deque[float] = deque(maxlen=window)

    def update(self, x: float) -> float:
        self._buf.append(x)
        s = sorted(self._buf)
        return s[len(s) // 2]

    def reset(self) -> None:
        self._buf.clear()

    def to_dict(self) -> dict:
        return {"window": self._buf.maxlen, "buf": list(self._buf)}

    @classmethod
    def from_dict(cls, d: dict) -> MedianFilter:
        f = cls(window=d["window"])
        f._buf.extend(d.get("buf", []))
        return f


@dataclass
class Hysteresis:
    """Two-threshold latch. ``active`` flips on at enter, off at exit.

    ``direction='below'`` (default, for EAR→eye closed): active when value drops
    below ``enter`` and stays active until it rises above ``exit`` (exit >= enter).
    ``direction='above'`` (e.g. MAR→yawn): mirror image.
    """
    enter: float
    exit: float
    direction: str = "below"
    active: bool = field(default=False)

    def update(self, value: float) -> bool:
        if self.direction == "below":
            if not self.active and value < self.enter:
                self.active = True
            elif self.active and value > self.exit:
                self.active = False
        elif self.direction == "above":
            if not self.active and value > self.enter:
                self.active = True
            elif self.active and value < self.exit:
                self.active = False
        else:
            raise ValueError("direction must be 'below' or 'above'")
        return self.active

    def reset(self) -> None:
        self.active = False

    def to_dict(self) -> dict:
        return {"enter": self.enter, "exit": self.exit, "direction": self.direction, "active": self.active}

    @classmethod
    def from_dict(cls, d: dict) -> Hysteresis:
        return cls(enter=d["enter"], exit=d["exit"], direction=d.get("direction", "below"),
                   active=d.get("active", False))


@dataclass
class StabilizedMetric:
    """Holds both a smoothed value and the latest raw value for one metric.

    For blinks, read ``raw``; for posture/tilt, read ``smoothed``.
    """
    ema: EmaFilter
    median: MedianFilter
    raw: float | None = None
    smoothed: float | None = None

    @classmethod
    def from_config(cls, cfg: FilterConfig) -> StabilizedMetric:
        return cls(ema=EmaFilter(cfg.ema_alpha), median=MedianFilter(cfg.median_window))

    def update(self, x: float) -> StabilizedMetric:
        self.raw = x
        med = self.median.update(x)
        self.smoothed = self.ema.update(med)
        return self

    def reset(self) -> None:
        self.ema.reset()
        self.median.reset()
        self.raw = None
        self.smoothed = None

    def to_dict(self) -> dict:
        return {"ema": self.ema.to_dict(), "median": self.median.to_dict(),
                "raw": self.raw, "smoothed": self.smoothed}

    @classmethod
    def from_dict(cls, d: dict) -> StabilizedMetric:
        sm = cls(ema=EmaFilter.from_dict(d["ema"]), median=MedianFilter.from_dict(d["median"]))
        sm.raw = d.get("raw")
        sm.smoothed = d.get("smoothed")
        return sm
