"""Unit tests for the Ralph PLAN.md parser."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from jarvis.selfupdate.ralph_plan import mark_task_done, mark_task_failed, next_ralph_task


SAMPLE_PLAN = textwrap.dedent("""\
    # Jarvis Plan

    ## Ralph Sprint v2.0 (2026-02-22 → 2026-02-28)

    - [ ] Implement CLI runner for single iteration
          Accept: command exits 0 and prints iteration result to stdout

    - [ ] Add run_ralph_iteration task with thread-based dispatch
          Accept: task registered; runs agent_step; marks done on success

    - [x] Already completed task
          Accept: this should be skipped

    ## Other Section

    - [ ] This task is outside Ralph Sprint and should be ignored
""")


@pytest.fixture()
def plan_file(tmp_path: Path) -> Path:
    p = tmp_path / "PLAN.md"
    p.write_text(SAMPLE_PLAN, encoding="utf-8")
    return p


def test_next_ralph_task_returns_first_unchecked(plan_file: Path) -> None:
    task = next_ralph_task(str(plan_file))
    assert task is not None
    assert "Implement CLI runner" in str(task["text"])
    assert "command exits 0" in str(task["accept"])
    assert isinstance(task["line_number"], int)
    assert isinstance(task["slug"], str)
    assert len(str(task["slug"])) <= 40


def test_next_ralph_task_skips_checked_items(plan_file: Path) -> None:
    # Mark the first task done and verify next_ralph_task returns the second.
    task1 = next_ralph_task(str(plan_file))
    assert task1 is not None
    mark_task_done(task1, str(plan_file))

    task2 = next_ralph_task(str(plan_file))
    assert task2 is not None
    assert "run_ralph_iteration" in str(task2["text"])


def test_next_ralph_task_returns_none_when_all_done(plan_file: Path) -> None:
    task = next_ralph_task(str(plan_file))
    assert task is not None
    mark_task_done(task, str(plan_file))

    task2 = next_ralph_task(str(plan_file))
    assert task2 is not None
    mark_task_done(task2, str(plan_file))

    result = next_ralph_task(str(plan_file))
    assert result is None


def test_next_ralph_task_ignores_tasks_outside_section(plan_file: Path) -> None:
    # Exhaust all Ralph Sprint tasks, confirm no tasks from "Other Section".
    while True:
        task = next_ralph_task(str(plan_file))
        if task is None:
            break
        mark_task_done(task, str(plan_file))

    content = plan_file.read_text()
    assert "- [ ] This task is outside" in content  # not modified


def test_mark_task_done_modifies_checkbox(plan_file: Path) -> None:
    task = next_ralph_task(str(plan_file))
    assert task is not None
    mark_task_done(task, str(plan_file))

    content = plan_file.read_text()
    assert "- [x] Implement CLI runner" in content


def test_mark_task_failed_adds_note(plan_file: Path) -> None:
    task = next_ralph_task(str(plan_file))
    assert task is not None
    mark_task_failed(task, "tests failed in CI", str(plan_file))

    content = plan_file.read_text()
    assert "FAILED: tests failed in CI" in content
    # Box should still be unchecked.
    assert "- [ ] Implement CLI runner" in content


def test_section_not_found_raises(tmp_path: Path) -> None:
    plan = tmp_path / "PLAN.md"
    plan.write_text("# No Ralph Sprint section here\n\n- [ ] Some task\n")
    with pytest.raises(RuntimeError, match="Ralph Sprint section not found"):
        next_ralph_task(str(plan))


def test_atomic_write_on_mark_done(plan_file: Path) -> None:
    task = next_ralph_task(str(plan_file))
    assert task is not None
    mark_task_done(task, str(plan_file))
    # File should still be valid UTF-8 and parseable.
    content = plan_file.read_text(encoding="utf-8")
    assert "## Ralph Sprint" in content


def test_slug_is_url_safe(plan_file: Path) -> None:
    task = next_ralph_task(str(plan_file))
    assert task is not None
    slug = str(task["slug"])
    import re
    assert re.match(r"^[a-z0-9-]+$", slug), f"slug not URL-safe: {slug!r}"
