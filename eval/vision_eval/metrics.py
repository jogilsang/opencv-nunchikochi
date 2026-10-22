"""Interval-overlap matching + per-behaviour precision/recall/F1 for vision eval.

The engine emits behaviour intervals (`Event` start/end); labels are ground-truth
intervals. We merge each behaviour's ongoing Events into closed predicted
intervals, then match predicted vs labelled intervals **per behaviour** by
temporal IoU with an explicit tolerance (default 0.3 — generous because start/end
are duration-gated and sampling is coarse at <=2 fps; stated in the report).

A labelled interval matched by >=1 predicted interval = TP (recall numerator).
A predicted interval matching no label = FP. A label with no match = FN. This
yields precision/recall/F1 per behaviour and a failure table (the FPs/FNs) that
the report shows as "실패 사례". No image data anywhere.

Honest: with synthetic/public inputs these numbers only prove the PIPELINE works;
real performance needs the user's labelled clips (U1). The runner marks the
report dataset accordingly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DEFAULT_IOU = 0.3


@dataclass
class Interval:
    behavior: str
    start: float
    end: float
    confidence: float = 1.0

    @property
    def dur(self) -> float:
        return max(0.0, self.end - self.start)


def iou(a: Interval, b: Interval) -> float:
    """Temporal intersection-over-union of two intervals (0 if disjoint)."""
    lo = max(a.start, b.start)
    hi = min(a.end, b.end)
    inter = max(0.0, hi - lo)
    union = (a.end - a.start) + (b.end - b.start) - inter
    return inter / union if union > 1e-9 else 0.0


def events_to_intervals(events_stream: list[tuple[float, list[dict[str, Any]]]]) -> list[Interval]:
    """Collapse a per-frame stream of Events into closed predicted intervals.

    ``events_stream`` is [(t, [event_dict,...]), ...] in frame order, where each
    event_dict has type/start/end/confidence. An ongoing event (end is None)
    opens an interval; the interval closes when (a) a matching ended Event
    arrives, or (b) the behaviour stops appearing. Confidence = max seen.
    """
    open_iv: dict[str, Interval] = {}
    out: list[Interval] = []
    seen_this_frame: set[str]
    for _t, evs in events_stream:
        seen_this_frame = set()
        for e in evs:
            b = e["type"]
            seen_this_frame.add(b)
            conf = float(e.get("confidence", 0.0) or 0.0)
            start = float(e["start"])
            end = e.get("end")
            if b not in open_iv:
                open_iv[b] = Interval(behavior=b, start=start, end=start, confidence=conf)
            iv = open_iv[b]
            iv.confidence = max(iv.confidence, conf)
            if end is not None:
                iv.end = float(end)
                out.append(iv)
                del open_iv[b]
            else:
                iv.end = max(iv.end, float(_t))
        # close intervals whose behaviour vanished this frame
        for b in list(open_iv.keys()):
            if b not in seen_this_frame:
                out.append(open_iv.pop(b))
    out.extend(open_iv.values())      # still-open at stream end
    return out


@dataclass
class BehaviorScore:
    behavior: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"behavior": self.behavior, "tp": self.tp, "fp": self.fp, "fn": self.fn,
                "precision": round(self.precision, 3), "recall": round(self.recall, 3),
                "f1": round(self.f1, 3)}


@dataclass
class Failure:
    kind: str            # "FP" (false alarm) | "FN" (miss)
    behavior: str
    start: float
    end: float
    best_iou: float
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def match_intervals(pred: list[Interval], gt: list[Interval], *, iou_thr: float = DEFAULT_IOU,
                    ) -> tuple[dict[str, BehaviorScore], list[Failure]]:
    """Per-behaviour greedy IoU matching -> scores + failure (FP/FN) list."""
    behaviors = sorted({i.behavior for i in pred} | {i.behavior for i in gt})
    scores = {b: BehaviorScore(behavior=b) for b in behaviors}
    failures: list[Failure] = []

    for b in behaviors:
        P = [i for i in pred if i.behavior == b]
        G = [i for i in gt if i.behavior == b]
        matched_g: set[int] = set()
        for p in P:
            best_j, best = -1, 0.0
            for j, g in enumerate(G):
                if j in matched_g:
                    continue
                v = iou(p, g)
                if v > best:
                    best, best_j = v, j
            if best >= iou_thr and best_j >= 0:
                scores[b].tp += 1
                matched_g.add(best_j)
            else:
                scores[b].fp += 1
                failures.append(Failure("FP", b, p.start, p.end, round(best, 3), p.confidence))
        for j, g in enumerate(G):
            if j not in matched_g:
                scores[b].fn += 1
                # best iou this label got from any predicted interval
                biou = max((iou(p, g) for p in P), default=0.0)
                failures.append(Failure("FN", b, g.start, g.end, round(biou, 3)))
    return scores, failures


@dataclass
class EvalReport:
    """One clip's evaluation outcome (JSON-serialisable; no images)."""
    clip: str
    conditions: dict[str, str] = field(default_factory=dict)
    iou_thr: float = DEFAULT_IOU
    scores: dict[str, BehaviorScore] = field(default_factory=dict)
    failures: list[Failure] = field(default_factory=list)
    face_detect_rate: float = 0.0
    frames: int = 0
    latency_ms: dict[str, float] = field(default_factory=dict)  # median/p95
    dataset: str = "unmeasured"   # "synthetic" | "public-sample" | "real-clip"

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip": self.clip, "conditions": self.conditions, "iou_thr": self.iou_thr,
            "dataset": self.dataset, "frames": self.frames,
            "face_detect_rate": round(self.face_detect_rate, 3),
            "latency_ms": self.latency_ms,
            "scores": {b: s.to_dict() for b, s in self.scores.items()},
            "failures": [f.to_dict() for f in self.failures],
        }


def score_clip(clip: str, conditions: dict[str, str], pred: list[Interval],
               gt: list[Interval], *, iou_thr: float = DEFAULT_IOU,
               face_detect_rate: float = 0.0, frames: int = 0,
               latency_ms: dict[str, float] | None = None,
               dataset: str = "unmeasured") -> EvalReport:
    scores, failures = match_intervals(pred, gt, iou_thr=iou_thr)
    return EvalReport(clip=clip, conditions=dict(conditions), iou_thr=iou_thr, scores=scores,
                      failures=failures, face_detect_rate=face_detect_rate, frames=frames,
                      latency_ms=latency_ms or {}, dataset=dataset)


def aggregate(reports: list[EvalReport]) -> dict[str, Any]:
    """Combine many clips: micro TP/FP/FN per behaviour + per-condition breakdown."""
    micro: dict[str, BehaviorScore] = {}
    by_light: dict[str, dict[str, BehaviorScore]] = {}
    for rep in reports:
        light = rep.conditions.get("light", "unknown")
        for b, s in rep.scores.items():
            m = micro.setdefault(b, BehaviorScore(behavior=b))
            m.tp += s.tp; m.fp += s.fp; m.fn += s.fn
            lb = by_light.setdefault(light, {})
            ls = lb.setdefault(b, BehaviorScore(behavior=b))
            ls.tp += s.tp; ls.fp += s.fp; ls.fn += s.fn
    return {
        "overall": {b: s.to_dict() for b, s in micro.items()},
        "by_light": {lt: {b: s.to_dict() for b, s in d.items()} for lt, d in by_light.items()},
        "clips": len(reports),
    }
