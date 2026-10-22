"""Face landmark extraction via OpenCV cv2.dnn (MediaPipe Face Mesh V2 ONNX port).

All inference is done with ``cv2.dnn`` on OpenCV 5 — no MediaPipe/dlib/torch/
onnxruntime runtime. The model (PINTO 410_FaceMeshV2, Apache-2.0) outputs 478
3D points (468 face mesh + 10 iris) in the 256x256 crop space.

Only geometry (landmark coordinates in the full-frame pixel space) leaves this
module; no image is stored or returned.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

_MESH_INPUT = 256
_MESH_POINTS = 478
_CROP_MARGIN = 1.25  # FaceMesh likes a slightly looser crop than the YuNet bbox
# V6 small-face retry: if the primary face is detected but small (height <= this,
# px at the analysed resolution), OR nothing is detected, re-run detection once on
# a 2x-upscaled frame. One extra pass, bounded latency (see VISION_ROBUSTNESS).
_SMALL_FACE_RETRY_PX = 48
_RETRY_UPSCALE = 2.0


@dataclass
class Landmarks:
    """Face landmarks in full-frame pixel coordinates.

    ``pts`` is (478, 2) float32 (x, y) in the original frame. ``bbox`` is the
    (x, y, w, h) face box used for the crop. ``ok`` is False when no face /
    mesh could be produced this frame.
    """
    ok: bool
    pts: np.ndarray | None = None
    bbox: tuple[int, int, int, int] | None = None


class LandmarkExtractor:
    """YuNet (detect) -> FaceMesh (478 landmarks) pipeline, both via OpenCV."""

    def __init__(self, models_dir: str | Path) -> None:
        self._dir = Path(models_dir)
        yunet_path = self._dir / "face_detection_yunet_2023mar.onnx"
        mesh_path = self._dir / "face_landmarks_mediapipe_2023.onnx"
        for p in (yunet_path, mesh_path):
            if not p.exists():
                raise FileNotFoundError(
                    f"model not found: {p}. Run: uv run python models/download_models.py"
                )
        self._detector = cv2.FaceDetectorYN.create(
            str(yunet_path), "", (320, 240),
            score_threshold=0.6, nms_threshold=0.3, top_k=50,
        )
        self._mesh = cv2.dnn.readNet(str(mesh_path))
        self._mesh_outs = self._mesh.getUnconnectedOutLayersNames()

    def detect_faces(self, frame_bgr: np.ndarray) -> list[np.ndarray]:
        """Return YuNet rows [x,y,w,h, 5*2 landmarks, score] for each face."""
        h, w = frame_bgr.shape[:2]
        self._detector.setInputSize((w, h))
        _, faces = self._detector.detect(frame_bgr)
        return [] if faces is None else [f for f in faces]

    def extract(self, frame_bgr: np.ndarray, face_row: np.ndarray | None = None) -> Landmarks:
        """Extract 478 landmarks for the given (or primary) face."""
        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            return Landmarks(ok=False)
        if face_row is None:
            faces = self.detect_faces(frame_bgr)
            if not faces:
                return Landmarks(ok=False)
            H, W = frame_bgr.shape[:2]
            face_row = select_primary_face(faces, W, H)

        H, W = frame_bgr.shape[:2]
        x, y, fw, fh = face_row[:4]
        cx, cy = x + fw / 2.0, y + fh / 2.0
        side = max(fw, fh) * _CROP_MARGIN
        x0 = int(max(0, cx - side / 2.0))
        y0 = int(max(0, cy - side / 2.0))
        x1 = int(min(W, x0 + side))
        y1 = int(min(H, y0 + side))
        crop = frame_bgr[y0:y1, x0:x1]
        if crop.size == 0 or crop.shape[0] < 2 or crop.shape[1] < 2:
            return Landmarks(ok=False)

        ch, cw = crop.shape[:2]
        blob = cv2.dnn.blobFromImage(
            cv2.resize(crop, (_MESH_INPUT, _MESH_INPUT)),
            scalefactor=1 / 255.0, size=(_MESH_INPUT, _MESH_INPUT), swapRB=True,
        )
        self._mesh.setInput(blob)
        mesh = None
        for o in self._mesh.forward(self._mesh_outs):
            o = np.asarray(o).flatten()
            if o.size == _MESH_POINTS * 3:
                mesh = o.reshape(_MESH_POINTS, 3)[:, :2]
                break
        if mesh is None:
            return Landmarks(ok=False)

        # mesh coords are in 256-crop space -> map back to full frame pixels
        sx = cw / float(_MESH_INPUT)
        sy = ch / float(_MESH_INPUT)
        pts = np.empty((_MESH_POINTS, 2), dtype=np.float32)
        pts[:, 0] = mesh[:, 0] * sx + x0
        pts[:, 1] = mesh[:, 1] * sy + y0
        return Landmarks(ok=True, pts=pts, bbox=(int(x), int(y), int(fw), int(fh)))

    def extract_best(self, frame_bgr: np.ndarray) -> Landmarks:
        """Extract landmarks, with ONE small-face retry on a 2x-upscaled frame (V6).

        First does the normal full-res extract. If no face is found, or the chosen
        subject face is small (height <= ``_SMALL_FACE_RETRY_PX``), re-detect on a
        2x-upscaled copy and re-extract; landmark coords are mapped back to the
        ORIGINAL frame scale so downstream geometry is unchanged. Returns whichever
        attempt detected a (larger) face. One extra pass only — bounded latency.
        """
        if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
            return Landmarks(ok=False)
        base = self.extract(frame_bgr)
        need_retry = (not base.ok) or (
            base.bbox is not None and max(base.bbox[2], base.bbox[3]) <= _SMALL_FACE_RETRY_PX
        )
        if not need_retry:
            return base
        up = cv2.resize(frame_bgr, None, fx=_RETRY_UPSCALE, fy=_RETRY_UPSCALE,
                        interpolation=cv2.INTER_CUBIC)
        faces = self.detect_faces(up)
        if not faces:
            return base
        Hs, Ws = up.shape[:2]
        prim = select_primary_face(faces, Ws, Hs)
        lm = self.extract(up, face_row=prim)
        if not lm.ok or lm.pts is None:
            return base
        # map upscaled-frame coords back to the original frame
        pts = lm.pts / _RETRY_UPSCALE
        bx, by, bw, bh = lm.bbox  # type: ignore[misc]
        bbox = (int(bx / _RETRY_UPSCALE), int(by / _RETRY_UPSCALE),
                int(bw / _RETRY_UPSCALE), int(bh / _RETRY_UPSCALE))
        # keep the retry result only if it actually found a bigger face
        if base.ok and base.bbox is not None and max(bbox[2], bbox[3]) <= max(base.bbox[2], base.bbox[3]):
            return base
        return Landmarks(ok=True, pts=pts.astype(np.float32), bbox=bbox)


# -- face selection (V5 robustness) ------------------------------------------
# The subject is the person using the app: the LARGEST face, tie-broken toward
# the frame centre. YuNet returns faces by detection score, so ``faces[0]`` could
# be a smaller/background detection (e.g. someone walking behind). Selecting by
# area+centrality keeps analysis on the subject and makes the "passing person"
# case a no-op. ``SECONDARY_MIN_AREA_RATIO`` is the area fraction (vs the primary)
# above which a second face is considered a *real* second person — below it the
# detection is background/spurious and must not raise ``multiple_faces``. These
# are tuned on the V5 synthetic sweep only (docs/eval/VISION_ROBUSTNESS.md) and
# are NOT validated performance.
SECONDARY_MIN_AREA_RATIO = 0.4   # a 2nd face >= 40% of the primary's area counts


def _area(row: np.ndarray) -> float:
    return float(row[2]) * float(row[3])


def _centre_dist2(row: np.ndarray, W: int, H: int) -> float:
    cx = float(row[0]) + float(row[2]) / 2.0
    cy = float(row[1]) + float(row[3]) / 2.0
    return (cx - W / 2.0) ** 2 + (cy - H / 2.0) ** 2


def select_primary_face(faces: list[np.ndarray], W: int, H: int) -> np.ndarray:
    """Pick the subject face: largest area, ties (within 10%) broken toward centre.

    Deterministic. ``faces`` must be non-empty (YuNet rows x,y,w,h,...,score).
    """
    if not faces:
        raise ValueError("select_primary_face called with no faces")
    biggest = max(_area(f) for f in faces)
    # candidates within 10% of the biggest area -> choose the most central
    near = [f for f in faces if _area(f) >= 0.9 * biggest]
    return min(near, key=lambda f: _centre_dist2(f, W, H))


def secondary_face_significant(faces: list[np.ndarray], primary: np.ndarray) -> bool:
    """True iff some OTHER face is at least ``SECONDARY_MIN_AREA_RATIO`` of the
    primary's area (i.e. a genuine second person, not a background/spurious box)."""
    if len(faces) < 2:
        return False
    pa = _area(primary)
    if pa <= 0:
        return len(faces) > 1
    for f in faces:
        if f is primary:
            continue
        if _area(f) >= SECONDARY_MIN_AREA_RATIO * pa:
            return True
    return False


def count_people(faces: list[np.ndarray], W: int, H: int) -> int:
    """Genuine people in frame: the subject plus faces of comparable size.
    Background/spurious small detections are not counted (V5)."""
    if not faces:
        return 0
    primary = select_primary_face(faces, W, H)
    pa = _area(primary)
    extra = 0
    for f in faces:
        if f is primary:
            continue
        if pa <= 0 or _area(f) >= SECONDARY_MIN_AREA_RATIO * pa:
            extra += 1
    return 1 + extra
