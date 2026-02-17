#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="/tmp/jarvis-logs"

cd "$ROOT_DIR"
mkdir -p "$LOG_DIR"

stop_from_pidfile() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$pid_file"
  fi
}

run_migrations_with_retry() {
  local max_attempts="${1:-5}"
  local attempt=1
  local out_file
  out_file="$(mktemp)"
  while (( attempt <= max_attempts )); do
    if make migrate >"$out_file" 2>&1; then
      cat "$out_file"
      rm -f "$out_file"
      return 0
    fi
    if rg -q "database is locked|OperationalError: database is locked" "$out_file"; then
      echo "Migrations hit SQLite lock (attempt $attempt/$max_attempts); retrying..."
      sleep 2
      ((attempt++))
      continue
    fi
    cat "$out_file"
    rm -f "$out_file"
    return 1
  done
  cat "$out_file"
  rm -f "$out_file"
  return 1
}

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

has_env_key() {
  local key="$1"
  if command -v rg >/dev/null 2>&1; then
    rg -q "^[[:space:]]*${key}=" .env
  else
    grep -qE "^[[:space:]]*${key}=" .env
  fi
}

if ! has_env_key "WEB_AUTH_SETUP_PASSWORD"; then
  echo "WEB_AUTH_SETUP_PASSWORD=change-me-now" >> .env
  echo "Added WEB_AUTH_SETUP_PASSWORD=change-me-now to .env"
fi

echo "[0/6] Cleaning up stale local API/web processes..."
stop_from_pidfile "$LOG_DIR/api.pid"
stop_from_pidfile "$LOG_DIR/web.pid"
pkill -f "uvicorn jarvis.main:app" 2>/dev/null || true
pkill -f "jarvis.main:app --host 127.0.0.1 --port 8000" 2>/dev/null || true
pkill -f "/bin/gemini -m" 2>/dev/null || true
pkill -f "/web/node_modules/.bin/vite" 2>/dev/null || true
pkill -f "npm run dev -- --port 5173 --strictPort" 2>/dev/null || true
pkill -f "vite --port 5173 --strictPort" 2>/dev/null || true

echo "[1/6] Starting Docker dependencies..."
services=()

if ss -ltn 2>/dev/null | grep -q ':8080 '; then
  echo "Port 8080 already in use; skipping docker searxng."
else
  services+=("searxng")
fi

if ss -ltn 2>/dev/null | grep -q ':11434 '; then
  echo "Port 11434 already in use; skipping docker ollama."
else
  services+=("ollama")
fi

if ss -ltn 2>/dev/null | grep -q ':30000 '; then
  echo "Port 30000 already in use; skipping docker sglang."
else
  services+=("sglang")
fi

if (( ${#services[@]} > 0 )); then
  docker compose up -d "${services[@]}"
else
  echo "All dependency ports already in use; skipping docker compose startup."
fi

echo "[2/7] Syncing Python dependencies..."
uv sync

echo "[3/7] Ensuring Gemini CLI is installed and OAuth is configured..."
if ! command -v gemini >/dev/null 2>&1; then
  echo "  Gemini CLI not found; installing @google/gemini-cli..."
  npm install -g @google/gemini-cli@latest
elif npm outdated -g @google/gemini-cli 2>/dev/null | grep -q gemini-cli; then
  echo "  Updating @google/gemini-cli to latest..."
  npm install -g @google/gemini-cli@latest
else
  echo "  Gemini CLI is up to date."
fi
GEMINI_HOME="${GEMINI_CLI_HOME_DIR:-$HOME/.gemini}"
if [[ ! -f "$GEMINI_HOME/oauth_creds.json" ]]; then
  echo "  WARNING: Gemini OAuth not configured at $GEMINI_HOME/oauth_creds.json"
  echo "  Run 'gemini' interactively once to complete OAuth setup."
fi

echo "[4/7] Running DB migrations..."
run_migrations_with_retry 5

echo "[4.5/7] Seeding root admin user..."
uv run python -c "
from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_root_user
with get_conn() as conn:
    uid = ensure_root_user(conn)
    print(f'Root user ready: {uid}')
"

echo "[5/7] Installing web dependencies..."
make web-install

echo "[6/7] Starting API and web UI..."
nohup uv run uvicorn jarvis.main:app --host 127.0.0.1 --port 8000 --app-dir src > "$LOG_DIR/api.log" 2>&1 &
echo $! > "$LOG_DIR/api.pid"

nohup bash -lc "cd '$ROOT_DIR/web' && exec npm run dev -- --port 5173 --strictPort" > "$LOG_DIR/web.log" 2>&1 &
echo $! > "$LOG_DIR/web.pid"

for _ in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1; then
  echo "API failed to start. Check $LOG_DIR/api.log"
  exit 1
fi

for _ in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:5173 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://127.0.0.1:5173 >/dev/null 2>&1; then
  echo "Web UI failed to start on port 5173. Check $LOG_DIR/web.log"
  exit 1
fi

echo "[7/7] Done."
echo "UI:  http://localhost:5173"
echo "API: http://localhost:8000/healthz"
echo "Logs: $LOG_DIR/{api,web}.log"
echo "PIDs: $LOG_DIR/{api,web}.pid"
echo
echo "To stop:"
echo "kill \"\$(cat $LOG_DIR/api.pid)\" \"\$(cat $LOG_DIR/web.pid)\""
