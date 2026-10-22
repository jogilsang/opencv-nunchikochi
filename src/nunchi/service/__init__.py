"""Nunchikochi HTTP service. OWNER: cloud tab (see docs/RULES.md).

Exposes `app` (FastAPI) for local uvicorn and `lambda_handler` (Mangum) for AWS Lambda.
Handler path for Lambda: nunchi.service.lambda_handler
"""
from __future__ import annotations

from .app import app

try:  # Mangum is in the `service` group; keep import optional so pure-unit tests need no Lambda deps.
    from mangum import Mangum

    lambda_handler = Mangum(app, lifespan="off")
except Exception:  # noqa: BLE001 - mangum optional; keep pure-unit tests importable without Lambda deps
    lambda_handler = None  # type: ignore
