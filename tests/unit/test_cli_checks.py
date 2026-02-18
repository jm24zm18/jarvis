"""Tests for jarvis.cli.checks primitives."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from jarvis.cli.checks import (
    CheckResult,
    check_agent_bundles,
    check_database,
    check_env_file,
    check_http_service,
    check_migrations_applied,
    check_python_version,
    check_tool_exists,
)


class TestCheckResult:
    def test_fields(self) -> None:
        r = CheckResult(name="test", passed=True, message="ok")
        assert r.name == "test"
        assert r.passed is True
        assert r.message == "ok"
        assert r.fix_hint == ""
        assert r.fix_fn is None

    def test_with_hint(self) -> None:
        r = CheckResult(name="x", passed=False, message="bad", fix_hint="do this")
        assert r.fix_hint == "do this"


class TestCheckToolExists:
    def test_found(self) -> None:
        with patch("jarvis.cli.checks.shutil.which", return_value="/usr/bin/git"):
            result = check_tool_exists("git")
        assert result.passed is True

    def test_missing(self) -> None:
        with patch("jarvis.cli.checks.shutil.which", return_value=None):
            result = check_tool_exists("nonexistent")
        assert result.passed is False
        assert "not found" in result.message


class TestCheckPythonVersion:
    def test_correct_version(self) -> None:
        with patch("jarvis.cli.checks.sys") as mock_sys:
            mock_sys.version_info = type("V", (), {"major": 3, "minor": 12, "micro": 5})()
            result = check_python_version()
        assert result.passed is True

    def test_wrong_minor(self) -> None:
        with patch("jarvis.cli.checks.sys") as mock_sys:
            mock_sys.version_info = type("V", (), {"major": 3, "minor": 11, "micro": 0})()
            result = check_python_version()
        assert result.passed is False


class TestCheckEnvFile:
    def test_exists(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("APP_ENV=dev\n")
        assert check_env_file(tmp_path).passed is True

    def test_missing(self, tmp_path: Path) -> None:
        assert check_env_file(tmp_path).passed is False

    def test_missing_with_fix_creates_env(self, tmp_path: Path) -> None:
        (tmp_path / ".env.example").write_text("APP_ENV=dev\n")
        result = check_env_file(tmp_path)
        assert result.passed is False
        assert result.fix_fn is not None
        assert result.fix_fn() is True
        assert (tmp_path / ".env").is_file()


class TestCheckHttpService:
    def test_ok(self) -> None:
        mock_resp = MagicMock(status_code=200)
        with patch("jarvis.cli.checks.httpx.get", return_value=mock_resp):
            result = check_http_service("Ollama", "http://localhost:11434", "/api/tags")
        assert result.passed is True

    def test_server_error(self) -> None:
        mock_resp = MagicMock(status_code=500)
        with patch("jarvis.cli.checks.httpx.get", return_value=mock_resp):
            result = check_http_service("Ollama", "http://localhost:11434", "/api/tags")
        assert result.passed is False

    def test_connection_error(self) -> None:
        with patch("jarvis.cli.checks.httpx.get", side_effect=ConnectionError("refused")):
            result = check_http_service("Ollama", "http://localhost:11434", "/api/tags")
        assert result.passed is False

    def test_dns_error_classification(self) -> None:
        request = httpx.Request("GET", "http://example.invalid/health")
        err = httpx.ConnectError(
            "Temporary failure in name resolution",
            request=request,
        )
        with patch("jarvis.cli.checks.httpx.get", side_effect=err):
            result = check_http_service("SGLang", "http://example.invalid", "/health")
        assert result.passed is False
        assert "[dns_resolution]" in result.message
        assert "DNS lookup failed" in result.fix_hint

    def test_timeout_error_classification(self) -> None:
        request = httpx.Request("GET", "http://localhost:11434/api/tags")
        err = httpx.ConnectTimeout("timed out", request=request)
        with patch("jarvis.cli.checks.httpx.get", side_effect=err):
            result = check_http_service("Ollama", "http://localhost:11434", "/api/tags")
        assert result.passed is False
        assert "[timeout]" in result.message
        assert "timed out" in result.fix_hint.lower()


class TestCheckDatabase:
    def test_exists_and_readable(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t(id INTEGER)")
        conn.close()
        result = check_database(str(db_path))
        assert result.passed is True

    def test_not_found(self, tmp_path: Path) -> None:
        result = check_database(str(tmp_path / "missing.db"))
        assert result.passed is False


class TestCheckMigrationsApplied:
    def test_all_applied(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations"
            "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        # Create fake migration files and mark them applied
        migrations_dir = tmp_path / "mig"
        migrations_dir.mkdir()
        (migrations_dir / "001_init.sql").write_text("SELECT 1;")
        (migrations_dir / "002_more.sql").write_text("SELECT 1;")
        conn.execute(
            "INSERT INTO schema_migrations VALUES('001_init.sql', '2024-01-01')"
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES('002_more.sql', '2024-01-01')"
        )
        conn.commit()
        conn.close()

        with patch("jarvis.db.migrations.runner.MIGRATIONS_DIR", migrations_dir):
            result = check_migrations_applied(str(db_path))
        assert result.passed is True
        assert "2/2" in result.message

    def test_missing_migration(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations"
            "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES('001_init.sql', '2024-01-01')"
        )
        conn.commit()
        conn.close()

        migrations_dir = tmp_path / "mig"
        migrations_dir.mkdir()
        (migrations_dir / "001_init.sql").write_text("SELECT 1;")
        (migrations_dir / "002_more.sql").write_text("SELECT 1;")

        with patch("jarvis.db.migrations.runner.MIGRATIONS_DIR", migrations_dir):
            result = check_migrations_applied(str(db_path))
        assert result.passed is False
        assert "002_more.sql" in result.message


class TestCheckAgentBundles:
    def test_valid_bundles(self, tmp_path: Path) -> None:
        bundle = tmp_path / "main"
        bundle.mkdir()
        (bundle / "identity.md").write_text("id")
        (bundle / "soul.md").write_text("soul")
        (bundle / "heartbeat.md").write_text("hb")
        result = check_agent_bundles(tmp_path)
        assert result.passed is True
        assert "1 bundles" in result.message

    def test_missing_file(self, tmp_path: Path) -> None:
        bundle = tmp_path / "main"
        bundle.mkdir()
        (bundle / "identity.md").write_text("id")
        # missing soul.md and heartbeat.md
        result = check_agent_bundles(tmp_path)
        assert result.passed is False

    def test_no_bundles(self, tmp_path: Path) -> None:
        result = check_agent_bundles(tmp_path)
        assert result.passed is False

    def test_missing_dir(self, tmp_path: Path) -> None:
        result = check_agent_bundles(tmp_path / "nonexistent")
        assert result.passed is False
