#!/usr/bin/env bash
# test_all.sh — run the whole test suite (vision + agent + service + e2e) in ONE command.
# OWNER: cloud tab. If the vision models are missing it FAILS with guidance (never a
# silent skip), because e2e exercises the real engine.
#
# Exit codes:  10 uv missing | 12 models missing | 1 tests failed
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\033[36m[test_all]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[test_all] ERROR:\033[0m %s\n' "$*" >&2; exit "${2:-1}"; }

command -v uv >/dev/null 2>&1 || die "uv is not installed. See https://docs.astral.sh/uv/" 10

say "syncing deps (uv.lock)…"
nice -n 15 uv sync --locked --group service --group dev >/dev/null 2>&1 \
  || nice -n 15 uv sync --group service --group dev >/dev/null 2>&1 \
  || die "uv sync failed." 1

# e2e needs the real ONNX models — verify first and fail clearly if absent.
say "checking vision models (required for e2e)…"
if ! nice -n 15 uv run python models/download_models.py --check >/tmp/nunchi_models_check.log 2>&1; then
  sed 's/^/  /' /tmp/nunchi_models_check.log >&2 || true
  die "models missing/corrupt. Run: uv run python models/download_models.py" 12
fi
say "models ok."

say "running tests (vision, agent, service, e2e)… this takes ~1-2 min on first run."
START=$(date +%s)
set +e
nice -n 15 uv run pytest tests -q
RC=$?
set -e
ELAPSED=$(( $(date +%s) - START ))

if [ "$RC" -eq 0 ]; then
  say "ALL TESTS PASSED in ${ELAPSED}s."
else
  die "tests failed (pytest exit $RC) after ${ELAPSED}s." 1
fi
