# nunchi.vision — OpenCV 5 face/quality/landmark pipeline (V tab)

All inference runs **inside OpenCV 5** (`cv2.FaceDetectorYN` + `cv2.dnn`). No
MediaPipe/dlib/torch/onnxruntime runtime. No frame or image is ever stored,
returned, logged, or traced — only coordinate/number contracts leave this module.

## Public API (docs/CONTRACTS.md §1)

```python
from nunchi.vision import VisionEngine, SessionState, decode_jpeg, runtime_info

eng = VisionEngine("models")                 # loads YuNet + FaceMesh once
st = eng.new_session("sid")

# 1) calibrate: feed ~5 s of frontal frames (per frame)
res = eng.calibrate(st, frame_bgr, t)         # CalibrationResult(done, progress, baseline, reason)

# 2) analyze: per frame -> FrameResult (metrics + overlay); updates filters
r = eng.analyze(st, frame_bgr, t)             # r.metrics.ear/mar/head_roll_deg/..., r.overlay

# 3) active perception (agent): re-see the SAME frame, state NOT mutated
r2 = eng.analyze_variant(st, frame_bgr, t, "enhance"|"zoom_face"|"strict")

q = eng.quality(frame_bgr)                    # Quality(ok, brightness, sharpness, face_px, issues)
img = decode_jpeg(jpeg_bytes, max_side=640)   # service decode; original bytes dropped
info = runtime_info()                         # {"cv_version","backend","arch"} for /healthz
```

## Behaviour state machine (V3) — `events.py`

`analyze` now fills `FrameResult.events` (contract `Event`: `type`, `start`,
`end` (None while ongoing), `confidence` 0–1, `count`). A per-session
`BehaviorStateMachine` (inside `SessionState`, serialised) turns per-frame
metrics into time intervals. All thresholds are in one dataclass
(`events.BehaviorThresholds`) and applied **relative to the calibration
baseline** so naturally narrow eyes / wide mouths aren't mislabelled.
`filters.Hysteresis` debounces on/off edges; duration gates (`*_hold_s`) stop a
one-frame spike becoming an event.

| behaviour | signal (vs baseline) | enter / hold | supported |
|---|---|---|---|
| `away` | face absent (no landmarks) | ≥ `away_seconds` (3 s) | ✅ |
| `head_tilt` | `|roll − roll_zero|` | > 12° (exit 8°), held 1.0 s | ✅ |
| `forward_head` | `face_scale` ≥ 1.18 **or** pitch Δ ≥ 0.06 | held 1.5 s | ✅ |
| `blink` | EAR < 0.70 × `ear_open`, reopens | per closure | ✅ (under-counts, see below) |
| `deep_blink` | EAR < 0.45 × `ear_open` **or** closure held ≥ 0.7 s | — | ✅ |
| `yawn` | MAR ≥ 1.8 × `mar_rest` | held 1.2 s | ✅ |
| `drink` | palm centre near mouth (`hand_mouth_dist`), held 1.2 s | per closure | ✅ (V7, **optional** palm model) |

`confidence` scales with how far past the enter threshold the signal sits (e.g.
25° roll → ~1.0). On a no-face / low-quality / pre-calibration frame the machine
**holds** ongoing intervals (re-emitted with 0.5 confidence) but does not
*confirm* new shape-based events — only `away` can fire there. `analyze_variant`
never advances the machine and emits no events.

### `drink` (V7) — optional palm detector

`drink` uses the OpenCV Zoo **palm detector** (Apache-2.0, cv2.dnn 5.0, ~3.9MB):
the palm **centre** near the mouth, held. No cup detection, no 21-point hand
model. The model is **optional** — if `models/palm_detection_mediapipe_2023feb.onnx`
is absent, `Metrics.hand_mouth_dist` is `None`, `drink` never fires, and the rest
of vision is unaffected (`VisionEngine.drink_supported` reports availability).
SSD anchors are generated (verified against the official literal). Conservative by
design; **synthetic hands can't validate it** — real-clip only. Feasibility,
latency (+2.7ms p95), and false-positive analysis: `docs/eval/DRINK_FEASIBILITY.md`.

### Sampling limit at ≤ 2 fps (honest)

A blink is ~200 ms; at ≤ 2 fps most blinks fall **between** frames, so a
per-minute blink *rate* is unreliable. We do **not** pretend to count every
blink. Single-frame closures we happen to catch are emitted as `blink`
(an **under-count**), and instead of a rate we expose a PERCLOS-like aggregate
`BehaviorStateMachine.eyes_closed_fraction()` (closed-eye frames ÷ evaluated
frames) — a drowsiness *trend*, not an exact count. Sustained closures (held ≥
0.7 s), which low fps **can** see, surface as `deep_blink`.

