"""Tests for stabilisation filters (pure logic, no model/image)."""
from __future__ import annotations

import pytest

from nunchi.vision.filters import (
    EmaFilter,
    FilterConfig,
    Hysteresis,
    MedianFilter,
    StabilizedMetric,
)


# -- normal 1: EMA converges toward a constant input --------------------------
def test_ema_converges():
    f = EmaFilter(alpha=0.5)
    for _ in range(30):
        f.update(10.0)
    assert f.value == pytest.approx(10.0, abs=1e-3)


# -- normal 2: median rejects a single spike ----------------------------------
def test_median_rejects_spike():
    f = MedianFilter(window=5)
    for v in [1.0, 1.0, 1.0, 1.0]:
        f.update(v)
    out = f.update(99.0)  # spike
    assert out == 1.0     # median of [1,1,1,1,99]


# -- normal 3: hysteresis latches (enter below, exit above) -------------------
def test_hysteresis_below_latches():
    h = Hysteresis(enter=0.2, exit=0.25, direction="below")
    assert h.update(0.30) is False     # above enter -> off
    assert h.update(0.19) is True      # drops below enter -> on
    assert h.update(0.22) is True      # between exit and enter -> stays on
    assert h.update(0.26) is False     # above exit -> off


# -- normal 4: StabilizedMetric keeps raw while smoothing ---------------------
def test_stabilized_metric_keeps_raw():
    sm = StabilizedMetric.from_config(FilterConfig(ema_alpha=0.3, median_window=3))
    sm.update(1.0); sm.update(1.0)
    sm.update(0.1)  # a blink-like dip
    assert sm.raw == 0.1               # raw preserves the fast event
    assert sm.smoothed > 0.1           # smoothed lags behind


# -- exception 1: invalid EMA alpha -------------------------------------------
def test_ema_invalid_alpha():
    with pytest.raises(ValueError):
        EmaFilter(alpha=0.0)
    with pytest.raises(ValueError):
        EmaFilter(alpha=1.5)


# -- exception 2: even median window rejected ---------------------------------
def test_median_even_window_rejected():
    with pytest.raises(ValueError):
        MedianFilter(window=4)


# -- error/edge: unknown hysteresis direction raises --------------------------
def test_hysteresis_bad_direction():
    h = Hysteresis(enter=1.0, exit=2.0, direction="sideways")
    with pytest.raises(ValueError):
        h.update(0.5)
