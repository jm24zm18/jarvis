"""CLI commands for the Ralph autonomous improvement loop."""

from __future__ import annotations

import json
import sys

import click

from jarvis.config import get_settings
from jarvis.ids import new_id
from jarvis.selfupdate.ralph_plan import mark_task_done, mark_task_failed, next_ralph_task
from jarvis.tasks.ralph import (
    read_ralph_progress,
    run_ralph_iteration,
)


@click.group("ralph")
def ralph_group() -> None:
    """Ralph autonomous improvement loop."""


def _check_safety_limits(
    progress: dict[str, object],
    max_failures: int,
) -> str | None:
    """Return an error message if safety limits are exceeded, else None."""
    raw_failures = progress.get("failures")
    failures = int(raw_failures) if isinstance(raw_failures, int | float | str) else 0
    if failures >= max_failures:
        return (
            f"Ralph halted: failure count {failures} >= RALPH_MAX_FAILURES={max_failures}. "
            "Resolve failures before running again."
        )
    return None


def _run_once(
    *,
    dry_run: bool,
    plan_path: str,
    repo_path: str,
    timeout_s: float,
    max_failures: int,
) -> str:
    """Execute one Ralph iteration. Returns status: 'success'|'failed'|'gate_fail'|'no_tasks'."""
    task = next_ralph_task(plan_path)
    if task is None:
        click.echo("No pending Ralph tasks in ## Ralph Sprint section.")
        return "no_tasks"

    task_text = str(task["text"])
    task_slug = str(task["slug"])
    accept = task.get("accept")
    accept_str = str(accept) if accept is not None else None

    click.echo(f"Ralph task: {task_text[:100]}")
    if accept_str:
        click.echo(f"Accept:     {accept_str[:100]}")

    if dry_run:
        click.echo("[dry-run] Would dispatch agent_step for this task.")
        click.echo(f"[dry-run] Slug: {task_slug}")
        click.echo(f"[dry-run] Plan path: {plan_path}")
        return "dry_run"

    # Check safety limits before dispatching.
    progress = read_ralph_progress(repo_path)
    limit_err = _check_safety_limits(progress, max_failures)
    if limit_err:
        click.echo(limit_err, err=True)
        return "halted"

    run_id = new_id("ralph")
    trace_id = new_id("trc")

    click.echo(f"run_id: {run_id}")
    click.echo("Dispatching Ralph iteration (this may take several minutes)...")

    result = run_ralph_iteration(
        run_id=run_id,
        task_text=task_text,
        task_slug=task_slug,
        accept_criteria=accept_str,
        trace_id=trace_id,
        dry_run=False,
        repo_path=repo_path,
        timeout_s=timeout_s,
    )

    status = str(result.get("status", "failed"))
    click.echo(f"Result: {status}")

    if status == "success":
        click.echo(f"  Summary: {result.get('outcome_detail', '')}")
        click.echo(f"  Commit: {result.get('commit_detail', '')}")
        click.echo(f"  Gates: {result.get('gate_detail', '')}")
        try:
            mark_task_done(task, plan_path)
            click.echo("  Task marked done in PLAN.md.")
        except Exception as exc:
            click.echo(f"  Warning: could not mark task done: {exc}", err=True)
    elif status == "gate_fail":
        click.echo(f"  Gate failure: {result.get('gate_detail', '')}")
        try:
            mark_task_failed(task, str(result.get("gate_detail", "gate failed"))[:200], plan_path)
        except Exception as exc:
            click.echo(f"  Warning: could not record failure: {exc}", err=True)
    else:
        reason = str(result.get("reason", "unknown"))
        click.echo(f"  Reason: {reason}")
        try:
            mark_task_failed(task, reason[:200], plan_path)
        except Exception as exc:
            click.echo(f"  Warning: could not record failure: {exc}", err=True)

    return status


