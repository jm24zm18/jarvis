from pathlib import Path

from jarvis.repo_index.builder import build_repo_index, write_repo_index


def test_repo_index_contains_expected_sections() -> None:
    payload = build_repo_index(Path.cwd())
    assert "entrypoints" in payload
    assert "commands" in payload
    assert "migrations" in payload
    assert "protected_modules" in payload


def test_repo_index_write_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text("test:\n\techo ok\n")
    (tmp_path / "src/jarvis/db/migrations").mkdir(parents=True)
    (tmp_path / "src/jarvis/db/migrations/001_initial.sql").write_text("-- sql\n")
    (tmp_path / "src/jarvis/main.py").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "src/jarvis/main.py").write_text("# main\n")
    (tmp_path / "src/jarvis/routes/api").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src/jarvis/routes/api/system.py").write_text("# route\n")
    (tmp_path / "agents/main").mkdir(parents=True, exist_ok=True)
    (tmp_path / "agents/main/identity.md").write_text("allowed_tools:\n  - echo\n")

    out_path, hash_path = write_repo_index(tmp_path)
    assert out_path.exists()
    assert hash_path.exists()
