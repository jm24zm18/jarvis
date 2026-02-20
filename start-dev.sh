#!/usr/bin/env bash
set -e

echo "=========================================="
echo "    Starting Jarvis Developer Environment   "
echo "=========================================="

# Ensure we're in the project root
cd "$(dirname "$0")"

echo "[1/3] Starting Docker dependencies (including Baileys WhatsApp service)..."
docker compose up -d jarvis-baileys

echo ""
echo "Cleaning up any old running instances..."
pkill -f "uvicorn jarvis.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
# Free up ports explicitly if pkill missed subprocesses
fuser -k 8000/tcp 2>/dev/null || true
fuser -k 5173/tcp 2>/dev/null || true
sleep 1

echo ""
echo "[2/3] Starting Python Backend API..."
# We use stdbuf/unbuffer or just let it run
make api &
API_PID=$!

echo ""
echo "[3/3] Starting React Web Frontend..."
make web-dev &
WEB_PID=$!

echo ""
echo "=========================================="
echo " All services started!"
echo " - Backend API: http://127.0.0.1:8000"
echo " - Web Frontend: http://localhost:5173"
echo " Press Ctrl+C to stop all services."
echo "=========================================="

# Trap SIGINT (Ctrl+C) and SIGTERM to gracefully shut down the background processes
trap "echo -e '\nShutting down services...'; kill $API_PID $WEB_PID 2>/dev/null; exit 0" SIGINT SIGTERM

# Wait for background processes to keep the script running
wait $WEB_PID $API_PID