@ralph_group.command("run")
@click.option(
    "--once", "mode", flag_value="once", default=True, help="Run one iteration (default)."
)
@click.option(
    "--loop", "mode", flag_value="loop", help="Loop until no tasks remain or limit hit."
)
@click.option(
    "--max", "max_iterations", default=None, type=int, help="Maximum iterations (loop mode)."
)
@click.option(
    "--dry-run", is_flag=True, help="Parse next task and print details without executing."
)
@click.option(
    "--plan",
    "plan_path",
    default="docs/PLAN.md",
    show_default=True,
    help="Path to PLAN.md file.",
)
@click.option(
    "--repo",
    "repo_path",
    default=".",
    show_default=True,
    help="Repository root path.",
)
@click.option(
    "--timeout-s",
    type=float,
    default=3600.0,
    show_default=True,
    help="Max seconds to wait for agent per iteration.",
)
def ralph_run(
    mode: str,
    max_iterations: int | None,
    dry_run: bool,
    plan_path: str,
    repo_path: str,
    timeout_s: float,
) -> None:
    """Run Ralph: pick next task, implement, verify, commit.

    \b
    Examples:
      uv run jarvis ralph run --dry-run        # inspect next task
      uv run jarvis ralph run --once           # one iteration
      uv run jarvis ralph run --loop --max 5   # up to 5 iterations
    """
    settings = get_settings()
    max_failures = int(settings.ralph_max_failures)

    if mode == "once" or dry_run:
        status = _run_once(
            dry_run=dry_run,
            plan_path=plan_path,
            repo_path=repo_path,
            timeout_s=timeout_s,
            max_failures=max_failures,
        )
        if status in ("failed", "gate_fail", "halted"):
            sys.exit(1)
        return

    # --loop mode
    max_iter = max_iterations if max_iterations is not None else int(settings.ralph_max_iterations)
    iteration = 0
    failures = 0

    while iteration < max_iter:
        click.echo(f"\n=== Ralph iteration {iteration + 1}/{max_iter} ===")
        status = _run_once(
            dry_run=False,
            plan_path=plan_path,
            repo_path=repo_path,
            timeout_s=timeout_s,
            max_failures=max_failures,
        )
        iteration += 1

        if status == "no_tasks":
            click.echo("No more pending Ralph tasks.")
            break
        if status == "halted":
            click.echo("Ralph halted by safety limit.")
            sys.exit(1)
        if status in ("failed", "gate_fail"):
            failures += 1
            if failures >= max_failures:
                click.echo(
                    f"Ralph stopping: {failures} consecutive failures"
                    f" >= RALPH_MAX_FAILURES={max_failures}."
                )
                sys.exit(1)
        else:
            failures = 0

    click.echo(f"\nRalph loop complete: {iteration} iteration(s), {failures} failure(s).")
    progress = read_ralph_progress(repo_path)
    click.echo(
        f"Progress: iteration={progress.get('iteration')} failures={progress.get('failures')}"
    )


@ralph_group.command("status")
@click.option(
    "--repo",
    "repo_path",
    default=".",
    show_default=True,
    help="Repository root path.",
)
@click.option("--json", "json_output", is_flag=True, help="Print JSON.")
def ralph_status(repo_path: str, json_output: bool) -> None:
    """Show Ralph progress and next pending task."""
    from jarvis.selfupdate.ralph_plan import next_ralph_task as get_next

    progress = read_ralph_progress(repo_path)
    try:
        next_task = get_next()
    except RuntimeError as exc:
        next_task = None
        if json_output:
            click.echo(json.dumps({"error": str(exc)}, indent=2))
            return
        click.echo(f"warning: {exc}", err=True)

    if json_output:
        payload = {
            "progress": progress,
            "next_task": next_task,
        }
        click.echo(json.dumps(payload, indent=2))
        return

    click.echo(f"iteration:  {progress.get('iteration', 0)}")
    click.echo(f"failures:   {progress.get('failures', 0)}")
    click.echo(f"last_task:  {progress.get('last_task', 'none')}")
    click.echo(f"last_run_at:{progress.get('last_run_at', 'never')}")
    if next_task:
        click.echo(f"next_task:  {next_task['text']}")
        if next_task.get("accept"):
            click.echo(f"accept:     {next_task['accept']}")
    else:
        click.echo("next_task:  (none — all done or section missing)")
