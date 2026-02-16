#!/usr/bin/env bash
set -euo pipefail

URL="${1:-http://127.0.0.1:8000/readyz}"

body="$(curl -fsS "${URL}")"
echo "${body}" | rg -q '"ok"\s*:\s*true'
echo "readyz ok"
