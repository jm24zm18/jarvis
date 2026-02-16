from pathlib import Path

from jarvis.tools.persona import update_persona


def test_update_persona_writes_soul_markdown(tmp_path: Path) -> None:
    result = update_persona("main", "# Soul\nBe concise.", agent_root=tmp_path / "agents")
    assert result["ok"] is True
    path = tmp_path / "agents" / "main" / "soul.md"
    assert path.is_file()
    assert "Be concise." in path.read_text(encoding="utf-8")


def test_update_persona_rejects_unknown_agent(tmp_path: Path) -> None:
    result = update_persona("unknown", "x", agent_root=tmp_path / "agents")
    assert result["ok"] is False
    assert "unknown agent_id" in str(result["error"])
