"""API-key resolution via SSM SecureString + fail-closed. OWNER: cloud tab.

Deploy reads the X-Api-Key from an SSM SecureString (NUNCHI_API_KEY_PARAM), not a
plaintext env var. These tests mock SSM with moto and assert: the key is read and
enforced; an unresolved SSM key fails CLOSED (503, not open); the direct env var still
wins for local/dev.
"""
from __future__ import annotations

import pytest


def _build_client(monkeypatch):
    monkeypatch.setenv("NUNCHI_FORCE_STUB", "1")
    monkeypatch.setenv("NUNCHI_STATE_BACKEND", "memory")
    import importlib

    app_mod = importlib.import_module("nunchi.service.app")
    from nunchi.service import deps

    app_mod._API_KEY_CACHE.clear()
    deps.reset_services()
    from fastapi.testclient import TestClient

    return TestClient(app_mod.create_app()), app_mod


# --- happy path: key read from SSM and enforced ----------------------------
def test_ssm_key_enforced(monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    monkeypatch.setenv("NUNCHI_API_KEY_PARAM", "/nunchi/api-key")

    with moto.mock_aws():
        boto3.client("ssm", region_name="us-east-1").put_parameter(
            Name="/nunchi/api-key", Value="ssm-secret", Type="SecureString"
        )
        c, _ = _build_client(monkeypatch)
        # wrong/missing key -> 401
        r = c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
        # correct key -> 200
        r = c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"},
                   headers={"X-Api-Key": "ssm-secret"})
        assert r.status_code == 200


# --- edge: direct env var wins over SSM (local/dev) ------------------------
def test_direct_env_wins(monkeypatch):
    monkeypatch.setenv("NUNCHI_API_KEY", "direct-key")
    monkeypatch.setenv("NUNCHI_API_KEY_PARAM", "/nunchi/api-key")  # should be ignored
    c, _ = _build_client(monkeypatch)
    assert c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"}).status_code == 401
    r = c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"},
               headers={"X-Api-Key": "direct-key"})
    assert r.status_code == 200


# --- error path: SSM param set but unresolved -> fail CLOSED (503) ----------
def test_ssm_unresolved_fails_closed(monkeypatch):
    moto = pytest.importorskip("moto")

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    monkeypatch.setenv("NUNCHI_API_KEY_PARAM", "/nunchi/missing")

    with moto.mock_aws():  # parameter does NOT exist -> get_parameter raises -> None -> fail closed
        c, _ = _build_client(monkeypatch)
        r = c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"},
                   headers={"X-Api-Key": "anything"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "auth_unavailable"


# --- edge: neither configured -> auth skipped (local) ----------------------
def test_no_key_configured_skips_auth(monkeypatch):
    monkeypatch.delenv("NUNCHI_API_KEY", raising=False)
    monkeypatch.delenv("NUNCHI_API_KEY_PARAM", raising=False)
    c, _ = _build_client(monkeypatch)
    assert c.post("/v1/sessions", json={"client_date": "2026-10-22", "lang": "en"}).status_code == 200
