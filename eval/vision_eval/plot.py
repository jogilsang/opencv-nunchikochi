"""Event timeline PNG (bars only, NEVER face pixels).

Draws a Gantt-style timeline: one row per behaviour, ground-truth intervals
(outlined) vs predicted intervals (filled), over the clip's time axis. Pure
drawing on a blank canvas with ``cv2`` primitives — no dependency beyond what
the project already has (no matplotlib), and crucially **no image frame is ever
read or drawn** here, only labels/predictions as coloured bars. This is the
"사람이 볼 수 있는 이벤트 타임라인 PNG (얼굴 이미지 없는 그래프만)".

If matplotlib happens to be installed it is NOT required; this cv2 renderer is
the default so the pipeline has zero extra deps and no pyproject change.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from eval.vision_eval.metrics import Interval

# behaviour -> BGR colour (distinct, colour-blind-ish safe spread)
_COLORS = {
    "away": (160, 160, 160),
    "head_tilt": (0, 170, 255),
    "forward_head": (0, 100, 255),
    "blink": (255, 180, 0),
    "deep_blink": (200, 60, 0),
    "yawn": (0, 200, 0),
}
_DEFAULT_COLOR = (200, 0, 200)


def timeline_png(out_path: str | Path, *, pred: list[Interval], gt: list[Interval],
                 clip: str, t_max: float | None = None, width: int = 900,
                 row_h: int = 44, pad: int = 70) -> str:
    """Render a predicted-vs-ground-truth timeline to a PNG. Returns the path."""
    behaviors = sorted({i.behavior for i in pred} | {i.behavior for i in gt})
    if not behaviors:
        behaviors = ["(none)"]
    if t_max is None:
        t_max = max([i.end for i in pred] + [i.end for i in gt] + [1.0])
    t_max = max(float(t_max), 1e-6)

    h = pad * 2 + row_h * len(behaviors)
    img = np.full((h, width, 3), 255, dtype=np.uint8)
    x0, x1 = pad, width - pad
    span = x1 - x0

    def X(t: float) -> int:
        return int(x0 + span * (t / t_max))

    # title + axis
    cv2.putText(img, f"timeline: {clip}", (pad, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (30, 30, 30), 1, cv2.LINE_AA)
    cv2.line(img, (x0, h - pad + 10), (x1, h - pad + 10), (120, 120, 120), 1)
    for k in range(6):
        tx = x0 + span * k // 5
        tv = t_max * k / 5
        cv2.line(img, (tx, h - pad + 6), (tx, h - pad + 14), (120, 120, 120), 1)
        cv2.putText(img, f"{tv:.0f}s", (tx - 8, h - pad + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                    (90, 90, 90), 1, cv2.LINE_AA)

    for row, b in enumerate(behaviors):
        cy = pad + row * row_h + row_h // 2
        color = _COLORS.get(b, _DEFAULT_COLOR)
        cv2.putText(img, b, (6, cy + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 40, 40), 1, cv2.LINE_AA)
        # ground truth: hollow rectangle (upper half of the row)
        for g in [i for i in gt if i.behavior == b]:
            cv2.rectangle(img, (X(g.start), cy - 16), (max(X(g.end), X(g.start) + 2), cy - 3), color, 1)
        # prediction: filled rectangle (lower half)
        for p in [i for i in pred if i.behavior == b]:
            cv2.rectangle(img, (X(p.start), cy + 3), (max(X(p.end), X(p.start) + 2), cy + 16), color, -1)

    # legend
    cv2.putText(img, "outline = label   filled = predicted", (x0, 48),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (90, 90, 90), 1, cv2.LINE_AA)

    out_path = str(out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(out_path, img)
    if not ok:
        raise OSError(f"failed to write timeline PNG: {out_path}")
    return out_path
