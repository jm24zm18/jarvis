#!/usr/bin/env bash
set -euo pipefail

echo "=========================================="
echo "    Starting Jarvis Developer Environment   "
echo "=========================================="

# Ensure we're in the project root
cd "$(dirname "$0")"

SEARXNG_BASE="${SEARXNG_BASE_URL:-http://localhost:8080}"
SEARXNG_BASE="${SEARXNG_BASE%/}"
SEARXNG_HEALTH_URL="${SEARXNG_BASE}/healthz"
SEARXNG_SEARCH_URL="${SEARXNG_BASE}/search"

wait_for_searxng() {
  local attempts=20
  local i
  for i in $(seq 1 "$attempts"); do
    if curl -fsS -m 2 "${SEARXNG_HEALTH_URL}" >/dev/null 2>&1; then
      return 0
    fi
    if curl -fsS -m 3 --get "${SEARXNG_SEARCH_URL}" \
      --data-urlencode "q=ping" \
      --data "format=json" >/dev/null 2>&1; then
      return 0
    fi
    echo "Waiting for SearXNG at ${SEARXNG_BASE}... (${i}/${attempts})"
    sleep 1
  done
  return 1
}

echo "[1/5] Starting Docker dependencies..."
make dev

echo "[2/5] Restarting jarvis-baileys for a clean WhatsApp session..."
docker compose stop jarvis-baileys >/dev/null 2>&1 || true
docker compose up -d jarvis-baileys >/dev/null

echo "[3/5] Verifying SearXNG health at ${SEARXNG_BASE}..."
if ! wait_for_searxng; then
  echo "SearXNG did not become healthy."
  echo ""
  echo "Status:"
  docker compose ps searxng || true
  echo ""
  echo "Recent searxng logs:"
  docker compose logs --tail=80 searxng || true
  echo ""
  echo "Remediation:"
  echo "- Ensure SearXNG is running: docker compose up -d searxng"
  echo "- If using alternate host port, set SEARXNG_BASE_URL accordingly (example: http://localhost:18080)"
  echo "- Validate manually: curl -fsS ${SEARXNG_HEALTH_URL}"
  exit 1
fi

echo ""
echo "Cleaning up any old running instances..."
pkill -f "uvicorn jarvis.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
# Free up ports explicitly if pkill missed subprocesses
fuser -k 8000/tcp 2>/dev/null || true
fuser -k 5173/tcp 2>/dev/null || true
sleep 1

echo ""
echo "[4/5] Starting Python Backend API..."
# We use stdbuf/unbuffer or just let it run
make api &
API_PID=$!

echo ""
echo "[5/5] Starting React Web Frontend..."
make web-dev &
WEB_PID=$!

echo ""
echo "=========================================="
echo " All services started!"
echo " - Backend API: http://127.0.0.1:8000"
echo " - Web Frontend: http://localhost:5173"
echo " Press Ctrl+C to stop all services."
echo "=========================================="

cleanup() {
  echo -e "\nShutting down services..."
  if [ -n "${API_PID:-}" ]; then
    kill "${API_PID}" 2>/dev/null || true
  fi
  if [ -n "${WEB_PID:-}" ]; then
    kill "${WEB_PID}" 2>/dev/null || true
  fi
}

# Trap SIGINT (Ctrl+C) and SIGTERM to gracefully shut down the background processes
trap "cleanup; exit 0" SIGINT SIGTERM

# Wait for background processes to keep the script running
wait $WEB_PID $API_PID
