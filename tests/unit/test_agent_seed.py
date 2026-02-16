from pathlib import Path

from jarvis.agents.seed import ensure_main_agent_seed


def test_ensure_main_agent_seed_creates_missing_files(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    changed = ensure_main_agent_seed(root)
    assert changed is True
    assert (root / "main" / "identity.md").is_file()
    assert (root / "main" / "soul.md").is_file()
    assert (root / "main" / "heartbeat.md").is_file()
    identity = (root / "main" / "identity.md").read_text()
    assert "web_search" in identity
    assert "exec_host" in identity
    assert "skill_list" in identity
    assert "skill_read" in identity
    assert "skill_write" in identity
    assert "update_persona" in identity


def test_ensure_main_agent_seed_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    first = ensure_main_agent_seed(root)
    second = ensure_main_agent_seed(root)
    assert first is True
    assert second is False
