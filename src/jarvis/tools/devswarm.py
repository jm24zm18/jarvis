"""DevSwarm tool handlers exposed to the agent runtime."""

from __future__ import annotations

from jarvis.tasks import devswarm as devswarm_tasks


async def spawn_worker(args: dict[str, object]) -> dict[str, object]:
    task_id = str(args.get("task_id", "")).strip()
    if task_id:
        return devswarm_tasks.spawn_worker(task_id)
    description = str(args.get("description", "")).strip()
    repo_path = str(args.get("repo_path", "")).strip()
    model = str(args.get("model", "")).strip() or None
    task_type = str(args.get("task_type", "feature")).strip().lower() or "feature"
    return devswarm_tasks.create_task(
        description=description,
        repo_path=repo_path,
        model=model,
        task_type=task_type,
    )


async def send_tmux(args: dict[str, object]) -> dict[str, object]:
    task_id = str(args.get("task_id", "")).strip()
    message = str(args.get("message", "")).strip()
    return devswarm_tasks.send_tmux(task_id, message)


async def check_tasks(args: dict[str, object]) -> dict[str, object]:
    raw_limit = args.get("limit", 100)
    try:
        limit = int(raw_limit) if isinstance(raw_limit, int | float | str) else 100
    except (TypeError, ValueError):
        limit = 100
    return devswarm_tasks.check_tasks(limit=limit)


async def cleanup(args: dict[str, object]) -> dict[str, object]:
    task_id = str(args.get("task_id", "")).strip() or None
    keep_worktrees = bool(args.get("keep_worktrees"))
    return devswarm_tasks.cleanup(task_id=task_id, remove_worktrees=not keep_worktrees)
