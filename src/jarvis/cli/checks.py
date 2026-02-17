"""Shared check primitives for doctor and setup verify."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    message: str
    fix_hint: str = ""
    fix_fn: Callable[[], bool] | None = None


def _copy_env_file(root: Path) -> bool:
    src = root / ".env.example"
    dst = root / ".env"
    if not src.is_file():
        return False
    if dst.exists():
        return True
    shutil.copy(src, dst)
    return dst.is_file()


def _run_migrations_fix() -> bool:
    try:
        from jarvis.db.migrations.runner import run_migrations

        run_migrations()
        return True
    except Exception:
        return False


def _docker_compose_up(service: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", service],
            capture_output=True,
            text=True,
            timeout=90,
        )
        return result.returncode == 0
    except Exception:
        return False


def check_tool_exists(name: str) -> CheckResult:
    found = shutil.which(name) is not None
    return CheckResult(
        name=f"{name} on PATH",
        passed=found,
        message=f"{name} found" if found else f"{name} not found",
        fix_hint=f"Install {name} and ensure it is on your PATH.",
    )


def check_python_version() -> CheckResult:
    v = sys.version_info
    ok = v.major == 3 and v.minor == 12
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    return CheckResult(
        name="Python version is 3.12.x",
        passed=ok,
        message=f"Python {version_str}",
        fix_hint="Requires Python 3.12.x. Install via pyenv or your package manager.",
    )


def check_env_file(root: Path) -> CheckResult:
    path = root / ".env"
    exists = path.is_file()
    return CheckResult(
        name=".env file exists",
        passed=exists,
        message=str(path) if exists else "missing",
        fix_hint="Copy .env.example to .env and fill in values: cp .env.example .env",
        fix_fn=None if exists else (lambda: _copy_env_file(root)),
    )


def check_config_loads() -> CheckResult:
    try:
        from jarvis.config import Settings

        Settings()
        return CheckResult(name="Settings load without error", passed=True, message="ok")
    except Exception as exc:
        return CheckResult(
            name="Settings load without error",
            passed=False,
            message=str(exc),
            fix_hint="Check .env for typos or missing required fields.",
        )


def check_config_validates() -> CheckResult:
    try:
        from jarvis.config import Settings, validate_settings_for_env

        settings = Settings()
        validate_settings_for_env(settings)
        return CheckResult(
            name="validate_settings_for_env() passes", passed=True, message="ok"
        )
    except Exception as exc:
        return CheckResult(
            name="validate_settings_for_env() passes",
            passed=False,
            message=str(exc),
            fix_hint="Fix the configuration issues listed above.",
        )


def check_http_service(name: str, url: str, path: str = "/") -> CheckResult:
    try:
        resp = httpx.get(url.rstrip("/") + path, timeout=5)
        ok = resp.status_code < 400
        return CheckResult(
            name=f"{name} reachable",
            passed=ok,
            message=f"HTTP {resp.status_code}",
            fix_hint=f"Ensure {name} is running at {url}.",
            fix_fn=None if ok else _service_fix_fn(name),
        )
    except Exception as exc:
        return CheckResult(
            name=f"{name} reachable",
            passed=False,
            message=str(exc),
            fix_hint=f"Ensure {name} is running at {url}.",
            fix_fn=_service_fix_fn(name),
        )


def check_database(db_path: str) -> CheckResult:
    path = Path(db_path)
    if not path.is_file():
        return CheckResult(
            name="DB file exists and readable",
            passed=False,
            message=f"{db_path} not found",
            fix_hint="Run migrations to create the database: make migrate",
            fix_fn=_run_migrations_fix,
        )
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT 1")
        conn.close()
        return CheckResult(name="DB file exists and readable", passed=True, message="ok")
    except Exception as exc:
        return CheckResult(
            name="DB file exists and readable",
            passed=False,
            message=str(exc),
            fix_hint="The database file may be corrupt. Try deleting it and running migrations.",
        )


def check_migrations_applied(db_path: str) -> CheckResult:
    from jarvis.db.migrations.runner import MIGRATIONS_DIR

    sql_files = sorted(f.name for f in MIGRATIONS_DIR.glob("*.sql"))
    total = len(sql_files)
    if total == 0:
        return CheckResult(
            name="All migrations applied", passed=True, message="no migrations found"
        )

    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT name FROM schema_migrations").fetchall()
        conn.close()
        applied = {row[0] for row in rows}
    except Exception:
        return CheckResult(
            name="All migrations applied",
            passed=False,
            message="schema_migrations table not found",
            fix_hint="Run migrations: make migrate",
            fix_fn=_run_migrations_fix,
        )

    missing = [f for f in sql_files if f not in applied]
    if missing:
        return CheckResult(
            name="All migrations applied",
            passed=False,
            message=f"{total - len(missing)}/{total} applied, missing: {', '.join(missing[:3])}",
            fix_hint="Run migrations: make migrate",
            fix_fn=_run_migrations_fix,
        )
    return CheckResult(
        name="All migrations applied", passed=True, message=f"{total}/{total}"
    )


def check_agent_bundles(agents_root: Path) -> CheckResult:
    from jarvis.agents.loader import REQUIRED_FILES

    if not agents_root.is_dir():
        return CheckResult(
            name="Agent bundles valid",
            passed=False,
            message=f"{agents_root} not found",
            fix_hint="Ensure the agents/ directory exists at the project root.",
        )

    dirs = [d for d in sorted(agents_root.iterdir()) if d.is_dir()]
    if not dirs:
        return CheckResult(
            name="Agent bundles valid",
            passed=False,
            message="no agent bundles found",
            fix_hint="Add at least one agent bundle directory under agents/.",
        )

    problems: list[str] = []
    for d in dirs:
        missing = [f for f in REQUIRED_FILES if not (d / f).is_file()]
        if missing:
            problems.append(f"{d.name} missing {', '.join(missing)}")

    if problems:
        return CheckResult(
            name="Agent bundles valid",
            passed=False,
            message="; ".join(problems),
            fix_hint="Each bundle needs: " + ", ".join(REQUIRED_FILES),
        )

    files_list = ", ".join(REQUIRED_FILES)
    return CheckResult(
        name="Agent bundles valid",
        passed=True,
        message=f"{len(dirs)} bundles found, all have {files_list}",
    )


def check_api_running() -> CheckResult:
    return check_http_service("API", "http://localhost:8000", "/healthz")


def check_task_runner() -> CheckResult:
    try:
        from jarvis.tasks import get_task_runner

        runner = get_task_runner()
        ok = runner.max_concurrent > 0
        return CheckResult(
            name="Task runner configured",
            passed=ok,
            message=f"max_concurrent={runner.max_concurrent}",
            fix_hint="Set TASK_RUNNER_MAX_CONCURRENT to a positive integer.",
        )
    except Exception as exc:
        return CheckResult(
            name="Task runner configured",
            passed=False,
            message=str(exc),
            fix_hint="Check task runner imports and configuration.",
        )

def _service_fix_fn(name: str) -> Callable[[], bool] | None:
    mapping = {
        "ollama": "ollama",
        "sglang": "sglang",
        "searxng": "searxng",
    }
    service = mapping.get(name.strip().lower())
    if service is None:
        return None
    return lambda: _docker_compose_up(service)
