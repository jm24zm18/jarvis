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
OLLAMA_BASE="${OLLAMA_BASE_URL:-http://localhost:11434}"
OLLAMA_BASE="${OLLAMA_BASE%/}"
OLLAMA_TAGS_URL="${OLLAMA_BASE}/api/tags"
DEV_USE_HOST_OLLAMA="${DEV_USE_HOST_OLLAMA:-1}"
LMSTUDIO_BASE="${LMSTUDIO_BASE_URL:-http://127.0.0.1:1234}"
LMSTUDIO_BASE="${LMSTUDIO_BASE%/}"
LMSTUDIO_OPENAI_BASE="${LMSTUDIO_OPENAI_BASE_URL:-${LMSTUDIO_BASE}/v1}"
LMSTUDIO_OPENAI_BASE="${LMSTUDIO_OPENAI_BASE%/}"
LMSTUDIO_MODELS_URL="${LMSTUDIO_OPENAI_BASE}/models"
OPENCODE_CONFIG_PATH="${OPENCODE_CONFIG_PATH:-opencode.json}"

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

echo "[0/6] Verifying OpenCode + LM Studio bootstrap..."
if ! command -v opencode >/dev/null 2>&1; then
  echo "OpenCode CLI is not installed or not in PATH."
  echo ""
  echo "Remediation:"
  echo "- Install OpenCode and ensure 'opencode' resolves in your shell."
  echo "- Re-run: ./start-dev.sh"
  exit 1
fi

if ! curl -fsS -m 5 "${LMSTUDIO_MODELS_URL}" >/dev/null 2>&1; then
  echo "LM Studio OpenAI-compatible endpoint is not reachable at ${LMSTUDIO_MODELS_URL}."
  echo ""
  echo "Remediation:"
  echo "- Start LM Studio server and enable OpenAI-compatible API."
  echo "- Set LMSTUDIO_BASE_URL / LMSTUDIO_OPENAI_BASE_URL if using custom host/port."
  echo "- Validate manually: curl -fsS ${LMSTUDIO_MODELS_URL}"
  exit 1
fi

BOOTSTRAP_OUTPUT="$(
  curl -fsS -m 10 "${LMSTUDIO_MODELS_URL}" \
    | python3 -c '
import json
import pathlib
import sys

raw = sys.stdin.read()
if not raw.strip():
    raise SystemExit("LM Studio /models endpoint returned an empty response")
try:
    payload = json.loads(raw)
except json.JSONDecodeError as exc:
    raise SystemExit(f"LM Studio /models returned invalid JSON: {exc}") from exc
data = payload.get("data") if isinstance(payload, dict) else None
if not isinstance(data, list):
    raise SystemExit("LM Studio /models payload missing data[]")

model_ids = []
for item in data:
    if not isinstance(item, dict):
        continue
    model_id = str(item.get("id") or "").strip()
    if model_id:
        model_ids.append(model_id)

if not model_ids:
    raise SystemExit("No LM Studio models discovered from /models endpoint")

config_path = pathlib.Path(sys.argv[1]).expanduser()
openai_base = str(sys.argv[2]).rstrip("/")
requested_default = str(sys.argv[3]).strip()
default_model = requested_default if requested_default in model_ids else model_ids[0]

config_doc = {
    "$schema": "https://opencode.ai/config.json",
    "provider": {
        "lmstudio": {
            "api": openai_base,
            "name": "LM Studio",
            "id": "lmstudio",
            "npm": "@ai-sdk/openai-compatible",
            "models": {m: {"id": m, "name": m} for m in model_ids},
            "options": {"baseURL": openai_base},
        }
    },
}
config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(json.dumps(config_doc, indent=2) + "\n", encoding="utf-8")

print(f"CONFIG_PATH={config_path}")
print(f"DEFAULT_MODEL={default_model}")
for model_id in model_ids:
    print(f"MODEL={model_id}")
' "${OPENCODE_CONFIG_PATH}" "${LMSTUDIO_OPENAI_BASE}" "${LMSTUDIO_MODEL:-}"
)"

echo "LM Studio discovered models:"
while IFS= read -r line; do
  case "${line}" in
    MODEL=*)
      echo " - ${line#MODEL=}"
      ;;
    DEFAULT_MODEL=*)
      DEFAULT_MODEL="${line#DEFAULT_MODEL=}"
      ;;
    CONFIG_PATH=*)
      WRITTEN_CONFIG_PATH="${line#CONFIG_PATH=}"
      ;;
  esac
done <<< "${BOOTSTRAP_OUTPUT}"
echo "Default model: ${DEFAULT_MODEL:-unknown}"
echo "OpenCode config written: ${WRITTEN_CONFIG_PATH:-${OPENCODE_CONFIG_PATH}}"

echo "[1/6] Starting Docker dependencies..."
DEV_USE_HOST_OLLAMA="${DEV_USE_HOST_OLLAMA}" python3 scripts/dev_preflight_ports.py
if [[ "${DEV_USE_HOST_OLLAMA}" == "1" ]]; then
  echo "Using host Ollama at ${OLLAMA_BASE} (DEV_USE_HOST_OLLAMA=1)."
  docker compose up -d searxng sglang >/dev/null
else
  echo "Using Docker Ollama (DEV_USE_HOST_OLLAMA=0)."
  make dev
fi

echo "[2/6] Restarting jarvis-baileys for a clean WhatsApp session..."
docker compose stop jarvis-baileys >/dev/null 2>&1 || true
docker compose up -d jarvis-baileys >/dev/null

echo "[3/6] Verifying Ollama and SearXNG health..."
if [[ "${DEV_USE_HOST_OLLAMA}" == "1" ]]; then
  if ! curl -fsS -m 3 "${OLLAMA_TAGS_URL}" >/dev/null 2>&1; then
    echo "Host Ollama is not reachable at ${OLLAMA_BASE}."
    echo ""
    echo "Remediation:"
    echo "- Start host Ollama: ollama serve"
    echo "- Or use Docker Ollama: DEV_USE_HOST_OLLAMA=0 ./start-dev.sh"
    echo "- Validate manually: curl -fsS ${OLLAMA_TAGS_URL}"
    exit 1
  fi
fi

echo "Checking SearXNG health at ${SEARXNG_BASE}..."
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
echo "[4/6] Starting Python Backend API..."
# We use stdbuf/unbuffer or just let it run
make api &
API_PID=$!

echo ""
echo "[5/6] Starting React Web Frontend..."
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
