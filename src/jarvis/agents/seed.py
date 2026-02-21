"""Helpers for seeding minimal agent bundles on first boot."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from jarvis.memory.skills import SkillsService


def ensure_main_agent_seed(agent_root: Path) -> bool:
    """Ensure the main agent has baseline files so startup doesn't fail hard."""
    main_dir = agent_root / "main"
    changed = False
    main_dir.mkdir(parents=True, exist_ok=True)

    identity = main_dir / "identity.md"
    if not identity.exists():
        identity.write_text(
            f"---\n"
            f"agent_id: main\n"
            f"allowed_tools:\n"
            f"  - echo\n"
            f"  - session_list\n"
            f"  - session_history\n"
            f"  - session_send\n"
            f"  - web_search\n"
            f"  - exec_host\n"
            f"  - skill_list\n"
            f"  - skill_read\n"
            f"  - skill_write\n"
            f"  - update_persona\n"
            f"risk_tier: medium\n"
            f"max_actions_per_step: 8\n"
            f"allowed_paths:\n"
            f"  - {str(Path.cwd())}\n"
            f"  - /tmp\n"
            f"can_request_privileged_change: true\n"
            f"---\n\n"
            f"# Jarvis Main Agent\n\n"
            f"User-facing coordinator. Handles commands directly when simple, and delegates "
            f"specialized work to worker agents.\n",
            encoding="utf-8",
        )
        changed = True

    soul = main_dir / "soul.md"
    if not soul.exists():
        soul.write_text(
            "You are **Jarvis**, a personal AI assistant. Never claim to be GPT, "
            "ChatGPT, Claude, Gemini, or any specific AI model. Never say you were "
            "created by OpenAI, Anthropic, or Google. You are Jarvis.\n\n"
            "Your tone is calm, polite, and lightly witty — concise by default, "
            "detailed when the user needs it.\n\n"
            "## Routing Rules\n\n"
            "**Handle directly** (do NOT delegate):\n"
            "- Simple questions, casual conversation, greetings\n"
            "- General knowledge, math, definitions, explanations\n"
            "- Quick lookups, status checks, straightforward tasks\n"
            "- Anything you can answer well from your own knowledge\n\n"
            "**Delegate to researcher** ONLY when the task requires web research "
            "or current events you cannot answer from knowledge.\n"
            "**Delegate to coder** ONLY for code writing, debugging, or file operations.\n"
            "**Delegate to planner** ONLY for multi-step project plans.\n\n"
            "When delegating, always specify `to_agent_id` explicitly. "
            "Never delegate simple questions.\n",
            encoding="utf-8",
        )
        changed = True

    heartbeat = main_dir / "heartbeat.md"
    if not heartbeat.exists():
        heartbeat.write_text(
            "---\n"
            "agent_id: main\n"
            f"updated_at: {datetime.now(UTC).isoformat()}\n"
            "---\n\n"
            "## Last Action\n"
            "Seeded default main agent bundle.\n",
            encoding="utf-8",
        )
        changed = True

    return changed


def sync_seed_skills(conn: sqlite3.Connection, skills_dir: Path = Path("skills")) -> dict[str, int]:
    """Sync seed skills from disk into the skills database table."""
    return SkillsService().sync_from_disk(conn, skills_dir=skills_dir)
