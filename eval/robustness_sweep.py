#!/usr/bin/env python3
"""눈치코치 견고성 스윕 (V5).

실사용 왜곡(웹캠 JPEG 압축, 어두움/역광, 블러, 잡음, 해상도, 회전, 얼굴 크기, 부분
가림, 다중 얼굴)을 공개 샘플에 입혀 엔진이 어디서 약한지 **측정으로** 드러낸다. 실제
클립이 없으므로 "공개 샘플 + 합성 변환"이며, 수치는 실제 성능이 아니라 **구조적 약점
탐지**용이다(리포트에 명시). 지표: 얼굴 검출률, 랜드마크 안정성(프레임 간 변동),
EAR/MAR 변동, quality 점수와 실제 검출의 상관, 지연.

사용:
    uv run python eval/robustness_sweep.py --out docs/eval/robustness
    uv run python eval/robustness_sweep.py --self-test     # 모델/샘플 없이 변환함수만 확인

안경은 합성으로 흉내 내지 않는다(공개 안경 샘플이 없으면 "미측정").
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

SAMPLES = _REPO / "tests" / "vision" / "_samples"
MODELS = _REPO / "models"

# public OpenCV face samples already cached by the test suite
_FACE_SAMPLES = ("lena.jpg", "messi5.jpg", "largest_selfie.jpg", "basketball1.png")


# -- transforms (deterministic) ----------------------------------------------

def t_jpeg(img: np.ndarray, quality: int) -> np.ndarray:
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR) if ok else img


def t_brightness(img: np.ndarray, delta: int) -> np.ndarray:
    return cv2.convertScaleAbs(img, alpha=1.0, beta=float(delta))


def t_gamma(img: np.ndarray, g: float) -> np.ndarray:
    inv = 1.0 / max(1e-3, g)
    lut = np.array([((i / 255.0) ** inv) * 255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(img, lut)


def t_gauss_blur(img: np.ndarray, k: int) -> np.ndarray:
    k = max(1, int(k) | 1)
    return cv2.GaussianBlur(img, (k, k), 0)


def t_motion_blur(img: np.ndarray, k: int) -> np.ndarray:
    k = max(2, int(k))
    kernel = np.zeros((k, k), np.float32)
    kernel[k // 2, :] = 1.0 / k
    return cv2.filter2D(img, -1, kernel)


def t_salt_pepper(img: np.ndarray, amount: float) -> np.ndarray:
    rng = np.random.default_rng(1234)              # deterministic
    out = img.copy()
    n = int(amount * img.shape[0] * img.shape[1])
    ys = rng.integers(0, img.shape[0], n); xs = rng.integers(0, img.shape[1], n)
    out[ys[: n // 2], xs[: n // 2]] = 255
    out[ys[n // 2:], xs[n // 2:]] = 0
    return out


def t_resolution(img: np.ndarray, long_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    s = long_side / float(max(h, w))
    return cv2.resize(img, (max(1, round(w * s)), max(1, round(h * s))),
                      interpolation=cv2.INTER_AREA)


def t_rotate(img: np.ndarray, deg: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(img, m, (w, h), borderValue=(127, 127, 127))


def t_occlude_mouth(img: np.ndarray) -> np.ndarray:
    out = img.copy(); h, w = img.shape[:2]
    cv2.rectangle(out, (int(w * 0.3), int(h * 0.62)), (int(w * 0.7), int(h * 0.82)), (90, 90, 90), -1)
    return out


def t_occlude_eye(img: np.ndarray) -> np.ndarray:
    out = img.copy(); h, w = img.shape[:2]
    cv2.rectangle(out, (int(w * 0.3), int(h * 0.30)), (int(w * 0.52), int(h * 0.45)), (90, 90, 90), -1)
    return out


def compose_background_face(primary: np.ndarray, secondary: np.ndarray, scale: float) -> np.ndarray:
    """'뒤에 지나가는 사람': primary 얼굴 프레임의 구석에 작게 축소한 secondary를 합성."""
    out = primary.copy(); H, W = out.shape[:2]
    sm = cv2.resize(secondary, (max(2, int(W * scale)), max(2, int(H * scale))))
    sh, sw = sm.shape[:2]
    out[0:sh, W - sw:W] = sm                       # top-right corner
    return out


_SWEEP = {
    "jpeg_quality": [("q90", t_jpeg, 90), ("q70", t_jpeg, 70), ("q50", t_jpeg, 50), ("q30", t_jpeg, 30)],
    "brightness":   [("dark-80", t_brightness, -80), ("dark-40", t_brightness, -40),
                     ("bright+60", t_brightness, 60)],
    "gamma":        [("g0.5", t_gamma, 0.5), ("g2.0", t_gamma, 2.0)],
    "gauss_blur":   [("gb3", t_gauss_blur, 3), ("gb7", t_gauss_blur, 7), ("gb13", t_gauss_blur, 13)],
    "motion_blur":  [("mb9", t_motion_blur, 9), ("mb17", t_motion_blur, 17)],
    "noise":        [("sp0.02", t_salt_pepper, 0.02), ("sp0.08", t_salt_pepper, 0.08)],
    "resolution":   [("r160", t_resolution, 160), ("r320", t_resolution, 320), ("r640", t_resolution, 640)],
    "rotation":     [("rot10", t_rotate, 10), ("rot20", t_rotate, 20), ("rot30", t_rotate, 30)],
    "occlusion":    [("occ-mouth", t_occlude_mouth, None), ("occ-eye", t_occlude_eye, None)],
}


def _available_faces() -> list[Path]:
    return [SAMPLES / n for n in _FACE_SAMPLES if (SAMPLES / n).exists()]


def _analyze_once(engine, img) -> dict:
    st = engine.new_session("sweep")
    # calibrate on the clean-ish frame itself so EAR/MAR deltas are meaningful
    for i in range(20):
        engine.calibrate(st, img, t=i * 0.3)
    t0 = time.perf_counter()
    r = engine.analyze(st, img, t=100.0)
    lat = (time.perf_counter() - t0) * 1000.0
    q = r.quality
    return {
        "face_present": bool(r.face_present), "persons": int(r.persons),
        "ear": r.metrics.ear, "mar": r.metrics.mar, "roll": r.metrics.head_roll_deg,
        "q_ok": bool(q.ok), "q_issues": list(q.issues),
        "brightness": q.brightness, "sharpness": q.sharpness, "face_px": q.face_px,
        "latency_ms": round(lat, 2),
    }


def _landmark_jitter(engine, img, reps: int = 3) -> float | None:
    """Stability: mean per-point std over repeated extracts of the SAME frame.
    (model is deterministic, so >0 only if detection path is unstable)."""
    pts = []
    for _ in range(reps):
        lm = engine._extract(img)
        if lm and lm.ok and lm.pts is not None:
            pts.append(lm.pts)
    if len(pts) < 2:
        return None
    arr = np.stack(pts, axis=0)
    return float(np.mean(np.std(arr, axis=0)))


def run(out_dir: Path) -> dict:
    from nunchi.vision import VisionEngine
    faces = _available_faces()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not faces:
        summary = {"status": "no-samples", "note": "공개 얼굴 샘플 없음 → 전부 미측정",
                   "families": {}}
        (out_dir / "robustness.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
        print("[미측정] 공개 얼굴 샘플이 없어 스윕을 건너뜁니다.")
        return summary
    engine = VisionEngine(str(MODELS))

    families: dict[str, list[dict]] = {}
    # baseline per sample (clean)
    base = {}
    for fp in faces:
        img = cv2.imread(str(fp))
        img = t_resolution(img, 480)
        base[fp.name] = _analyze_once(engine, img)

    for fam, variants in _SWEEP.items():
        rows = []
        for label, fn, arg in variants:
            det = 0; n = 0; eardelta = []; lats = []; q_flags = {}
            correlated = 0
            for fp in faces:
                img = t_resolution(cv2.imread(str(fp)), 480)
                tried = fn(img) if arg is None else fn(img, arg)
                res = _analyze_once(engine, tried)
                n += 1
                det += 1 if res["face_present"] else 0
                # quality-vs-truth correlation: does q_ok agree with face_present?
                if res["q_ok"] == res["face_present"]:
                    correlated += 1
                for iss in res["q_issues"]:
                    q_flags[iss] = q_flags.get(iss, 0) + 1
                b = base[fp.name]
                if res["ear"] is not None and b["ear"] is not None:
                    eardelta.append(abs(res["ear"] - b["ear"]))
                lats.append(res["latency_ms"])
            rows.append({
                "variant": label,
                "detect_rate": round(det / n, 3) if n else 0.0,
                "ear_delta_mean": round(statistics.mean(eardelta), 4) if eardelta else None,
                "q_truth_agree": round(correlated / n, 3) if n else 0.0,
                "q_issues": q_flags,
                "latency_median_ms": round(statistics.median(lats), 2) if lats else None,
            })
        families[fam] = rows

    # face-size sweep (shrink the face within a padded canvas)
    families["face_size"] = _face_size_sweep(engine, faces)
    # multiple-faces / passing-person
    families["multi_face"] = _multiface_sweep(engine, faces, base)
    # landmark stability
    jit = [_landmark_jitter(engine, t_resolution(cv2.imread(str(fp)), 480)) for fp in faces]
    jit = [j for j in jit if j is not None]
    families["_landmark_jitter_px"] = [{"mean_std_px": round(statistics.mean(jit), 4) if jit else None,
                                        "samples": len(jit)}]

    summary = {"status": "measured-synthetic", "samples": [f.name for f in faces],
               "note": "공개 샘플+합성 변환. 실제 성능 아님 — 구조적 약점 탐지용.",
               "glasses": "미측정(공개 안경 샘플 없음, 합성 흉내 금지)",
               "families": families}
    (out_dir / "robustness.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                             encoding="utf-8")
    _print(summary)
    return summary


def _face_size_sweep(engine, faces) -> list[dict]:
    rows = []
    for frac in (0.6, 0.3, 0.15, 0.08):
        det = 0; n = 0; pxs = []
        for fp in faces:
            img = t_resolution(cv2.imread(str(fp)), 480)
            H, W = img.shape[:2]
            fw = max(8, int(W * frac))
            small = cv2.resize(img, (fw, int(H * frac)))
            canvas = np.full((H, W, 3), 127, np.uint8)
            canvas[0:small.shape[0], 0:small.shape[1]] = small
            res = _analyze_once(engine, canvas)
            n += 1; det += 1 if res["face_present"] else 0
            if res["face_px"]:
                pxs.append(res["face_px"])
        rows.append({"variant": f"face~{int(frac*100)}%", "detect_rate": round(det / n, 3) if n else 0.0,
                     "face_px_mean": round(statistics.mean(pxs), 1) if pxs else 0})
    return rows


def _multiface_sweep(engine, faces, base) -> list[dict]:
    """'뒤에 지나가는 사람': 주 얼굴 + 구석의 작은 얼굴. 주 얼굴이 계속 선택되는지."""
    rows = []
    if len(faces) < 2:
        return [{"variant": "n/a", "note": "얼굴 샘플 2개 미만 → 미측정"}]
    primary = t_resolution(cv2.imread(str(faces[0])), 480)
    secondary = t_resolution(cv2.imread(str(faces[1])), 480)
    b = base[faces[0].name]
    for sc in (0.25, 0.4):
        comp = compose_background_face(primary, secondary, sc)
        res = _analyze_once(engine, comp)
        # EAR near the primary's baseline => primary face was analysed (not hijacked)
        ear_ok = (res["ear"] is not None and b["ear"] is not None
                  and abs(res["ear"] - b["ear"]) < 0.08)
        rows.append({"variant": f"bg-face~{int(sc*100)}%", "persons": res["persons"],
                     "q_issues": res["q_issues"], "primary_kept": bool(ear_ok)})
    return rows


def _print(summary: dict) -> None:
    print("\n== 견고성 스윕 (합성 — 약점 탐지용) ==")
    for fam, rows in summary["families"].items():
        print(f"\n[{fam}]")
        for r in rows:
            print("  " + json.dumps(r, ensure_ascii=False))


def self_test() -> int:
    """모델/샘플 없이 변환 함수의 형태/결정성만 확인."""
    img = np.full((240, 320, 3), 100, np.uint8)
    cv2.circle(img, (160, 120), 40, (200, 200, 200), -1)
    for fn, arg in [(t_jpeg, 50), (t_brightness, -40), (t_gamma, 0.5), (t_gauss_blur, 7),
                    (t_motion_blur, 9), (t_salt_pepper, 0.05), (t_resolution, 160), (t_rotate, 20)]:
        o = fn(img, arg)
        assert o is not None and o.ndim == 3, f"{fn.__name__} bad output"
    a = t_salt_pepper(img, 0.05); b = t_salt_pepper(img, 0.05)
    assert np.array_equal(a, b), "salt-pepper must be deterministic"
    assert t_occlude_mouth(img).shape == img.shape
    print("[self-test] 변환 함수 OK (결정성·형태 확인)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="눈치코치 견고성 스윕")
    ap.add_argument("--out", default="docs/eval/robustness")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    run(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