### analyze_variant (for the agent's `second_look`)

| variant | what it does | use |
|---|---|---|
| `enhance` | auto-gamma (brighten from original luma) + CLAHE, then re-detect/re-estimate | dark / low-contrast frame |
| `zoom_face` | loose crop around the face + 2× upscale, re-mesh | small / far face |
| `strict` | same frame, tighter blur/face-size gates | re-judge confidence |

- **Does not mutate session state** (calibration/filters/state machine untouched;
  `frames_seen` not incremented). Returns a `FrameResult` of the same schema so
  the agent compares before/after quality & confidence. Unknown variant → `ValueError`.
- If a variant yields a worse result it is returned as-is for the agent to judge.

### overlay (web draws "what OpenCV sees")

`FrameResult.overlay` is coordinates only, **0–1 normalised** to the analysed
frame, **≤20 points** (5 key points + sparse eye/mouth contour — not the raw 478
mesh), JSON-serialisable, never pixels. `None` when no face. Web handles
mirroring/scaling.

### Face selection (V5 robustness)

The subject = the **largest** detected face, ties (within 10% area) broken toward
the frame **centre** (`landmarks.select_primary_face`), applied consistently in
`extract` / `quality` / `zoom_face`. `multiple_faces` fires only for a second
face ≥ 40% of the primary's area (`SECONDARY_MIN_AREA_RATIO`); a small background
detection (someone walking behind) does not hijack analysis, flag
`multiple_faces`, or inflate `persons` (`count_people`). Rationale and the
synthetic sweep behind it: `docs/eval/VISION_ROBUSTNESS.md`
(`eval/robustness_sweep.py`). Quality/blur/size thresholds were **not** retuned
(synthetic evidence only; real-clip tuning is a separate task).

### Tilt-robust EAR + small-face retry (V6)

- **Roll-aligned EAR** (`metrics.roll_aligned_ear`): eye points are de-rotated by
  the head roll before the aspect ratio, so a tilted head/camera doesn't inflate
  blink variance (sweep: rot10 EAR Δ 0.083→0.025, rot20 0.10→0.05). Baseline
  stores the same aligned EAR. **State schema bumped 1.0→2.0**; a pre-V6 blob is
  rejected by `SessionState.from_dict` (`ValueError`, re-calibrate).
- **Small-face retry** (`landmarks.extract_best`): if the subject face is small
  (≤48px) or missing, re-detect once on a 2× upscale and map coords back (sweep:
  face~30% detect 0.5→1.0, r160 0.75→1.0). Only fires when needed; p95 delta
  +4.4ms (normal frames unchanged). Very small faces still yield `face_too_small`.

### SessionState serialisation (Lambda restore)

`st.to_dict()` / `SessionState.from_dict(d)` round-trip a small JSON blob
(**≤8 KB**, `schema` field) carrying baseline, in-progress calibration samples,
and filter state (EMA/median/hysteresis values). A different Lambda instance
restores and continues with **identical output** (`tests/vision/test_state_roundtrip.py`).

## Measured performance (this dev Mac, arm64, 320×240)

- `analyze` (detect + mesh + metrics + overlay + events + roll-EAR + small-face
  retry + palm/drink): median ≈ **11.6 ms**, p95 ≈ **14.3 ms** (this dev Mac,
  320×240, 3-run median; palm path included). Earlier 8.7–8.9 ms figures predate
  V6 (roll-EAR, small-face retry) and V7 (palm ≈ +2.7 ms) and are superseded.
- `analyze_variant`: enhance p95 ≈ 13 ms, zoom_face ≈ 20 ms, strict ≈ 10 ms
  (all well under the 60 ms/variant target; variants skip the palm/event path).
- `enhance` on a darkened frame: brightness 37 → 135, sharpness 82 → 1272,
  `issues ['too_dark'] → []`.
- State blob ≈ 3.4 KB (behaviour state machine incl. drink latch; still ≤ 8 KB).

> Contract target **p95 < 250 ms** is on a Graviton 1-vCPU Lambda — measured by
> the C tab. These dev-Mac numbers only indicate comfortable headroom.

## Known limitation (honest)

A **synthetic** "closed eye" does not change EAR (both landmark models regress a
plausible face), so synthetic closure can't validate blink detection. Real
eye-closure is detected **relative to the per-user calibration baseline**
(open-eye EAR median / p10). This must be confirmed on **real human clips**
(U1 / V4 harness), not synthetic frames.

See `models/README.md` for the Step 0 model-selection decision table.
