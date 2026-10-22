#!/usr/bin/env bash
# Build the Lambda deployment zip (arm64). OWNER: cloud tab.
#
# Strategy (a) zip — see docs/ARCHITECTURE.md "Lambda 패키징". Installs arm64 manylinux
# wheels into a staging dir, adds the service package + models, strips test/pyc/metadata,
# and zips. boto3 is EXCLUDED (provided by the Lambda runtime). No docker needed.
#
# Usage:  cloud/package.sh [OUT_ZIP]
#   OUT_ZIP  output path (default: cloud/build/nunchi-service.zip)
#
# Prints the unzipped size and the zip size at the end (completion evidence).
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-cloud/build/nunchi-service.zip}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "[package] installing arm64 wheels into staging (binary-only)…"
# numpy pinned to a version with aarch64 manylinux wheels (2.5.x has none → source build fails).
# Keep this list == cloud/requirements-lambda.txt minus boto3 (runtime-provided).
nice -n 15 uv pip install \
  --python-platform aarch64-manylinux2014 --python-version 3.12 \
  --target "$STAGE" --no-cache --only-binary=:all: \
  "opencv-python-headless==5.0.0.93" "numpy>=1.26,<3" \
  "fastapi==0.159.1" "mangum==0.22.0" "python-multipart==0.0.32" >/dev/null

echo "[package] adding service package + models…"
cp -r src/nunchi "$STAGE/nunchi"
mkdir -p "$STAGE/models"
# Only ship the ONNX models + manifest (not the downloader/readme).
find models -maxdepth 1 -name "*.onnx" -exec cp {} "$STAGE/models/" \;
[ -f models/MANIFEST.json ] && cp models/MANIFEST.json "$STAGE/models/" || true

echo "[package] stripping tests / pyc / dist metadata…"
find "$STAGE" -type d -name "tests" -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name "*.pyc" -delete 2>/dev/null || true
find "$STAGE" -name "*.pyi" -delete 2>/dev/null || true

UNZIPPED_KB=$(du -sk "$STAGE" | cut -f1)
UNZIPPED_MB=$(( UNZIPPED_KB / 1024 ))
echo "[package] unzipped size: ${UNZIPPED_MB} MB (Lambda limit 250 MB)"
if [ "$UNZIPPED_MB" -gt 250 ]; then
  echo "[package] ERROR: unzipped package exceeds 250 MB; switch to container (strategy b)." >&2
  exit 2
fi

mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
( cd "$STAGE" && zip -q -r -X "$OLDPWD/$OUT" . )
ZIP_MB=$(( $(du -sk "$OUT" | cut -f1) / 1024 ))
echo "[package] wrote $OUT  (zip ${ZIP_MB} MB, unzipped ${UNZIPPED_MB} MB)"
