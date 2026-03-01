from __future__ import annotations

import json

import pytest

from jarvis.cli.checks import CheckResult
from jarvis.cli.doctor import run_doctor


def _always_pass(name: str = "ok") -> CheckResult:
    return CheckResult(name=name, passed=True, message="ok")


def _patch_common_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_python_version",
        lambda: _always_pass("python"),
    )
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_env_file",
        lambda _root: _always_pass("env"),
    )
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_config_loads",
        lambda: _always_pass("config"),
    )
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_config_validates",
        lambda: _always_pass("config.validate"),
    )
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_http_service",
        lambda *args, **kwargs: _always_pass("http"),
    )
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_database",
        lambda _db: _always_pass("db"),
    )
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_migrations_applied",
        lambda _db: _always_pass("migrations"),
    )
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_db_path_consistency",
        lambda _db, _root: _always_pass("db_path"),
    )
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_agent_bundles",
        lambda _path: _always_pass("bundles"),
    )
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_api_running",
        lambda: _always_pass("api"),
    )
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_task_runner",
        lambda: _always_pass("runner"),
    )

    class _Settings:
        ollama_base_url = "http://localhost:11434"
        sglang_base_url = "http://localhost:3000/v1"
        searxng_base_url = "http://localhost:8080"
        app_db = "app.db"

    monkeypatch.setattr("jarvis.config.Settings", _Settings)


def test_doctor_json_output_is_machine_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_tool_exists",
        lambda tool: _always_pass(f"tool {tool}"),
    )
    _patch_common_checks(monkeypatch)

    run_doctor(json_output=True)
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert isinstance(payload["results"], list)
    assert "System Tools" not in out


def test_doctor_json_failure_sets_non_zero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "jarvis.cli.doctor.check_tool_exists",
        lambda _tool: CheckResult(name="tool", passed=False, message="missing"),
    )
    _patch_common_checks(monkeypatch)

    with pytest.raises(SystemExit, match="1"):
        run_doctor(json_output=True)
