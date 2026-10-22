"""Palm detection via OpenCV cv2.dnn (MediaPipe palm detector ONNX, Apache-2.0).

V7: used only for the ``drink`` behaviour (hand-near-mouth proximity). We detect
palm bounding boxes and keep their CENTRES — no 21-point hand-skeleton model, no
cup/bottle detection (unnecessary extra models). All inference is cv2.dnn on
OpenCV 5; no image is stored or returned, only coordinates.

The model (opencv_zoo palm_detection_mediapipe_2023feb) is OPTIONAL: if the file
is absent the detector reports ``available=False`` and the engine simply never
emits ``drink``. SSD anchors (2016) are generated deterministically here
(verified to match the official literal) rather than embedded.

Decode follows the official opencv_zoo demo: score = sigmoid(out[1]); box =
((delta/192) + anchor) * scale; then NMS. Input 192x192, letterboxed to keep
aspect ratio, BGR->RGB, /255.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

_INPUT = 192
_MODEL_FILE = "palm_detection_mediapipe_2023feb.onnx"
_SCORE_THR = 0.5
_NMS_THR = 0.3


@lru_cache(maxsize=1)
def _anchors() -> np.ndarray:
    """2016 SSD anchor centres (cx, cy) in 0..1. Two grids: 24x24x2 + 12x12x6.

    Generated deterministically; verified exact-equal to the opencv_zoo literal.
    """
    out = []
    for grid, count in ((24, 2), (12, 6)):
        for y in range(grid):
            cy = (y + 0.5) / grid
            for x in range(grid):
                cx = (x + 0.5) / grid
                out.extend([(cx, cy)] * count)
    return np.asarray(out, dtype=np.float32)


@dataclass
class Palm:
    """One detected palm in full-frame pixels."""
    cx: float
    cy: float
    w: float
    h: float
    score: float

    @property
    def centre(self) -> tuple[float, float]:
        return (self.cx, self.cy)


class PalmDetector:
    """Loads the palm ONNX once (if present) and returns palm centres per frame."""

    def __init__(self, models_dir: str | Path) -> None:
        self._path = Path(models_dir) / _MODEL_FILE
        self.available = self._path.exists()
        self._net = None
        self._outs: tuple[str, ...] = ()
        if self.available:
            try:
                self._net = cv2.dnn.readNet(str(self._path))
                self._outs = tuple(self._net.getUnconnectedOutLayersNames())
            except cv2.error:
                self.available = False
                self._net = None

    def detect(self, frame_bgr: np.ndarray) -> list[Palm]:
        """Return detected palms (centres) in full-frame pixel coords. [] if none
        or if the model is unavailable."""
        if not self.available or self._net is None:
            return []
        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            return []
        blob, pad, ratio = self._preprocess(frame_bgr)
        self._net.setInput(blob)
        out = self._net.forward(self._outs)
        # out may come back in either order; identify by last-dim size
        a, b = np.asarray(out[0]), np.asarray(out[1])
        box_out = a if a.shape[-1] >= 18 else b
        score_out = b if a.shape[-1] >= 18 else a
        return self._postprocess(box_out, score_out, frame_bgr.shape[1], frame_bgr.shape[0], pad, ratio)

    # -- internals ----------------------------------------------------------

    def _preprocess(self, image: np.ndarray):
        h, w = image.shape[:2]
        ratio = min(_INPUT / h, _INPUT / w)
        rw, rh = int(w * ratio), int(h * ratio)
        resized = cv2.resize(image, (rw, rh))
        pad_w, pad_h = _INPUT - rw, _INPUT - rh
        left, top = pad_w // 2, pad_h // 2
        padded = cv2.copyMakeBorder(resized, top, pad_h - top, left, pad_w - left,
                                    cv2.BORDER_CONSTANT, value=(0, 0, 0))
        blob = cv2.dnn.blobFromImage(padded, 1 / 255.0, (_INPUT, _INPUT), swapRB=True)
        # pad bias in original-image pixels (matches official demo)
        pad_bias = (np.array([left, top], dtype=np.float32) / ratio).astype(np.int32)
        return blob, pad_bias, ratio

    def _postprocess(self, box_out: np.ndarray, score_out: np.ndarray,
                     W: int, H: int, pad_bias, ratio) -> list[Palm]:
        score = score_out[0, :, 0].astype(np.float64)
        score = 1.0 / (1.0 + np.exp(-np.clip(score, -40.0, 40.0)))   # stable sigmoid
        box_delta = box_out[0, :, 0:4]
        anchors = _anchors()
        scale = float(max(W, H))

        cxy = box_delta[:, :2] / _INPUT
        wh = box_delta[:, 2:] / _INPUT
        xy1 = (cxy - wh / 2 + anchors) * scale
        xy2 = (cxy + wh / 2 + anchors) * scale
        boxes = np.concatenate([xy1, xy2], axis=1)
        boxes -= [pad_bias[0], pad_bias[1], pad_bias[0], pad_bias[1]]

        # NMS expects [x, y, w, h]
        wh_boxes = np.c_[boxes[:, 0], boxes[:, 1], boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]]
        keep = cv2.dnn.NMSBoxes(wh_boxes.tolist(), score.tolist(), _SCORE_THR, _NMS_THR)
        if len(keep) == 0:
            return []
        keep = np.array(keep).flatten()
        palms: list[Palm] = []
        for i in keep:
            x1, y1, x2, y2 = boxes[i]
            palms.append(Palm(cx=float((x1 + x2) / 2), cy=float((y1 + y2) / 2),
                              w=float(x2 - x1), h=float(y2 - y1), score=float(score[i])))
        return palms


def hand_mouth_distance(palms: list[Palm], mouth_xy: tuple[float, float],
                        face_px: float) -> float | None:
    """Min distance from any palm centre to the mouth, normalised by face height.

    Small = a hand is near the mouth. ``None`` when there is no palm or no face
    scale to normalise by (so the contract's ``hand_mouth_dist`` stays None).
    """
    if not palms or face_px <= 0:
        return None
    mx, my = mouth_xy
    best = min(((p.cx - mx) ** 2 + (p.cy - my) ** 2) ** 0.5 for p in palms)
    return float(best / face_px)
