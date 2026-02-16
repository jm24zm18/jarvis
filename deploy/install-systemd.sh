#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC_DIR="${ROOT_DIR}/deploy/systemd"
SYSTEMD_DIR="/etc/systemd/system"

install -m 0644 "${UNIT_SRC_DIR}/jarvis-api.service" "${SYSTEMD_DIR}/jarvis-api.service"
install -m 0644 "${UNIT_SRC_DIR}/jarvis-worker.service" "${SYSTEMD_DIR}/jarvis-worker.service"
install -m 0644 "${UNIT_SRC_DIR}/jarvis-scheduler.service" "${SYSTEMD_DIR}/jarvis-scheduler.service"

systemctl daemon-reload
systemctl enable --now jarvis-api.service jarvis-worker.service jarvis-scheduler.service

echo "Installed and started jarvis-api, jarvis-worker, jarvis-scheduler"
