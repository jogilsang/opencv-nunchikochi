# Vision models (V tab)

All inference runs **inside OpenCV 5** (`cv2.FaceDetectorYN` for detection,
`cv2.dnn.readNet` for landmarks). No MediaPipe / dlib / torch / onnxruntime
runtime. Model binaries are **gitignored** (`models/*.onnx`); `MANIFEST.json`
(name · url/archive · sha256 · bytes · license) is the source of truth and
`download_models.py` reproduces them on a fresh machine.

## Download / verify

```bash
uv run python models/download_models.py          # fetch missing or changed models
uv run python models/download_models.py --check  # verify sha256 only (no network)
uv run python models/download_models.py --force  # re-download everything
```

Re-run safe (sha256-matching files are left untouched). The landmark model ships
inside a PINTO tarball, so its manifest entry uses `archive_url` + `archive_member`
and the downloader extracts just that one file. Exit code is non-zero if a
**required** model is missing.

## Selected models

| model | role | license | input / output | file · size | why |
|---|---|---|---|---|---|
| **YuNet** `face_detection_yunet_2023mar` | face **detection** (+5-pt) | **MIT** (Shiqi Yu) | dynamic (`setInputSize`); demo 320×240 | 232,589 B | fast, native `cv2.FaceDetectorYN` on OpenCV 5; gives bbox + face count + crop for the mesh stage. |
| **FaceMesh V2** `face_landmarks_mediapipe_2023` | **478-pt** face landmarks (468 mesh + 10 iris) → EAR/MAR/roll/pitch/face_scale | **Apache-2.0** (Google MediaPipe Face Mesh; ONNX port via PINTO) | 256×256 BGR→RGB /255; output `(1,1,1,1434)`=478×3 | dense eyelid/lip points needed for blink (EAR) and yawn (MAR). Loads and runs via `cv2.dnn` on OpenCV 5.0.0. |
| **Palm** `palm_detection_mediapipe_2023feb` (V7) | palm bbox (SSD, 2016 anchors) → hand-near-mouth for `drink` | **Apache-2.0** (opencv_zoo) | 192×192 BGR→RGB /255; `(1,2016,18)`+`(1,2016,1)` | **OPTIONAL** (`required:false`): absent → `drink` never fires, rest unaffected. 3,905,734 B. Anchors generated (not embedded), verified vs official literal. See `docs/eval/DRINK_FEASIBILITY.md`. |

### Step 0 decision (landmark model) — measured, not assumed

The biggest V2 risk was the eye/mouth landmark model. Candidates were evaluated
on **OpenCV 5.0 `cv2.dnn` load**, **licence**, **latency**, and whether **EAR
reflects eye shape**:

| candidate | loads on cv2.dnn 5.0 | license | latency (crop+infer, this Mac) | EAR behaviour | verdict |
|---|---|---|---|---|---|
| **FaceMesh V2** (PINTO 410) | ✅ 478 pts | **Apache-2.0** | ~9 ms | open-eye EAR spans **0.16–0.49** across faces (reflects eye openness) | **SELECTED** |
| face_landmark 68-pt (PINTO 043) | ✅ 68 pts | Apache-2.0 | ~5.5 ms | open-eye EAR stuck at **0.15–0.18** (insensitive) | rejected (poor eye sensitivity) |
| InsightFace 2d106det | (not tested) | **non-commercial research only** | — | — | **rejected (licence)** |
| YuNet 5-pt + eye ROI (fallback ⑤) | ✅ | MIT | fast | crude open/close heuristic | fallback only |

Note: a *synthetic* "closed eye" (squashing the eye band) does **not** change EAR
for either landmark model — both regress a plausible face, so synthetic closure
is not a valid test. Real eye-closure detection is done **relative to the
per-user calibration baseline** (median open-eye EAR), which is the design
intent; the raw EAR range above confirms the model tracks eye shape.

There is **no standalone 68/5-pt face-landmark model in OpenCV Zoo**, and contrib
Facemark LBF is unavailable (`hasattr(cv2,"face")==False` on
`opencv-python-headless==5.0.0.93`), so an external ONNX (FaceMesh) is required —
still executed only through `cv2.dnn`.

## Metrics & stabilisation

- `metrics.py`: EAR (eyelid points), MAR (lip points), head roll (eye line),
  pitch proxy (nose vs eye line / face height), face_scale (face height ÷
  calibrated baseline). `face_scale` is `None` until calibration.
- `calibration.py`: 5-second frontal calibration fixes a per-user baseline
  (open-eye EAR median, resting MAR, face px, frontal pitch, roll zero); bad
  frames (no face / low quality) are rejected and retryable.
- `filters.py`: EMA + median smoothing and hysteresis (separate enter/exit
  thresholds). Slow metrics (roll/pitch/scale) are smoothed; EAR/MAR keep the
  **raw** value too so a fast blink is not averaged away.

## Runtime (measured, not estimated)

`cv2.__version__ == 5.0.0`, Python 3.12.13, arm64 (NEON FP16). Per-frame wall
time at **320×240** over public OpenCV samples (`eval/v2_bench.json`):

- `analyze` (YuNet + FaceMesh + metrics + overlay + events + roll-EAR + small-face
  retry + palm/drink): **median ≈ 11.6 ms, p95 ≈ 14.3 ms** (3-run median). The
  earlier 8.7/9.4 ms were V4-era (before V6 roll-EAR/small-face retry and V7's
  palm path ≈ +2.7 ms) and are superseded.
- `analyze_variant` (active perception): enhance p95 ≈ 13 ms, zoom_face ≈ 20 ms,
  strict ≈ 10 ms — all under the 60 ms/variant target.
- `enhance` on a darkened frame: brightness 37 → 135, sharpness 82 → 1272,
  `issues ['too_dark'] → []`.
- EAR tracks eye shape (e.g. lena 0.40, largest_selfie 0.22); 4/4 face images
  detected, 8/8 non-face → 0 (no false positives).
- `SessionState` JSON blob ≈ 3.4 KB (≤ 8 KB); round-trip restore gives identical
  output (`tests/vision/test_state_roundtrip.py`).

> Dev-machine numbers. The contract's **p95 < 250 ms** target is on a Graviton
> 1-vCPU Lambda and will be measured with the **C (cloud)** tab. Large headroom
> here suggests the target is comfortable, but must be confirmed on arm64 Lambda.

## Sources

- OpenCV Zoo (YuNet): https://github.com/opencv/opencv_zoo
- PINTO model zoo (FaceMesh V2 ONNX): https://github.com/PINTO0309/PINTO_model_zoo (`410_FaceMeshV2`, Apache-2.0)
- Google MediaPipe Face Mesh (original model): Apache-2.0
- OpenCV 5 docs: https://docs.opencv.org/
