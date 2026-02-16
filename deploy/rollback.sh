#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <git-ref>"
  exit 1
fi

TARGET_REF="$1"
REPO_DIR="${2:-/srv/agent-framework}"

git -C "${REPO_DIR}" fetch --all --tags
git -C "${REPO_DIR}" checkout "${TARGET_REF}"

systemctl restart jarvis-api.service jarvis-worker.service jarvis-scheduler.service
echo "Rolled back to ${TARGET_REF} and restarted services"
