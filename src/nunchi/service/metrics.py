"""CloudWatch EMF metrics for the service. OWNER: cloud tab.

Emits the Embedded Metric Format (EMF) as a single JSON line on stdout; CloudWatch Logs
parses it into metrics automatically (no PutMetricData call, no extra IAM). See AWS docs:
https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html

PRIVACY (docs/RULES.md): metrics are numbers + low-cardinality labels only. We NEVER put
image bytes, raw response bodies, API keys, headers, or session ids into a metric or its
dimensions. `decision` / `error_code` are bounded enum-like strings, safe as dimensions.

Namespace `nunchikochi`. Metrics:
- FrameLatencyMs (ms)   — vision wall time per frame
- Decisions (count)     — dimension Decision=<action>
- Errors (count)        — dimension ErrorCode=<code>
- Sessions (count)      — dimension Event=create|end
- RateLimited (count)   — server-side throttle hits
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

NAMESPACE = "nunchikochi"
_ENABLED = os.environ.get("NUNCHI_METRICS", "1") != "0"


def _emit(metrics: list[dict[str, Any]], dimensions: dict[str, str], values: dict[str, float]) -> None:
    """Write one EMF record to stdout. Best-effort: never raise into the request path."""
    if not _ENABLED:
        return
    try:
        doc: dict[str, Any] = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": NAMESPACE,
                        "Dimensions": [list(dimensions.keys())] if dimensions else [[]],
                        "Metrics": metrics,
                    }
                ],
            },
        }
        doc.update(dimensions)
        doc.update(values)
        sys.stdout.write(json.dumps(doc, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001, S110 - metrics are best-effort; never break the request path
        pass


def frame_processed(latency_ms: float, decision: str) -> None:
    """One analysed frame: latency + which decision the agent took."""
    _emit(
        metrics=[
            {"Name": "FrameLatencyMs", "Unit": "Milliseconds"},
            {"Name": "Decisions", "Unit": "Count"},
        ],
        dimensions={"Decision": str(decision or "none")},
        values={"FrameLatencyMs": float(latency_ms), "Decisions": 1},
    )


def error(error_code: str) -> None:
    """A request failed with a known error code (never the message/body)."""
    _emit(
        metrics=[{"Name": "Errors", "Unit": "Count"}],
        dimensions={"ErrorCode": str(error_code)},
        values={"Errors": 1},
    )


def rate_limited() -> None:
    """Server-side per-session frame-rate throttle fired."""
    _emit(
        metrics=[{"Name": "RateLimited", "Unit": "Count"}],
        dimensions={},
        values={"RateLimited": 1},
    )


def session_event(event: str) -> None:
    """Session lifecycle: create | end."""
    _emit(
        metrics=[{"Name": "Sessions", "Unit": "Count"}],
        dimensions={"Event": str(event)},
        values={"Sessions": 1},
    )
