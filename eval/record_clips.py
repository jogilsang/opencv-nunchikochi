#!/usr/bin/env python3
"""눈치코치 라벨 클립 녹화 도구 (V4, 로컬 전용).

웹캠(OpenCV VideoCapture)으로, 안내에 따라 행동을 연출하며 10~20초짜리 라벨 클립을
찍는다. 영상은 **로컬에만** 저장(eval/clips/, .gitignore)되고, 라벨은 같은 이름의
JSON(eval/clips/<clip>.labels.json: behavior/start/end)으로 분리 저장된다.
업로드·전송 코드는 없다. 밝은 환경 1세트 + 어두운 환경 1세트를 권장한다(U1).

사용:
    uv run python eval/record_clips.py --dry-run          # 카메라 없이 계획만 출력
    uv run python eval/record_clips.py --light bright      # 실제 녹화(밝은 환경 세트)
    uv run python eval/record_clips.py --light dim --out eval/clips

카메라가 없거나 권한이 없으면 macOS 권한 안내를 출력하고 종료한다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path


# A fixed, easy-to-perform script. Each entry: behaviour label, seconds, 한국어 안내.
# "normal" 구간은 라벨에 넣지 않는다(정상은 '이벤트 없음'이 정답).
@dataclass
class Shot:
    clip_suffix: str
    behavior: str | None   # None == 정상(라벨 없음)
    seconds: int
    instruction: str


SCRIPT: list[Shot] = [
    Shot("normal", None, 12, "평소처럼 화면을 바라보며 자연스럽게 작업하는 척 하세요."),
    Shot("away", "away", 14, "중간에 자리에서 일어나 5초 이상 화면 밖으로 벗어났다가 돌아오세요."),
    Shot("head_tilt", "head_tilt", 14, "고개를 한쪽으로 15도 이상 기울인 채 몇 초간 유지하세요."),
    Shot("forward_head", "forward_head", 14, "거북목처럼 머리를 화면 쪽으로 쭉 내밀어 가까이 가세요(몇 초 유지)."),
    Shot("blink", "blink", 12, "평소보다 또렷하게 여러 번 깜빡이세요(각 깜빡임을 분명히)."),
    Shot("deep_blink", "deep_blink", 14, "눈을 1초 이상 지그시 감았다 뜨기를 3회 반복하세요."),
    Shot("yawn", "yawn", 14, "입을 크게 벌려 하품을 2~3회 하세요(각 2초 이상)."),
    Shot("drink", "drink", 16, "컵이나 물병을 손에 들고 입으로 가져가 마시는 동작을 3회 하세요(한 번에 2초 이상, 손이 입 높이까지 올라오게)."),
    # 아래 셋은 '이벤트가 나오면 안 되는' 오탐 점검용 음성(negative) 클립입니다.
    # 정답은 '이벤트 없음'이므로 behavior=None(라벨 비움). 평가에서 drink/forward_head/
    # deep_blink 오탐이 이 구간에 찍히면 그대로 오탐으로 집계됩니다.
    Shot("typing", None, 30, "손을 키보드에 두고 30초간 평소처럼 타자만 치세요(물·턱 괴기 없이). drink가 뜨면 안 됩니다."),
    Shot("chin_rest", None, 10, "한 손으로 턱을 괸 채 10초간 가만히 화면을 보세요(손을 움직이지 말 것). drink가 뜨면 안 됩니다."),
    Shot("look_down_keyboard", None, 14, "고개를 숙여 키보드를 10초 이상 내려다보세요(졸거나 눈 감지 말 것). deep_blink가 뜨면 안 됩니다. forward_head는 자세 신호로 뜰 수 있습니다."),
]


def macos_permission_hint() -> str:
    return (
        "카메라를 열 수 없습니다. macOS라면 시스템 설정 > 개인정보 보호 및 보안 > "
        "카메라에서 터미널(또는 이 앱)에 권한을 허용했는지 확인하세요. "
        "다른 앱이 카메라를 점유 중이면 종료 후 다시 시도하세요."
    )


def plan(light: str) -> list[dict]:
    """세트 계획(dry-run에서 출력, 실제 녹화에서도 동일 순서)."""
    out = []
    for s in SCRIPT:
        out.append({
            "clip": f"{s.clip_suffix}_{light}",
            "behavior": s.behavior,
            "seconds": s.seconds,
            "instruction": s.instruction,
        })
    return out


def _write_labels(out_dir: Path, clip: str, light: str, behavior: str | None,
                  duration: float, *, angle: str = "frontal") -> Path:
    """라벨 JSON 저장. 정상(behavior None)은 빈 labels 리스트."""
    labels = []
    if behavior is not None:
        # 녹화 중 실제 행동 구간은 사람이 다듬을 수 있도록 전체 길이를 1차 라벨로 둔다.
        labels = [{"behavior": behavior, "start": 1.0, "end": round(max(2.0, duration - 1.0), 2)}]
    doc = {
        "schema": "clip-labels/1",
        "clip": clip,
        "fps_hint": 2.0,
        "conditions": {"light": light, "angle": angle},
        "labels": labels,
    }
    p = out_dir / f"{clip}.labels.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def record(light: str, out_dir: Path, *, fps: float, angle: str) -> int:
    import cv2
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(0)
    if not cap or not cap.isOpened():
        print(macos_permission_hint(), file=sys.stderr)
        return 2
    print(f"[녹화 시작] 환경={light}, 저장={out_dir} (영상은 로컬에만 저장됩니다)")
    try:
        for s in SCRIPT:
            clip = f"{s.clip_suffix}_{light}"
            print(f"\n=== {clip} ({s.seconds}s) ===\n{s.instruction}")
            for c in (3, 2, 1):
                print(f"  {c}...", flush=True); time.sleep(1.0)
            print("  촬영!", flush=True)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            vpath = out_dir / f"{clip}.mp4"
            writer = cv2.VideoWriter(str(vpath), fourcc, fps, (w, h))
            t_end = time.time() + s.seconds
            n = 0
            while time.time() < t_end:
                ok, frame = cap.read()
                if not ok:
                    break
                writer.write(frame)
                n += 1
                time.sleep(max(0.0, 1.0 / fps - 0.001))
            writer.release()
            dur = n / fps if fps else s.seconds
            lp = _write_labels(out_dir, clip, light, s.behavior, dur, angle=angle)
            print(f"  저장: {vpath.name} ({n}프레임), 라벨: {lp.name}")
    finally:
        cap.release()
    print("\n[완료] 라벨 JSON의 start/end를 실제 행동 구간에 맞게 손보면 평가 정확도가 올라갑니다.")
    print("두 환경(bright/dim)을 모두 찍으면 15~20개 세트가 됩니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="눈치코치 라벨 클립 녹화 (로컬 전용)")
    ap.add_argument("--dry-run", action="store_true", help="카메라 없이 녹화 계획만 출력")
    ap.add_argument("--light", choices=["bright", "dim"], default="bright", help="조명 환경 라벨")
    ap.add_argument("--angle", choices=["frontal", "side"], default="frontal")
    ap.add_argument("--fps", type=float, default=2.0, help="저장 프레임률(서비스와 동일 ~2fps)")
    ap.add_argument("--out", default="eval/clips", help="저장 폴더(.gitignore 대상)")
    args = ap.parse_args(argv)

    out_dir = Path(args.out)
    if args.dry_run:
        print(f"[DRY-RUN] 환경={args.light} 세트 계획 (영상은 저장하지 않음):")
        for i, item in enumerate(plan(args.light), start=1):
            tag = item["behavior"] or "정상(라벨 없음)"
            print(f"  {i:>2}. {item['clip']:<18} [{tag}] {item['seconds']}s — {item['instruction']}")
        total = sum(x["seconds"] for x in plan(args.light)) + len(SCRIPT) * 3
        print(f"\n총 {len(SCRIPT)}개 클립, 약 {total}s (카운트다운 포함). "
              f"bright/dim 둘 다 찍으면 {len(SCRIPT)*2}개.")
        print(f"저장 예정 폴더: {out_dir}/ (영상 .mp4 + <clip>.labels.json)")
        return 0

    return record(args.light, out_dir, fps=args.fps, angle=args.angle)


if __name__ == "__main__":
    raise SystemExit(main())
