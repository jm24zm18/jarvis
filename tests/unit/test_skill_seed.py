from pathlib import Path

from jarvis.agents.seed import ensure_main_agent_seed, sync_seed_skills
from jarvis.db.connection import get_conn
from jarvis.memory.skills import SkillsService


def test_sync_seed_skills_from_directory(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "jarvis-project.md").write_text(
        "---\n"
        "slug: jarvis-project\n"
        "pinned: true\n"
        "---\n\n"
        "# Jarvis Project\n\n"
        "## Purpose\n"
        "Seeded\n",
        encoding="utf-8",
    )

    with get_conn() as conn:
        first = sync_seed_skills(conn, skills_dir=skills_dir)
        second = sync_seed_skills(conn, skills_dir=skills_dir)
        item = SkillsService().get(conn, slug="jarvis-project", scope="global")

    assert first == {"inserted": 1, "updated": 0, "skipped": 0}
    assert second == {"inserted": 0, "updated": 0, "skipped": 1}
    assert item is not None
    assert item["source"] == "seed"
    assert item["pinned"] is True


def test_ensure_main_agent_seed_includes_skill_tools(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    changed = ensure_main_agent_seed(root)
    identity = (root / "main" / "identity.md").read_text(encoding="utf-8")

    assert changed is True
    assert "skill_list" in identity
    assert "skill_read" in identity
    assert "skill_write" in identity
