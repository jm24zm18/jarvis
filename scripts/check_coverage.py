#!/usr/bin/env python3
"""Enforce per-module coverage thresholds for plan quality gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

THRESHOLD = 80.0
TARGETS = (
    "src/jarvis/orchestrator/",
    "src/jarvis/policy/",
    "src/jarvis/tools/runtime.py",
)


def _matches_target(filename: str) -> bool:
    return any(filename.startswith(prefix) for prefix in TARGETS)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_coverage.py <coverage.json>")
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"coverage file missing: {path}")
        return 2

    payload = json.loads(path.read_text())
    files = payload.get("files", {})
    if not isinstance(files, dict):
        print("invalid coverage payload")
        return 2

    covered = 0
    statements = 0
    for filename, info in files.items():
        if not isinstance(filename, str) or not _matches_target(filename):
            continue
        if not isinstance(info, dict):
            continue
        summary = info.get("summary", {})
        if not isinstance(summary, dict):
            continue
        covered_lines = summary.get("covered_lines")
        num_statements = summary.get("num_statements")
        if isinstance(covered_lines, int) and isinstance(num_statements, int):
            covered += covered_lines
            statements += num_statements

    if statements == 0:
        print("no coverage data found for target modules")
        return 2
    percent = (covered / statements) * 100.0
    print(f"target coverage: {percent:.2f}% (threshold {THRESHOLD:.2f}%)")
    if percent < THRESHOLD:
        print("coverage gate failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
