import subprocess
from pathlib import Path

from jarvis.config import get_settings
from jarvis.tasks import devswarm


def test_parse_github_repo_supports_https_and_ssh() -> None:
    assert devswarm._parse_github_repo("https://github.com/acme/jarvis.git") == ("acme", "jarvis")
    assert devswarm._parse_github_repo("git@github.com:acme/jarvis.git") == ("acme", "jarvis")


def test_parse_github_repo_rejects_unknown_host() -> None:
    assert devswarm._parse_github_repo("https://gitlab.com/acme/jarvis.git") is None


def test_status_from_checks_ready_for_review() -> None:
    checks = {
        "gates": {
            "pr_exists": True,
            "pr_base_dev": True,
            "ci_green": True,
            "branch_up_to_date_with_dev": True,
            "tmux_alive": True,
            "branch_exists": True,
        },
        "ci_state": "success",
    }
    assert devswarm._status_from_checks(checks) == "ready_for_review"


def test_status_from_checks_needs_attention_on_ci_failure() -> None:
    checks = {
        "gates": {
            "pr_exists": True,
            "pr_base_dev": True,
            "ci_green": False,
            "branch_up_to_date_with_dev": True,
            "tmux_alive": True,
            "branch_exists": True,
        },
        "ci_state": "failure",
    }
    assert devswarm._status_from_checks(checks) == "needs_attention"


def test_opencode_command_uses_prompt_file_when_supported(monkeypatch) -> None:
    devswarm._OPENCODE_PROMPT_FILE_SUPPORTED = None
    monkeypatch.setenv("DEVSWARM_OPENCODE_COMMAND_TEMPLATE", "")
    get_settings.cache_clear()

    def _fake_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout_s
        if argv == ["opencode", "run", "--help"]:
            return subprocess.CompletedProcess(argv, 0, stdout="--prompt-file", stderr="")
        raise AssertionError(f"unexpected argv: {argv}")

    monkeypatch.setattr(devswarm, "_run", _fake_run)
    cmd = devswarm._opencode_command(Path("/tmp/task.md"), "qwen", "sch_123")
    assert "--model lmstudio/qwen" in cmd
    assert "--prompt-file" in cmd
    assert "-f " not in cmd


def test_opencode_command_falls_back_to_file_flag(monkeypatch) -> None:
    devswarm._OPENCODE_PROMPT_FILE_SUPPORTED = None
    monkeypatch.setenv("DEVSWARM_OPENCODE_COMMAND_TEMPLATE", "")
    get_settings.cache_clear()

    def _fake_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout_s
        if argv == ["opencode", "run", "--help"]:
            return subprocess.CompletedProcess(argv, 0, stdout="--format", stderr="")
        raise AssertionError(f"unexpected argv: {argv}")

    monkeypatch.setattr(devswarm, "_run", _fake_run)
    cmd = devswarm._opencode_command(Path("/tmp/task.md"), "qwen", "sch_123")
    assert "-m lmstudio/qwen" in cmd
    assert "-f " in cmd
    assert " -- " in cmd
    assert "--prompt-file" not in cmd


def test_opencode_command_prefers_custom_template(monkeypatch) -> None:
    monkeypatch.setenv(
        "DEVSWARM_OPENCODE_COMMAND_TEMPLATE",
        'opencode run --model "{model}" --file "{prompt_file}"',
    )
    get_settings.cache_clear()
    cmd = devswarm._opencode_command(Path("/tmp/task.md"), "qwen", "sch_123")
    assert '--model "lmstudio/qwen"' in cmd
    assert "--file" in cmd
    assert "/tmp/task.md" in cmd


def test_opencode_command_rejects_invalid_template(monkeypatch) -> None:
    monkeypatch.setenv("DEVSWARM_OPENCODE_COMMAND_TEMPLATE", 'opencode run "{missing}"')
    get_settings.cache_clear()
    try:
        devswarm._opencode_command(Path("/tmp/task.md"), "qwen", "sch_123")
    except RuntimeError as exc:
        assert "invalid DEVSWARM_OPENCODE_COMMAND_TEMPLATE" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for invalid template")


def test_validate_opencode_preflight_rejects_invalid_json(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "opencode.json"
    config_path.write_text('{"providers":{}\\n', encoding="utf-8")
    monkeypatch.delenv("OPENCODE_CONFIG_PATH", raising=False)

    def _fake_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout_s
        if argv == ["opencode", "run", "--help"]:
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")
        raise AssertionError(f"unexpected argv: {argv}")

    monkeypatch.setattr(devswarm, "_run", _fake_run)
    try:
        devswarm._validate_opencode_preflight(tmp_path)
    except RuntimeError as exc:
        text = str(exc)
        assert "invalid OpenCode config" in text
        assert str(config_path) in text
    else:
        raise AssertionError("expected RuntimeError for invalid opencode config")


def test_create_task_returns_error_when_preflight_fails(monkeypatch) -> None:
    monkeypatch.setattr(devswarm, "_normalize_repo_path", lambda _: Path("/tmp"))
    monkeypatch.setattr(
        devswarm,
        "_validate_opencode_preflight",
        lambda _repo: (_ for _ in ()).throw(RuntimeError("preflight failed")),
    )

    result = devswarm.create_task(description="ship it", repo_path="/tmp/repo")
    assert result["ok"] is False
    assert result["error"] == "preflight failed"


def test_validate_opencode_preflight_rejects_legacy_schema(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "opencode.json"
    config_path.write_text(
        '{"providers":{"lmstudio":{}},"models":[],"defaultModel":"x"}',
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENCODE_CONFIG_PATH", raising=False)

    def _fake_run(
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout_s
        if argv == ["opencode", "run", "--help"]:
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")
        raise AssertionError(f"unexpected argv: {argv}")

    monkeypatch.setattr(devswarm, "_run", _fake_run)
    try:
        devswarm._validate_opencode_preflight(tmp_path)
    except RuntimeError as exc:
        assert "legacy schema detected" in str(exc)
        assert str(config_path) in str(exc)
    else:
        raise AssertionError("expected RuntimeError for legacy schema")


def test_normalize_opencode_model_keeps_qualified_model() -> None:
    assert devswarm._normalize_opencode_model("openclaw/openai/gpt-oss-120b") == (
        "openclaw/openai/gpt-oss-120b"
    )


def test_normalize_opencode_model_prefixes_bare_model() -> None:
    assert devswarm._normalize_opencode_model("qwen3.5-122b-a10b") == (
        "lmstudio/qwen3.5-122b-a10b"
    )


def test_normalize_opencode_model_rejects_empty() -> None:
    try:
        devswarm._normalize_opencode_model("   ")
    except RuntimeError as exc:
        assert "model is required" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for empty model")
