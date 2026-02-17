"""Dependency stewardship task stubs with evidence output."""

from __future__ import annotations

import subprocess

from jarvis.config import get_settings


def run_dependency_steward() -> dict[str, object]:
    settings = get_settings()
    if int(settings.dependency_steward_enabled) != 1:
        return {"status": "disabled"}
    try:
        proc = subprocess.run(
            ["uv", "run", "pip", "list", "--outdated", "--format=json"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return {
            "status": "ok" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "outdated_json": proc.stdout[:20000],
            "stderr": proc.stderr[:2000],
            "max_upgrades": int(settings.dependency_steward_max_upgrades),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

