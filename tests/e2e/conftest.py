"""E2E fixtures: real vision + agent + service in one process. OWNER: cloud tab (E1).

These tests wire the REAL engine/agent (no NUNCHI_FORCE_STUB) against the in-memory
state store and the deterministic agent (no LLM / no AWS). If the ONNX models are
missing the real engine can't load, so we FAIL CLEARLY (not skip) with the fix command,
per the brief's exception rule.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
MODELS_DIR = REPO / "models"
SAMPLES = REPO / "tests" / "vision" / "_samples"


def pytest_configure(config):
    # Register markers locally so `-q` runs clean without editing pyproject (conductor-owned).
    config.addinivalue_line("markers", "e2e: end-to-end pipeline test (vision+agent+service)")
    config.addinivalue_line("markers", "slow: loads the real ONNX models")


def _models_present() -> tuple[bool, str]:
    manifest = MODELS_DIR / "MANIFEST.json"
    if not manifest.exists():
        return False, f"missing {manifest}"
    try:
        json.loads(manifest.read_text())
    except Exception as exc:  # noqa: BLE001
        return False, f"unreadable MANIFEST.json: {exc}"
    # Require at least the two ONNX models to exist and be non-trivial.
    onnx = list(MODELS_DIR.glob("*.onnx"))
    if len(onnx) < 2 or any(p.stat().st_size < 1024 for p in onnx):
        return False, "ONNX model files absent or truncated"
    return True, ""


@pytest.fixture(scope="session", autouse=True)
def _require_models():
    ok, why = _models_present()
    if not ok:
        pytest.fail(
            "E2E needs the real vision models. "
            "Run: uv run python models/download_models.py --check   "
            f"({why})",
            pytrace=False,
        )


def _build_real_client(monkeypatch, **env):
    """A TestClient wired to the REAL engine/agent (deterministic), in-memory store."""
    monkeypatch.delenv("NUNCHI_FORCE_STUB", raising=False)
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.setenv("NUNCHI_MODELS_DIR", str(MODELS_DIR))
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    monkeypatch.delenv("NUNCHI_API_KEY_PARAM", raising=False)
    monkeypatch.delenv("NUNCHI_CORS_ORIGINS", raising=False)
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, str(v))
    from nunchi.service import deps

    deps.reset_services()
    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app

    return deps, TestClient(create_app())


@pytest.fixture()
def real_client(monkeypatch):
    deps, client = _build_real_client(monkeypatch)
    with client as c:
        # Prove we are on the REAL path, not stubs — the whole point of E1.
        h = c.get("/healthz").json()
        assert h["stubs"] is False, f"expected real engine, got stubs: {h}"
        yield c
    deps.reset_services()


@pytest.fixture()
def stub_client(monkeypatch):
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    from nunchi.service import deps

    deps.reset_services()
    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app

    with TestClient(create_app()) as c:
        yield c
    deps.reset_services()


@pytest.fixture()
def dark_jpeg() -> bytes:
    """A too-dark, no-face frame — drives the bad-quality / second_look path."""
    img = np.full((240, 320, 3), 12, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.fixture()
def face_jpeg() -> bytes:
    """A real face sample (committed) — drives the metrics / happy path."""
    p = SAMPLES / "messi5.jpg"
    assert p.exists(), f"missing sample {p}"
    return p.read_bytes()
