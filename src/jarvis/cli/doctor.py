"""Doctor command: runs checks and prints a color-coded report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jarvis.cli.checks import (
    CheckResult,
    check_agent_bundles,
    check_api_running,
    check_config_loads,
    check_config_validates,
    check_database,
    check_env_file,
    check_http_service,
    check_migrations_applied,
    check_python_version,
    check_task_runner,
    check_tool_exists,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _print_result(result: CheckResult) -> None:
    icon = _green("\u2713") if result.passed else _red("\u2717")
    print(f"  {icon} {result.name}: {result.message}")
    if not result.passed and result.fix_hint:
        print(f"    {_yellow('Fix:')} {result.fix_hint}")


def _section(title: str) -> None:
    print(f"\n{_bold(title)}")


def run_doctor(*, json_output: bool = False, fix: bool = False) -> None:
    all_results: list[CheckResult] = []
    failed = False

    def _run(result: CheckResult) -> bool:
        all_results.append(result)
        _print_result(result)
        if not result.passed:
            if fix and result.fix_fn is not None:
                applied = result.fix_fn()
                status_text = "applied" if applied else "failed"
                print(f"    {_yellow('Auto-fix:')} {status_text}")
            nonlocal failed
            failed = True
        return result.passed

    # --- System Tools ---
    _section("System Tools")
    for tool in ("python3", "uv", "git", "docker"):
        _run(check_tool_exists(tool))
    _run(check_python_version())

    # --- Configuration ---
    _section("Configuration")
    env_ok = _run(check_env_file(PROJECT_ROOT))
    config_ok = False
    if env_ok:
        config_ok = _run(check_config_loads())
        if config_ok:
            _run(check_config_validates())

    # --- External Services ---
    _section("External Services")
    if config_ok:
        try:
            from jarvis.config import Settings

            settings = Settings()
            _run(check_http_service("Ollama", settings.ollama_base_url, "/api/tags"))
            sglang_base = settings.sglang_base_url.rstrip("/v1").rstrip("/")
            _run(check_http_service("SGLang", sglang_base, "/health"))
            _run(check_http_service("SearXNG", settings.searxng_base_url, "/"))
        except Exception as exc:
            result = CheckResult(
                name="Load settings for service checks",
                passed=False,
                message=str(exc),
            )
            _run(result)
    else:
        print(f"  {_yellow('⊘')} skipped (configuration not loaded)")

    # --- Database ---
    _section("Database")
    if config_ok:
        try:
            from jarvis.config import Settings

            settings = Settings()
            db_ok = _run(check_database(settings.app_db))
            if db_ok:
                _run(check_migrations_applied(settings.app_db))
        except Exception as exc:
            _run(
                CheckResult(
                    name="Database checks", passed=False, message=str(exc)
                )
            )
    else:
        print(f"  {_yellow('⊘')} skipped (configuration not loaded)")

    # --- Agent Bundles ---
    _section("Agent Bundles")
    _run(check_agent_bundles(PROJECT_ROOT / "agents"))

    # --- Runtime ---
    _section("Runtime (if running)")
    api_result = check_api_running()
    _run(api_result)
    if api_result.passed:
        _run(check_task_runner())
    else:
        print(f"  {_yellow('⊘')} task runner check skipped (API not running)")

    # --- Summary ---
    fail_count = sum(1 for r in all_results if not r.passed)
    print()
    if fail_count == 0:
        print(_green("All checks passed!"))
    else:
        print(_red(f"{fail_count} check(s) failed."))

    if json_output:
        data = [
            {
                "name": r.name,
                "passed": r.passed,
                "message": r.message,
                "fix_hint": r.fix_hint,
            }
            for r in all_results
        ]
        print("\n" + json.dumps(data, indent=2))

    if failed:
        sys.exit(1)
