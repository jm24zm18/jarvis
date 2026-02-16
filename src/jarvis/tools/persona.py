"""Persona tools for editing agent identity bundles."""

from __future__ import annotations

from pathlib import Path

KNOWN_AGENT_IDS = {"main", "researcher", "planner", "coder"}


def update_persona(agent_id: str, soul_md: str, agent_root: Path = Path("agents")) -> dict[str, object]:
    normalized_agent_id = agent_id.strip()
    if normalized_agent_id not in KNOWN_AGENT_IDS:
        return {"ok": False, "error": f"unknown agent_id '{normalized_agent_id}'"}

    content = soul_md.strip()
    if not content:
        return {"ok": False, "error": "soul_md is required"}

    path = agent_root / normalized_agent_id / "soul.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{content}\n", encoding="utf-8")
    return {
        "ok": True,
        "agent_id": normalized_agent_id,
        "path": str(path),
    }
