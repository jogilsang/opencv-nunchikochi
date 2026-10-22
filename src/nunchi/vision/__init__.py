"""nunchi.vision — OpenCV 5 face/quality/landmark pipeline (V tab). See docs/RULES.md.

Public API (contract, docs/CONTRACTS.md §1):
    VisionEngine (new_session, calibrate, quality, analyze, analyze_variant),
    SessionState (to_dict/from_dict), decode_jpeg, runtime_info
Vision-internal types (not contracts): Baseline, CalibrationResult, FilterConfig.
"""
from __future__ import annotations

from nunchi.vision.calibration import Baseline, CalibrationResult
from nunchi.vision.engine import SessionState, VisionEngine, runtime_info
from nunchi.vision.filters import FilterConfig
from nunchi.vision.io import DecodeError, decode_jpeg

__all__ = [
    "Baseline",
    "CalibrationResult",
    "DecodeError",
    "FilterConfig",
    "SessionState",
    "VisionEngine",
    "decode_jpeg",
    "runtime_info",
]
