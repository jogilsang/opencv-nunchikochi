#!/usr/bin/env python3
"""Reproducible, re-run-safe model downloader for the vision tab.

Reads ``models/MANIFEST.json`` (source of truth: name/url/sha256/bytes/license)
and fetches each model next to this script. ONNX files are gitignored; this
script + manifest make them reproducible on a fresh machine.

Behaviour:
- Re-run safe: if the file already exists and its sha256 matches the manifest,
  it is left untouched (no re-download).
- Integrity: after download, sha256 is verified against the manifest. On
  mismatch the partial file is removed and the model is reported as failed.
- Network failure on a single model does not abort the others; a summary with
  exit code (0 = all required models present & verified) is printed.

Usage:
    uv run python models/download_models.py          # fetch missing/changed
    uv run python models/download_models.py --check  # verify only, no download
    uv run python models/download_models.py --force  # re-download everything

No OpenCV import here — pure stdlib so it runs before the env is fully set up.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "MANIFEST.json"
TIMEOUT = 180


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    with MANIFEST.open(encoding="utf-8") as f:
        return json.load(f)


def verify(path: Path, expected_sha: str) -> bool:
    return path.exists() and sha256_of(path) == expected_sha


def download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "nunchikochi-model-dl/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)


def download_from_archive(archive_url: str, member: str, dest: Path) -> None:
    """Fetch a .tar.gz and extract a single member to ``dest`` (no full unpack)."""
    req = urllib.request.Request(archive_url, headers={"User-Agent": "nunchikochi-model-dl/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        src = None
        for m in tar.getmembers():
            if m.name == member or m.name.endswith("/" + member) or Path(m.name).name == member:
                src = m
                break
        if src is None:
            raise OSError(f"member {member!r} not found in archive {archive_url}")
        extracted = tar.extractfile(src)
        if extracted is None:
            raise OSError(f"could not extract {member!r} from archive")
        tmp.write_bytes(extracted.read())
    tmp.replace(dest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download/verify vision models from MANIFEST.json")
    ap.add_argument("--check", action="store_true", help="verify only; never download")
    ap.add_argument("--force", action="store_true", help="re-download even if present and valid")
    args = ap.parse_args(argv)

    manifest = load_manifest()
    models = manifest.get("models", {})
    ok, failed = [], []

    for name, spec in models.items():
        dest = HERE / spec["file"]
        expected = spec["sha256"]

        if not args.force and verify(dest, expected):
            print(f"[ok]    {name}: present & verified ({dest.name})")
            ok.append(name)
            continue

        if args.check:
            state = "missing" if not dest.exists() else "sha mismatch"
            print(f"[check] {name}: {state} ({dest.name})")
            failed.append(name)
            continue

        print(f"[get]   {name}: downloading {spec.get('url') or spec.get('archive_url')}")
        try:
            if spec.get("archive_url"):
                download_from_archive(spec["archive_url"], spec["archive_member"], dest)
            else:
                download(spec["url"], dest)
        except (urllib.error.URLError, OSError, tarfile.TarError) as e:  # network / disk / archive
            print(f"[fail]  {name}: download error: {e}")
            if dest.with_suffix(dest.suffix + ".part").exists():
                dest.with_suffix(dest.suffix + ".part").unlink()
            failed.append(name)
            continue

        if verify(dest, expected):
            print(f"[ok]    {name}: downloaded & verified")
            ok.append(name)
        else:
            got = sha256_of(dest) if dest.exists() else "(no file)"
            print(f"[fail]  {name}: sha256 mismatch\n          expected {expected}\n          got      {got}")
            if dest.exists():
                dest.unlink()
            failed.append(name)

    required_missing = [n for n in failed if models[n].get("required", True)]
    print(f"\nsummary: {len(ok)} ok, {len(failed)} failed "
          f"({len(required_missing)} required missing)")
    return 1 if required_missing else 0


if __name__ == "__main__":
    sys.exit(main())
