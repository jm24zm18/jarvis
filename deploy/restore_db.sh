#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <snapshot.db|snapshot.db.gz> [db_path]"
  exit 1
fi

SNAPSHOT="$1"
DB_PATH="${2:-/srv/agent-framework/app.db}"
READYZ_URL="${RESTORE_READYZ_URL:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STAGE_PATH="${DB_PATH}.restore.${STAMP}"
PREV_PATH="${DB_PATH}.pre_restore.${STAMP}"

if [ ! -f "${SNAPSHOT}" ]; then
  echo "snapshot not found: ${SNAPSHOT}"
  exit 1
fi

mkdir -p "$(dirname "${DB_PATH}")"

if [[ "${SNAPSHOT}" == *.gz ]]; then
  gzip -cd "${SNAPSHOT}" > "${STAGE_PATH}"
else
  cp "${SNAPSHOT}" "${STAGE_PATH}"
fi

INTEGRITY="$(sqlite3 "${STAGE_PATH}" "PRAGMA integrity_check;")"
if [ "${INTEGRITY}" != "ok" ]; then
  echo "integrity check failed: ${INTEGRITY}"
  rm -f "${STAGE_PATH}"
  exit 1
fi

if [ -f "${DB_PATH}" ]; then
  cp "${DB_PATH}" "${PREV_PATH}"
fi
mv "${STAGE_PATH}" "${DB_PATH}"

if [ -n "${READYZ_URL}" ]; then
  BODY="$(curl -fsS --max-time 5 "${READYZ_URL}" || true)"
  if [[ "${BODY}" != *'"ok":true'* && "${BODY}" != *'"ok": true'* ]]; then
    echo "restore readiness check failed"
    if [ -f "${PREV_PATH}" ]; then
      mv "${PREV_PATH}" "${DB_PATH}"
      echo "reverted to previous db"
    fi
    exit 1
  fi
fi

echo "restore complete"
echo "db_path=${DB_PATH}"
echo "previous_backup=${PREV_PATH}"
