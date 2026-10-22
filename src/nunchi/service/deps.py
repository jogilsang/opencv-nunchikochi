"""Dependency selection. OWNER: cloud tab.

Chooses real vision/agent implementations when available, otherwise deterministic
stubs (service/stubs.py). This is explicit selection, *not* a broad try/except that
hides import errors: we probe the specific public symbols the contract defines and
fall back only when they are absent. `using_stub_*` flags are surfaced at /healthz.

No image data is handled here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .stubs import StubAgent, StubVision


def _load_vision() -> tuple[Any, bool]:
    """Return (vision_engine, using_stub). Real engine only if nunchi.vision exposes VisionEngine."""
    if os.environ.get("NUNCHI_FORCE_STUB") == "1":
        return StubVision(), True
    try:
        from nunchi.vision import VisionEngine  # type: ignore
    except ImportError:
        return StubVision(), True
    try:
        models_dir = os.environ.get("NUNCHI_MODELS_DIR", "models")
        return VisionEngine(models_dir=models_dir), False
    except Exception:  # noqa: BLE001 - intentional: any init failure (e.g. missing model) -> stub fallback
        # Real module present but not usable here (e.g. missing model files): stay on stub.
        return StubVision(), True


def _load_agent(vision: Any, use_stub_vision: bool) -> tuple[Any, bool]:
    """Return (agent, using_stub). Real agent only if nunchi.agent exposes NunchiAgent."""
    if os.environ.get("NUNCHI_FORCE_STUB") == "1":
        return StubAgent(), True
    try:
        from nunchi.agent import NunchiAgent  # type: ignore
    except ImportError:
        return StubAgent(), True
    try:
        # Pass the real vision engine only when it is real; stubs are agent-internal shape, not VisionEngine.
        return NunchiAgent(vision if not use_stub_vision else None, mode="deterministic"), False
    except Exception:  # noqa: BLE001 - intentional: any init failure -> deterministic stub fallback
        return StubAgent(), True


@dataclass
class Services:
    vision: Any
    agent: Any
    using_stub_vision: bool
    using_stub_agent: bool

    @property
    def using_stubs(self) -> bool:
        return self.using_stub_vision or self.using_stub_agent


_singleton: Services | None = None


def get_services() -> Services:
    """Process-wide singleton (built once per Lambda instance / uvicorn worker)."""
    global _singleton
    if _singleton is None:
        vision, sv = _load_vision()
        agent, sa = _load_agent(vision, sv)
        _singleton = Services(vision=vision, agent=agent, using_stub_vision=sv, using_stub_agent=sa)
    return _singleton


def reset_services() -> None:
    """Test hook: force re-selection on next get_services()."""
    global _singleton
    _singleton = None
