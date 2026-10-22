"""Label JSON schema + loader for vision evaluation.

A label file describes ONE recorded clip (or frame folder): capture conditions
and the ground-truth behaviour intervals a human performed. Faces/images are
never here — only behaviour name + start/end seconds. Schema errors raise
``ValueError`` (``LabelError``) with the offending field/line so a hand-edited
label is easy to fix (brief: "라벨 JSON 스키마 오류는 줄 번호와 함께 ValueError").

Schema (v1):
{
  "schema": "clip-labels/1",
  "clip": "c01_yawn_bright",            # base name; video is eval/clips/<clip>.*
  "fps_hint": 2.0,                      # optional, informational
  "conditions": {"light": "bright"|"dim", "angle": "frontal"|"side", ...},
  "labels": [
    {"behavior": "yawn", "start": 3.2, "end": 5.0},
    {"behavior": "away", "start": 8.0, "end": 12.0}
  ]
}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Behaviours the harness can score. Mirrors contracts.BehaviorType. ``drink`` is
# scorable from V7 (palm detector); when the palm model is absent the engine
# simply never emits it (a labelled drink would then be a false negative).
SCORABLE_BEHAVIORS: tuple[str, ...] = (
    "away", "head_tilt", "forward_head", "blink", "deep_blink", "yawn", "drink",
)
_SCHEMA = "clip-labels/1"


class LabelError(ValueError):
    """Raised on a malformed label file (carries clip/field context)."""


@dataclass
class LabelInterval:
    behavior: str
    start: float
    end: float


@dataclass
class LabelSet:
    clip: str
    conditions: dict[str, str] = field(default_factory=dict)
    fps_hint: float | None = None
    labels: list[LabelInterval] = field(default_factory=list)
    path: str = ""

    @property
    def light(self) -> str:
        return self.conditions.get("light", "unknown")

    @property
    def angle(self) -> str:
        return self.conditions.get("angle", "unknown")


def _require(cond: bool, msg: str, path: Path | str) -> None:
    if not cond:
        raise LabelError(f"{path}: {msg}")


def load_labelset(path: str | Path) -> LabelSet:
    """Load+validate one label JSON. Raises LabelError with context on any problem."""
    p = Path(path)
    if not p.exists():
        raise LabelError(f"{p}: label file not found")
    raw = p.read_text(encoding="utf-8")
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        # json already reports line/col; surface it.
        raise LabelError(f"{p}: invalid JSON at line {e.lineno} col {e.colno}: {e.msg}") from e
    return _parse(d, p, raw)


def parse_labelset(d: dict[str, Any], *, source: str = "<dict>") -> LabelSet:
    """Validate an already-parsed dict (used by tests)."""
    return _parse(d, source, None)


def _line_of(raw: str | None, needle: str) -> int | None:
    if not raw:
        return None
    for i, line in enumerate(raw.splitlines(), start=1):
        if needle in line:
            return i
    return None


def _parse(d: Any, path: Path | str, raw: str | None) -> LabelSet:
    _require(isinstance(d, dict), "top level must be a JSON object", path)
    _require(d.get("schema") == _SCHEMA, f"schema must be {_SCHEMA!r}", path)
    clip = d.get("clip")
    _require(isinstance(clip, str) and clip.strip() != "", "'clip' must be a non-empty string", path)
    conditions = d.get("conditions", {})
    _require(isinstance(conditions, dict), "'conditions' must be an object", path)
    fps_hint = d.get("fps_hint")
    _require(fps_hint is None or isinstance(fps_hint, (int, float)), "'fps_hint' must be a number", path)
    labels_raw = d.get("labels")
    _require(isinstance(labels_raw, list), "'labels' must be a list", path)

    labels: list[LabelInterval] = []
    for idx, item in enumerate(labels_raw):
        ln = _line_of(raw, '"start"') if raw else None  # best-effort
        ctx = f"labels[{idx}]" + (f" (line {ln})" if ln else "")
        _require(isinstance(item, dict), f"{ctx} must be an object", path)
        b = item.get("behavior")
        _require(b in SCORABLE_BEHAVIORS,
                 f"{ctx}: behavior {b!r} not in {SCORABLE_BEHAVIORS}", path)
        s, e = item.get("start"), item.get("end")
        _require(isinstance(s, (int, float)) and isinstance(e, (int, float)),
                 f"{ctx}: start/end must be numbers", path)
        _require(float(e) > float(s), f"{ctx}: end ({e}) must be > start ({s})", path)
        labels.append(LabelInterval(behavior=b, start=float(s), end=float(e)))

    return LabelSet(clip=clip, conditions={str(k): str(v) for k, v in conditions.items()},
                    fps_hint=float(fps_hint) if fps_hint is not None else None,
                    labels=labels, path=str(path))
