"""Test-gates command: runs all pre-commit quality gates with colored output."""

from __future__ import annotations

import json
import subprocess
import sys
import time

GATES: list[tuple[str, list[str]]] = [
    ("Lint", ["uv", "run", "ruff", "check", "src", "tests"]),
    ("Typecheck", ["uv", "run", "mypy", "src"]),
    ("Agent validation", ["uv", "run", "python", "scripts/validate_agents.py"]),
    ("Migration validation", ["python3", "scripts/test_migrations.py"]),
    ("Unit tests", ["uv", "run", "pytest", "tests/unit", "-q"]),
    ("Integration tests", ["uv", "run", "pytest", "tests/integration", "-q"]),
    (
        "Coverage",
        [
            "uv", "run", "pytest", "tests",
            "--cov=jarvis.orchestrator",
            "--cov=jarvis.policy",
            "--cov=jarvis.tools.runtime",
            "--cov-report=json:/tmp/jarvis_coverage.json",
            "-q",
        ],
    ),
    (
        "Coverage threshold",
        ["uv", "run", "python", "scripts/check_coverage.py", "/tmp/jarvis_coverage.json"],
    ),
]


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def run_test_gates(
    *,
    fail_fast: bool = False,
    json_output: bool = False,
    mode: str = "enforce",
) -> None:
    results: list[dict[str, object]] = []
    failed = 0
    t0 = time.monotonic()
    gate_mode = mode.strip().lower()
    if gate_mode not in {"warn", "enforce"}:
        raise ValueError("mode must be 'warn' or 'enforce'")

    for name, cmd in GATES:
        print(f"\n{_bold(name)}")
        print(f"  $ {' '.join(cmd)}")
        gate_t0 = time.monotonic()
        proc = subprocess.run(cmd, check=False)
        elapsed = round(time.monotonic() - gate_t0, 1)
        passed = proc.returncode == 0

        icon = _green("\u2713") if passed else _red("\u2717")
        print(f"  {icon} {name} ({elapsed}s)")

        results.append(
            {
                "name": name,
                "passed": passed,
                "seconds": elapsed,
                "failure_reason": None if passed else "non_zero_exit",
            }
        )
        if not passed:
            failed += 1
            if fail_fast:
                print(f"\n{_red('Stopping early (--fail-fast)')}")
                break

    total = round(time.monotonic() - t0, 1)
    ran = len(results)

    print()
    if failed == 0:
        print(_green(f"All {ran} gates passed ({total}s)"))
    else:
        print(_red(f"{failed}/{ran} gate(s) failed ({total}s)"))

    if json_output:
        print("\n" + json.dumps(results, indent=2))

    if failed and gate_mode == "enforce":
        sys.exit(1)
