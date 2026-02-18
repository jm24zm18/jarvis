"""Dependency stewardship task stubs with evidence output."""

from __future__ import annotations

import json
import subprocess

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import insert_governance_agent_run


def _risk_for_upgrade(current: str, latest: str) -> str:
    def _major(value: str) -> int | None:
        parts = value.split(".")
        if not parts:
            return None
        try:
            return int(parts[0])
        except ValueError:
            return None

    cur = _major(current)
    nxt = _major(latest)
    if cur is None or nxt is None:
        return "unknown"
    if nxt > cur:
        return "high"
    return "medium" if latest != current else "low"


def run_dependency_steward() -> dict[str, object]:
    settings = get_settings()
    if int(settings.dependency_steward_enabled) != 1:
        result = {"status": "disabled"}
        with get_conn() as conn:
            insert_governance_agent_run(
                conn,
                run_type="dependency_steward",
                status="disabled",
                summary="dependency steward disabled",
                payload=result,
            )
        return result
    max_upgrades = max(1, int(settings.dependency_steward_max_upgrades))
    try:
        proc = subprocess.run(
            ["uv", "run", "pip", "list", "--outdated", "--format=json"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            result = {
                "status": "error",
                "returncode": proc.returncode,
                "outdated_json": proc.stdout[:20000],
                "stderr": proc.stderr[:2000],
                "max_upgrades": max_upgrades,
                "proposals": [],
                "risk_summary": {"high": 0, "medium": 0, "low": 0, "unknown": 0},
            }
            with get_conn() as conn:
                insert_governance_agent_run(
                    conn,
                    run_type="dependency_steward",
                    status="error",
                    summary="dependency listing command failed",
                    payload=result,
                )
            return result
        payload = json.loads(proc.stdout or "[]")
        items = payload if isinstance(payload, list) else []
        normalized = [
            {
                "name": str(item.get("name", "")).strip(),
                "current": str(item.get("version", "")).strip(),
                "latest": str(item.get("latest_version", "")).strip(),
            }
            for item in items
            if isinstance(item, dict)
        ]
        normalized = [item for item in normalized if item["name"]]
        normalized.sort(key=lambda item: item["name"].lower())
        proposals = []
        risk_summary = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
        for item in normalized[:max_upgrades]:
            risk = _risk_for_upgrade(item["current"], item["latest"])
            risk_summary[risk] = int(risk_summary.get(risk, 0)) + 1
            proposals.append(
                {
                    "package": item["name"],
                    "from_version": item["current"],
                    "to_version": item["latest"],
                    "risk": risk,
                }
            )
        result = {
            "status": "ok",
            "returncode": proc.returncode,
            "outdated_json": proc.stdout[:20000],
            "stderr": proc.stderr[:2000],
            "max_upgrades": max_upgrades,
            "outdated_total": len(normalized),
            "proposals": proposals,
            "risk_summary": risk_summary,
        }
        with get_conn() as conn:
            insert_governance_agent_run(
                conn,
                run_type="dependency_steward",
                status=str(result["status"]),
                summary=f"proposals={len(proposals)} outdated_total={len(normalized)}",
                payload=result,
            )
        return result
    except Exception as exc:
        result = {"status": "error", "error": str(exc)}
        with get_conn() as conn:
            insert_governance_agent_run(
                conn,
                run_type="dependency_steward",
                status="error",
                summary="dependency steward execution exception",
                payload=result,
            )
        return result
