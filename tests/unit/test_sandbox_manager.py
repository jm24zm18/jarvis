"""Tests for the selfupdate Docker sandbox manager."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jarvis.errors import ConfigError
from jarvis.selfupdate.sandbox import (
    SandboxContext,
    create_sandbox,
    generate_diff_summary,
    run_in_sandbox,
)


def _make_ctx(tmp_path: Path) -> SandboxContext:
    return SandboxContext(
        sandbox_id="jarvis-sandbox-test",
        worktree_path=tmp_path / "worktree",
        image="jarvis-sandbox:latest",
    )


# ---------------------------------------------------------------------------
# run_in_sandbox — success path
# ---------------------------------------------------------------------------

def test_run_in_sandbox_success(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    fake_proc = SimpleNamespace(
        returncode=0,
        stdout="ok\n",
        stderr="",
    )
    with patch("jarvis.selfupdate.sandbox.subprocess.run", return_value=fake_proc) as mock_run:
        result = run_in_sandbox(ctx, ["ruff", "check", "src"])

    assert result.ok is True
    assert result.exit_code == 0
    assert result.stdout == "ok\n"
    # Docker run was called
    call_args = mock_run.call_args[0][0]
    assert "docker" in call_args
    assert "run" in call_args
    assert "--network=none" in call_args


# ---------------------------------------------------------------------------
# run_in_sandbox — failure path
# ---------------------------------------------------------------------------

def test_run_in_sandbox_failure(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    fake_proc = SimpleNamespace(
        returncode=1,
        stdout="",
        stderr="lint error found\n",
    )
    with patch("jarvis.selfupdate.sandbox.subprocess.run", return_value=fake_proc):
        result = run_in_sandbox(ctx, ["ruff", "check", "src"])

    assert result.ok is False
    assert result.exit_code == 1
    assert "lint error" in result.stderr


# ---------------------------------------------------------------------------
# run_in_sandbox — timeout
# ---------------------------------------------------------------------------

def test_run_in_sandbox_timeout(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    with patch(
        "jarvis.selfupdate.sandbox.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["docker"], timeout=1),
    ):
        result = run_in_sandbox(ctx, ["pytest", "tests"], timeout=1)

    assert result.ok is False
    assert "timeout" in result.stderr.lower()


# ---------------------------------------------------------------------------
# generate_diff_summary — detects migration files
# ---------------------------------------------------------------------------

def test_generate_diff_summary_detects_migrations(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()

    stat_proc = SimpleNamespace(returncode=0, stdout=" 2 files changed\n", stderr="")
    name_proc = SimpleNamespace(
        returncode=0,
        stdout="src/jarvis/db/migrations/061_cbac_scopes.sql\nsrc/jarvis/auth/service.py\n",
        stderr="",
    )

    with patch(
        "jarvis.selfupdate.sandbox.subprocess.run",
        side_effect=[stat_proc, name_proc],
    ):
        summary = generate_diff_summary(
            repo_path=str(tmp_path / "repo"),
            worktree_path=worktree,
            patch_path=tmp_path / "proposal.diff",
        )

    assert summary["files_changed"] == 2
    assert summary["migration_pending"] is True
    assert any("061_cbac_scopes" in f for f in summary["migration_files"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Docker unavailable raises ConfigError
# ---------------------------------------------------------------------------

def test_docker_unavailable_raises_config_error(tmp_path: Path) -> None:
    fake_proc = SimpleNamespace(
        returncode=1,
        stdout="",
        stderr="Cannot connect to the Docker daemon",
    )
    with patch("jarvis.selfupdate.sandbox.subprocess.run", return_value=fake_proc):
        with pytest.raises(ConfigError, match="Docker"):
            create_sandbox("trc_test", tmp_path / "worktree", "jarvis-sandbox:latest")
