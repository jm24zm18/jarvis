#!/usr/bin/env python3
"""New-user setup smoke target for API + web bootstrap."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _run(step: str, cmd: list[str], *, cwd: Path | None = None) -> None:
    print(f"[smoke] {step}: {' '.join(cmd)}")
    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", "/tmp/uv-cache")
    env.setdefault("XDG_CACHE_HOME", "/tmp/.cache")
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        return
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    raise SystemExit(
        f"[smoke] failed: {step} (exit {result.returncode}). "
        "Resolve the error above and rerun `make setup-smoke`."
    )


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(
            f"[smoke] missing required tool: {name}. "
            "Install prerequisites from docs/getting-started.md."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-web-install", action="store_true")
    parser.add_argument("--skip-migrate", action="store_true")
    parser.add_argument("--skip-dev-preflight", action="store_true")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    env_file = project_root / ".env"
    if not env_file.is_file():
        raise SystemExit("[smoke] missing .env. Run `cp .env.example .env` first.")

    for tool in ("python3", "uv", "docker", "node", "npm"):
        _require_tool(tool)

    _run("python version", ["python3", "--version"])
    _run("uv version", ["uv", "--version"])
    _run("node version", ["node", "--version"])
    _run("npm version", ["npm", "--version"])

    if not args.skip_dev_preflight:
        _run("dev port preflight", ["python3", "scripts/dev_preflight_ports.py"], cwd=project_root)
    if not args.skip_migrate:
        _run("database migrations", ["uv", "run", "python", "-m", "jarvis.db.migrations.runner"], cwd=project_root)

    # API bootstrap check: app import works in the current env.
    _run(
        "api bootstrap import",
        ["uv", "run", "python", "-c", "from jarvis.main import app; print(app.title)"],
        cwd=project_root,
    )

    if not args.skip_web_install:
        _run("web dependency install", ["python3", "scripts/web_install.py"], cwd=project_root)

    node_modules = project_root / "web" / "node_modules"
    if not node_modules.is_dir():
        raise SystemExit(
            "[smoke] web bootstrap incomplete: web/node_modules missing. "
            "Run `make web-install` and retry."
        )

    print("[smoke] ok: API + web setup bootstrap checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
