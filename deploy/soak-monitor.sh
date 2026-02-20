#!/usr/bin/env bash
# Jarvis 24h Readiness Soak Monitor
# Usage: ./deploy/soak-monitor.sh [interval_seconds] [duration_hours]
# Logs readyz probe results to data/soak_log.txt
set -euo pipefail

INTERVAL="${1:-60}"
DURATION_HOURS="${2:-24}"
URL="http://127.0.0.1:8000/readyz"
LOG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data"
LOG_FILE="${LOG_DIR}/soak_log.txt"
TOTAL_SECONDS=$((DURATION_HOURS * 3600))

mkdir -p "${LOG_DIR}"

echo "=== Jarvis 24h Readiness Soak ===" | tee -a "${LOG_FILE}"
echo "Start: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${LOG_FILE}"
echo "Duration: ${DURATION_HOURS}h, Interval: ${INTERVAL}s" | tee -a "${LOG_FILE}"
echo "URL: ${URL}" | tee -a "${LOG_FILE}"
echo "---" | tee -a "${LOG_FILE}"

PASS=0
FAIL=0
START_TS=$(date +%s)

while true; do
  NOW_TS=$(date +%s)
  ELAPSED=$((NOW_TS - START_TS))
  if [ "${ELAPSED}" -ge "${TOTAL_SECONDS}" ]; then
    break
  fi

  STAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  BODY=$(curl -fsS --max-time 10 "${URL}" 2>&1 || echo "CURL_FAILED")

  if echo "${BODY}" | grep -q '"ok":true\|"ok": true'; then
    echo "${STAMP} OK ${BODY}" >> "${LOG_FILE}"
    PASS=$((PASS + 1))
  else
    echo "${STAMP} FAIL ${BODY}" | tee -a "${LOG_FILE}"
    FAIL=$((FAIL + 1))
  fi

  # Print progress every 10 checks
  TOTAL=$((PASS + FAIL))
  if [ $((TOTAL % 10)) -eq 0 ]; then
    HOURS_LEFT=$(( (TOTAL_SECONDS - ELAPSED) / 3600 ))
    echo "[${STAMP}] pass=${PASS} fail=${FAIL} remaining=${HOURS_LEFT}h"
  fi

  sleep "${INTERVAL}"
done

echo "---" | tee -a "${LOG_FILE}"
echo "End: $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${LOG_FILE}"
echo "Results: pass=${PASS} fail=${FAIL}" | tee -a "${LOG_FILE}"

if [ "${FAIL}" -eq 0 ]; then
  echo "SOAK PASSED" | tee -a "${LOG_FILE}"
  exit 0
else
  echo "SOAK FAILED (${FAIL} failures)" | tee -a "${LOG_FILE}"
  exit 1
fi
