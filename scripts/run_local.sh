#!/usr/bin/env bash
# run_local.sh — bring up nunchikochi (service + web) locally in ONE command. No AWS.
# OWNER: cloud tab. macOS + Linux, arm64/x86.
#
# Steps: check uv -> sync pinned deps (uv.lock) -> download+verify models -> start the
# FastAPI service (uvicorn, in-memory state) -> serve the web static files -> print URLs.
# Ctrl-C (or exit) tears both down. A local DUMMY api key is generated and printed; it is
# NOT a secret (local only, in-memory).
#
# Exit codes:  10 uv missing | 11 port in use | 12 model download/verify failed | 1 other
set -euo pipefail
cd "$(dirname "$0")/.."

SVC_PORT="${NUNCHI_SVC_PORT:-8000}"
WEB_PORT="${NUNCHI_WEB_PORT:-8099}"
PIDS=()

say()  { printf '\033[36m[run_local]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[run_local] ERROR:\033[0m %s\n' "$*" >&2; exit "${2:-1}"; }

cleanup() {
  say "shutting down…"
  for pid in "${PIDS[@]:-}"; do [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

port_busy() {  # 0 = busy
  if command -v lsof >/dev/null 2>&1; then lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v nc  >/dev/null 2>&1; then nc -z 127.0.0.1 "$1" >/dev/null 2>&1
  else return 1; fi
}

# 1) tooling
command -v uv >/dev/null 2>&1 || die "uv is not installed. Install: https://docs.astral.sh/uv/getting-started/ (curl -LsSf https://astral.sh/uv/install.sh | sh)" 10

# 2) ports
for p in "$SVC_PORT" "$WEB_PORT"; do
  if port_busy "$p"; then
    die "port $p already in use. Free it or set NUNCHI_SVC_PORT / NUNCHI_WEB_PORT." 11
  fi
done

# 3) pinned deps (uses uv.lock for a reproducible env)
say "syncing pinned dependencies (uv.lock)…"
nice -n 15 uv sync --locked --group service >/dev/null 2>&1 \
  || nice -n 15 uv sync --group service >/dev/null 2>&1 \
  || die "uv sync failed. See pyproject.toml / uv.lock." 1

# 4) models (download + sha256 verify; explicit failure, never silent skip)
say "verifying vision models (models/MANIFEST.json)…"
if ! nice -n 15 uv run python models/download_models.py >/tmp/nunchi_models.log 2>&1; then
  sed 's/^/  /' /tmp/nunchi_models.log >&2 || true
  die "model download/verify failed. Re-run: uv run python models/download_models.py" 12
fi
say "models ok."

# 5) local dummy api key (NOT a secret — local, in-memory service only)
DUMMY_KEY="local-$(uv run python -c 'import secrets;print(secrets.token_hex(8))' 2>/dev/null || echo devkey00)"

# 6) start the service (in-memory state, real engine, dummy key)
say "starting service on http://127.0.0.1:${SVC_PORT} …"
NUNCHI_STATE_BACKEND=memory \
NUNCHI_FORCE_STUB="${NUNCHI_FORCE_STUB:-}" \
NUNCHI_API_KEY="$DUMMY_KEY" \
NUNCHI_CORS_ORIGINS="http://localhost:${WEB_PORT},http://127.0.0.1:${WEB_PORT}" \
  nice -n 15 uv run uvicorn nunchi.service.app:app --host 127.0.0.1 --port "$SVC_PORT" \
  >/tmp/nunchi_service.log 2>&1 &
PIDS+=($!)

# 7) wait for /healthz 200
say "waiting for /healthz …"
ok=0
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${SVC_PORT}/healthz" >/tmp/nunchi_health.json 2>/dev/null; then ok=1; break; fi
  sleep 0.5
done
[ "$ok" = 1 ] || { sed 's/^/  /' /tmp/nunchi_service.log >&2 || true; die "service did not become healthy on :${SVC_PORT}" 1; }
say "healthz: $(cat /tmp/nunchi_health.json)"

# 8) write web/config.json so the browser talks to THIS service (gitignored; dummy key)
cat > web/config.json <<JSON
{
  "apiBase": "http://127.0.0.1:${SVC_PORT}",
  "apiKey": "${DUMMY_KEY}",
  "lang": "en",
  "fps": 2
}
JSON

# 9) serve the web static files
say "serving web on http://127.0.0.1:${WEB_PORT} …"
( cd web && nice -n 15 uv run python -m http.server "$WEB_PORT" --bind 127.0.0.1 ) \
  >/tmp/nunchi_web.log 2>&1 &
PIDS+=($!)
sleep 1

cat <<EOF

  ✅ nunchikochi is up (local, no AWS)
     web      : http://127.0.0.1:${WEB_PORT}
     service  : http://127.0.0.1:${SVC_PORT}  (/healthz, /v1/*)
     api key  : ${DUMMY_KEY}   (local dummy, not a secret)
     logs     : /tmp/nunchi_service.log , /tmp/nunchi_web.log

  Open the web URL in a browser (camera permission needed for live use).
  Press Ctrl-C to stop everything.

EOF

wait
