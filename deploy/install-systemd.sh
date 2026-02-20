#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC_DIR="${ROOT_DIR}/deploy/systemd"
SYSTEMD_DIR="/etc/systemd/system"
ENV_SRC="${ROOT_DIR}/deploy/.env.prod"

# Validate production env exists
if [ ! -f "${ENV_SRC}" ]; then
    echo "ERROR: ${ENV_SRC} not found. Copy deploy/.env.prod and configure it first."
    exit 1
fi

# Create data directories
mkdir -p "${ROOT_DIR}/data"/{backups,patches,exec_logs}

# Install systemd units
install -m 0644 "${UNIT_SRC_DIR}/jarvis-api.service" "${SYSTEMD_DIR}/jarvis-api.service"
install -m 0644 "${UNIT_SRC_DIR}/jarvis-worker.service" "${SYSTEMD_DIR}/jarvis-worker.service"
install -m 0644 "${UNIT_SRC_DIR}/jarvis-scheduler.service" "${SYSTEMD_DIR}/jarvis-scheduler.service"

systemctl daemon-reload
systemctl enable --now jarvis-api.service jarvis-worker.service jarvis-scheduler.service

echo "Installed and started jarvis-api, jarvis-worker, jarvis-scheduler"
echo "Env file: ${ENV_SRC}"
echo "Logs: journalctl -u jarvis-api -f"
