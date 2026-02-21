from pathlib import Path

from jarvis.db.connection import get_conn
from jarvis.memory.skills import SkillsService


def test_skills_service_crud_scope_and_version() -> None:
    svc = SkillsService()
    with get_conn() as conn:
        first = svc.put(
            conn,
            slug="deploy-checklist",
            title="Deploy Checklist",
            content="Initial content",
            scope="global",
            pinned=False,
            source="agent",
        )
        second = svc.put(
            conn,
            slug="deploy-checklist",
            title="Deploy Checklist",
            content="Coder-specific",
            scope="coder",
            owner_id="coder",
            pinned=True,
            source="agent",
        )
        updated = svc.put(
            conn,
            slug="deploy-checklist",
            title="Deploy Checklist",
            content="Updated global content",
            scope="global",
            pinned=False,
            source="agent",
        )

        coder_view = svc.get(conn, slug="deploy-checklist", scope="coder")
        planner_view = svc.get(conn, slug="deploy-checklist", scope="planner")
        listed = svc.list_skills(conn, scope="coder", limit=10)
        pinned = svc.get_pinned(conn, scope="coder")
        search = svc.search(conn, query="global", scope="coder", limit=5)
        deleted = svc.delete(conn, slug="deploy-checklist", scope="coder")

    assert int(first["version"]) == 1
    assert int(second["version"]) == 1
    assert int(updated["version"]) == 2
    assert coder_view is not None
    assert coder_view["scope"] == "coder"
    assert planner_view is not None
    assert planner_view["scope"] == "global"
    assert any(item["scope"] == "coder" for item in listed)
    assert any(item["scope"] == "global" for item in listed)
    assert len(pinned) == 1
    assert pinned[0]["scope"] == "coder"
    assert any("Updated global" in str(item["content"]) for item in search)
    assert deleted is True


def test_skills_service_sync_from_disk(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "jarvis-project.md").write_text(
        "---\n"
        "slug: jarvis-project\n"
        "pinned: true\n"
        "---\n\n"
        "# Jarvis Project\n\n"
        "## Purpose\n"
        "Seed content\n",
        encoding="utf-8",
    )
    (skills_dir / "skills-standard.md").write_text(
        "---\n"
        "slug: skills-standard\n"
        "pinned: false\n"
        "---\n\n"
        "# Skills Standard\n\n"
        "## Purpose\n"
        "Template content\n",
        encoding="utf-8",
    )

    svc = SkillsService()
    with get_conn() as conn:
        first = svc.sync_from_disk(conn, skills_dir)
        second = svc.sync_from_disk(conn, skills_dir)
        (skills_dir / "skills-standard.md").write_text(
            "---\n"
            "slug: skills-standard\n"
            "pinned: false\n"
            "---\n\n"
            "# Skills Standard\n\n"
            "## Purpose\n"
            "Updated template content\n",
            encoding="utf-8",
        )
        third = svc.sync_from_disk(conn, skills_dir)
        project = svc.get(conn, slug="jarvis-project", scope="global")
        standard = svc.get(conn, slug="skills-standard", scope="global")

    assert first == {"inserted": 2, "updated": 0, "skipped": 0}
    assert second == {"inserted": 0, "updated": 0, "skipped": 2}
    assert third == {"inserted": 0, "updated": 1, "skipped": 1}
    assert project is not None and project["source"] == "seed" and project["pinned"] is True
    assert standard is not None and "Updated template content" in str(standard["content"])


def test_skills_service_install_package_and_history(tmp_path: Path) -> None:
    package_dir = tmp_path / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "manifest.yaml").write_text(
        "slug: deploy-helper\n"
        "title: Deploy Helper\n"
        "version: 1.0.0\n"
        "pinned: true\n"
        "tools_required:\n"
        "  - echo\n"
        "files:\n"
        "  - SKILL.md\n",
        encoding="utf-8",
    )
    (package_dir / "SKILL.md").write_text("# Deploy Helper\n\nDo deployment checks.\n")

    svc = SkillsService()
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO principals(id, principal_type, created_at) "
                "VALUES(?,?,datetime('now'))"
            ),
            ("main", "agent"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO tool_permissions(principal_id, tool_name, effect) VALUES(?,?,?)",
            ("main", "echo", "allow"),
        )
        installed = svc.install_package(
            conn,
            package_path=str(package_dir),
            scope="global",
            actor_id="tester",
            install_source="test",
        )
        skill = svc.get(conn, slug="deploy-helper", scope="global")
        history = svc.get_install_history(conn, slug="deploy-helper")
        updates = svc.check_updates(conn, scope="global")

    assert installed["slug"] == "deploy-helper"
    assert installed["package_version"] == "1.0.0"
    assert installed["warnings"] == []
    assert skill is not None
    assert skill["package_version"] == "1.0.0"
    assert len(history) == 1
    assert history[0]["action"] == "install"
    assert any(item["slug"] == "deploy-helper" for item in updates)
