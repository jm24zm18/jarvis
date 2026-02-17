"""Tests for the test-gates CLI command."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from jarvis.cli.test_gates import GATES, run_test_gates


def _make_completed(returncode: int = 0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(args=[], returncode=returncode)


def test_gates_list_not_empty():
    assert len(GATES) >= 6


def test_all_pass(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("jarvis.cli.test_gates.subprocess.run", return_value=_make_completed(0)):
        run_test_gates()
    out = capsys.readouterr().out
    assert "passed" in out


def test_failure_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("jarvis.cli.test_gates.subprocess.run", return_value=_make_completed(1)):
        with pytest.raises(SystemExit, match="1"):
            run_test_gates()
    out = capsys.readouterr().out
    assert "failed" in out


def test_fail_fast_stops_early() -> None:
    with patch("jarvis.cli.test_gates.subprocess.run", return_value=_make_completed(1)) as mock_run:
        with pytest.raises(SystemExit, match="1"):
            run_test_gates(fail_fast=True)
    # Should have stopped after the first gate
    assert mock_run.call_count == 1


def test_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("jarvis.cli.test_gates.subprocess.run", return_value=_make_completed(0)):
        run_test_gates(json_output=True)
    out = capsys.readouterr().out
    assert '"name"' in out
    assert '"passed"' in out
