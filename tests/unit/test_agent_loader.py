from pathlib import Path

import pytest

from jarvis.agents.loader import get_all_agent_ids, load_agent_bundle, load_agent_registry

ALL_AGENT_IDS = (
    "main", "researcher", "planner", "coder",
    "tester", "lintfixer", "api_guardian", "data_migrator",
    "web_builder", "security_reviewer", "docs_keeper", "release_ops",
)


def _write_bundle(root: Path, agent_id: str) -> None:
    bundle_dir = root / agent_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "identity.md").write_text(
        (
            "---\n"
            f"agent_id: {agent_id}\n"
            "allowed_tools:\n"
            "  - echo\n"
            "risk_tier: low\n"
            "max_actions_per_step: 4\n"
            "allowed_paths:\n"
            "  - /tmp\n"
            "can_request_privileged_change: false\n"
            "---\n\n"
            f"# {agent_id.title()} Agent\n"
        ),
        encoding="utf-8",
    )
    (bundle_dir / "soul.md").write_text(f"# {agent_id.title()} Soul\n", encoding="utf-8")
    (bundle_dir / "heartbeat.md").write_text(
        (
            "---\n"
            f"agent_id: {agent_id}\n"
            "updated_at: 2026-02-15T00:00:00+00:00\n"
            "---\n\n"
            "## Last Action\n"
            "Seeded in test.\n"
        ),
        encoding="utf-8",
    )


def test_load_agent_registry_discovers_all(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    for agent_id in ALL_AGENT_IDS:
        _write_bundle(root, agent_id)
    bundles = load_agent_registry(root)
    assert set(ALL_AGENT_IDS).issubset(set(bundles.keys()))
    assert "echo" in bundles["main"].allowed_tools


def test_get_all_agent_ids_discovers_all(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    for agent_id in ALL_AGENT_IDS:
        _write_bundle(root, agent_id)
    discovered = get_all_agent_ids(root)
    assert set(ALL_AGENT_IDS) == discovered


def test_missing_required_file_fails(tmp_path: Path) -> None:
    agent_dir = tmp_path / "broken"
    agent_dir.mkdir()
    (agent_dir / "identity.md").write_text("# identity")
    (agent_dir / "soul.md").write_text("# soul")

    with pytest.raises(RuntimeError):
        load_agent_bundle(agent_dir)
