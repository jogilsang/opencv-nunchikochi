"""Shared fixtures for service tests. OWNER: cloud tab.

Tests run against the *stub* implementations by default (NUNCHI_FORCE_STUB=1) so the
service contract is verified independently of whether vision/agent are wired. A tiny
real JPEG is synthesised with OpenCV for upload paths (synthetic image, not a face;
allowed under tests/ per RULES).
"""
from __future__ import annotations

import cv2
import numpy as np
import pytest


@pytest.fixture()
def client(monkeypatch):
    # Force deterministic stubs so the HTTP contract is tested in isolation.
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    monkeypatch.delenv("NUNCHI_CORS_ORIGINS", raising=False)

    # Rebuild services and app fresh for each test (singleton reset).
    from nunchi.service import deps

    deps.reset_services()
    from fastapi.testclient import TestClient

    from nunchi.service.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
    deps.reset_services()


@pytest.fixture()
def jpeg_bytes() -> bytes:
    """A small valid JPEG (synthetic 320x240 grey frame)."""
    img = np.full((240, 320, 3), 120, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.fixture()
def make_session(client):
    def _make(lang: str = "en", date: str = "2026-10-22") -> str:
        r = client.post("/v1/sessions", json={"client_date": date, "lang": lang})
        assert r.status_code == 200, r.text
        return r.json()["session_id"]

    return _make
