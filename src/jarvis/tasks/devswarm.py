"""DevSwarm task orchestration and deterministic monitoring."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import time
from pathlib import Path

import httpx

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_devswarm_task,
    ensure_channel,
    ensure_open_thread,
    ensure_user,
    get_devswarm_task,
    insert_message,
    list_active_devswarm_tasks,
    list_devswarm_tasks,
    now_iso,
    update_devswarm_task,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.tasks import get_task_runner
from jarvis.tasks.github import github_pr_swarm_status_comment

logger = logging.getLogger(__name__)

SWARM_STATUSES = {
    "queued",
    "running",
    "needs_attention",
    "ready_for_review",
    "done",
    "failed",
}
_OPENCODE_PROMPT_FILE_SUPPORTED: bool | None = None


def _enqueue_system_notification(event_type: str, payload: dict[str, object]) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
            "VALUES(?,?,?,?)",
            ("system", event_type, json.dumps(payload), now_iso()),
        )


def _normalize_task_row(row: dict[str, object]) -> dict[str, object]:
    checks = _safe_json_loads(str(row.get("checks_json") or "{}"))
    return {
        "id": str(row.get("id") or ""),
        "task_type": str(row.get("task_type") or ""),
        "description": str(row.get("description") or ""),
        "status": str(row.get("status") or ""),
        "repo_path": str(row.get("repo_path") or ""),
        "worktree_path": str(row.get("worktree_path") or ""),
        "branch": str(row.get("branch") or ""),
        "base_branch": str(row.get("base_branch") or ""),
        "model": str(row.get("model") or ""),
        "provider": str(row.get("provider") or ""),
        "tmux_session": str(row.get("tmux_session") or ""),
        "pr_number": row.get("pr_number"),
        "pr_url": str(row.get("pr_url") or ""),
        "attempt": int(row.get("attempt") or 0),
        "max_attempts": int(row.get("max_attempts") or 0),
        "last_error": str(row.get("last_error") or ""),
        "checks": checks,
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "completed_at": str(row.get("completed_at") or ""),
    }


def _emit(
    *,
    trace_id: str,
    event_type: str,
    payload: dict[str, object],
    thread_id: str | None = None,
) -> None:
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=thread_id,
                event_type=event_type,
                component="devswarm",
                actor_type="system",
                actor_id="devswarm",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout_s: int = 30,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        capture_output=True,
        text=True,
        timeout=max(1, timeout_s),
    )


def _normalize_repo_path(repo_path: str) -> Path:
    path = Path(repo_path).expanduser().resolve()
    if not path.exists() or not (path / ".git").exists():
        raise RuntimeError(f"repo_path is not a git repo: {path}")
    return path


def _parse_github_repo(remote_url: str) -> tuple[str, str] | None:
    value = remote_url.strip()
    if value.endswith(".git"):
        value = value[:-4]
    if value.startswith("git@github.com:"):
        tail = value.split(":", 1)[1]
    elif value.startswith("https://github.com/"):
        tail = value.split("https://github.com/", 1)[1]
    else:
        return None
    if "/" not in tail:
        return None
    owner, repo = tail.split("/", 1)
    owner = owner.strip()
    repo = repo.strip()
    if not owner or not repo:
        return None
    return owner, repo


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Jarvis-DevSwarm/1.0",
    }


def _safe_json_loads(raw: str) -> dict[str, object]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _default_worktree_root(repo: Path) -> Path:
    settings = get_settings()
    raw = settings.devswarm_worktrees_root.strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (repo / ".jarvis" / "worktrees").resolve()


def _default_logs_root(repo: Path) -> Path:
    settings = get_settings()
    raw = settings.devswarm_logs_root.strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (repo / ".jarvis" / "logs").resolve()


def _default_prompts_root(repo: Path) -> Path:
    settings = get_settings()
    raw = settings.devswarm_prompts_root.strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (repo / ".jarvis" / "prompts").resolve()


def _render_prompt(task_type: str, description: str, task_id: str, base_branch: str) -> str:
    return (
        f"# DevSwarm Task {task_id}\n\n"
        f"Type: {task_type}\n"
        f"Base branch: {base_branch}\n\n"
        "## Objective\n"
        f"{description.strip()}\n\n"
        "## Required constraints\n"
        "- Work on the current git branch only.\n"
        "- Keep PR base branch as dev.\n"
        "- Run focused tests and linters for touched code.\n"
        "- Commit coherent changes and open a PR when ready.\n"
    )


def _normalize_opencode_model(model: str) -> str:
    raw = model.strip()
    if not raw:
        raise RuntimeError("model is required for DevSwarm worker launch")
    if "/" in raw:
        return raw
    return f"lmstudio/{raw}"


def _opencode_command(prompt_file: Path, model: str, task_id: str) -> str:
    settings = get_settings()
    normalized_model = _normalize_opencode_model(model)
    template = settings.devswarm_opencode_command_template.strip()
    if template:
        try:
            return template.format(
                model=normalized_model,
                prompt_file=str(prompt_file),
                task_id=task_id,
            )
        except (KeyError, ValueError) as exc:
            raise RuntimeError(f"invalid DEVSWARM_OPENCODE_COMMAND_TEMPLATE: {exc}") from exc
    return _default_opencode_command(prompt_file=prompt_file, model=normalized_model)


def _opencode_supports_prompt_file() -> bool:
    global _OPENCODE_PROMPT_FILE_SUPPORTED
    if _OPENCODE_PROMPT_FILE_SUPPORTED is not None:
        return _OPENCODE_PROMPT_FILE_SUPPORTED
    proc = _run(["opencode", "run", "--help"], timeout_s=5)
    help_text = f"{proc.stdout}\n{proc.stderr}"
    _OPENCODE_PROMPT_FILE_SUPPORTED = "--prompt-file" in help_text
    return _OPENCODE_PROMPT_FILE_SUPPORTED


def _default_opencode_command(*, prompt_file: Path, model: str) -> str:
    model_q = shlex.quote(model)
    prompt_q = shlex.quote(str(prompt_file))
    if _opencode_supports_prompt_file():
        return f"opencode run --model {model_q} --prompt-file {prompt_q}"
    return (
        f"opencode run -m {model_q} -f {prompt_q} -- "
        f"{shlex.quote('Complete the attached task file.')}"
    )


def _resolve_opencode_config_path(repo_path: Path) -> Path:
    raw = os.getenv("OPENCODE_CONFIG_PATH", "").strip()
    if not raw:
        return (repo_path / "opencode.json").resolve()
    configured = Path(raw).expanduser()
    if configured.is_absolute():
        return configured.resolve()
    return (repo_path / configured).resolve()


def _validate_opencode_preflight(repo_path: Path) -> None:
    proc = _run(["opencode", "run", "--help"], timeout_s=5)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:400]
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"opencode is unavailable{suffix}")

    config_path = _resolve_opencode_config_path(repo_path)
    if not config_path.exists():
        return

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"unable to read OpenCode config at {config_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid OpenCode config at {config_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError(f"invalid OpenCode config at {config_path}: expected object")
    # OpenCode v1.2+ expects a "provider" object schema. The older
    # "providers/models/defaultModel" shape causes runtime validation errors.
    if (
        "provider" not in payload
        and ("providers" in payload or "models" in payload or "defaultModel" in payload)
    ):
        raise RuntimeError(
            f"invalid OpenCode config at {config_path}: legacy schema detected "
            "(providers/models/defaultModel). Rebuild config via ./start-dev.sh."
        )


def _scrubbed_shell_command(base_command: str) -> str:
    settings = get_settings()
    keys = [
        item.strip()
        for item in settings.devswarm_blocked_env_keys.split(",")
        if item.strip()
    ]
    unset_cmd = " ".join(f"-u {shlex.quote(item)}" for item in keys)
    if unset_cmd:
        return f"env {unset_cmd} {base_command}"
    return base_command


def _ensure_tmux_available() -> None:
    proc = _run(["tmux", "-V"], timeout_s=5)
    if proc.returncode != 0:
        raise RuntimeError("tmux is required for devswarm workers")


def _tail_file(path: Path, *, lines: int = 40) -> str:
    if lines <= 0 or not path.exists():
        return ""
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    return "\n".join(raw_lines[-lines:]).strip()


def _wait_for_tmux_session(session: str, *, attempts: int = 8, delay_seconds: float = 0.25) -> bool:
    for _ in range(max(1, attempts)):
        if _tmux_alive(session):
            return True
        time.sleep(max(0.01, delay_seconds))
    return False


def _notify_whatsapp(
    task: dict[str, object],
    checks: dict[str, object],
    *,
    status: str,
) -> dict[str, object]:
    settings = get_settings()
    if int(settings.devswarm_whatsapp_notify_enabled) != 1:
        return {"ok": True, "skipped": "disabled"}

    targets = [
        item.strip()
        for item in (
            settings.devswarm_whatsapp_targets or settings.human_escalation_targets
        ).split(",")
        if item.strip()
    ]
    if not targets:
        return {"ok": True, "skipped": "no_targets"}

    pr_url = str(task.get("pr_url") or "")
    pr_number = task.get("pr_number")
    task_id = str(task.get("id") or "")
    gates = checks.get("gates")
    gate_summary = ""
    if isinstance(gates, dict):
        failed = [name for name, ok in gates.items() if not bool(ok)]
        if failed:
            gate_summary = f"\nFailing gates: {', '.join(failed)}"
    text = (
        f"Jarvis DevSwarm: {status.upper()}\n"
        f"task_id: {task_id}\n"
        f"PR: #{pr_number} {pr_url}".strip()
    ) + gate_summary

    sent = 0
    with get_conn() as conn:
        for target in targets:
            user_id = ensure_user(conn, target)
            channel_id = ensure_channel(conn, user_id, "whatsapp")
            thread_id = ensure_open_thread(conn, user_id, channel_id)
            message_id = insert_message(conn, thread_id, "assistant", text)
            ok = get_task_runner().send_task(
                "jarvis.tasks.channel.send_channel_message",
                kwargs={
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "channel_type": "whatsapp",
                },
                queue="tools_io",
            )
            if ok:
                sent += 1
    return {"ok": True, "sent": sent}


def _git_remote(repo_path: Path) -> str:
    proc = _run(["git", "-C", str(repo_path), "remote", "get-url", "origin"], timeout_s=10)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _fetch_pr_for_branch(
    *,
    owner: str,
    repo: str,
    branch: str,
    token: str,
    api_base: str,
) -> dict[str, object] | None:
    with httpx.Client(timeout=10.0, headers=_github_headers(token)) as client:
        resp = client.get(
            f"{api_base}/repos/{owner}/{repo}/pulls",
            params={"head": f"{owner}:{branch}", "state": "open", "per_page": 5},
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list) or not payload:
            return None
        for item in payload:
            if not isinstance(item, dict):
                continue
            number = item.get("number")
            if not isinstance(number, int):
                continue
            detail = client.get(f"{api_base}/repos/{owner}/{repo}/pulls/{number}")
            detail.raise_for_status()
            body = detail.json()
            if isinstance(body, dict):
                return body
    return None


def _ci_state(
    *,
    owner: str,
    repo: str,
    sha: str,
    token: str,
    api_base: str,
) -> str:
    with httpx.Client(timeout=10.0, headers=_github_headers(token)) as client:
        checks_resp = client.get(
            f"{api_base}/repos/{owner}/{repo}/commits/{sha}/check-runs",
            params={"per_page": 100},
        )
        checks_resp.raise_for_status()
        checks_payload = checks_resp.json()
        check_runs = checks_payload.get("check_runs") if isinstance(checks_payload, dict) else []
        if not isinstance(check_runs, list):
            check_runs = []

        status_resp = client.get(f"{api_base}/repos/{owner}/{repo}/commits/{sha}/status")
        status_resp.raise_for_status()
        status_payload = status_resp.json()
        combined_state = str(status_payload.get("state") or "").strip().lower()

    saw_pending = combined_state in {"pending"}
    saw_failure = combined_state in {"error", "failure"}
    saw_success = combined_state in {"success"}

    for run in check_runs:
        if not isinstance(run, dict):
            continue
        status = str(run.get("status") or "").strip().lower()
        conclusion = str(run.get("conclusion") or "").strip().lower()
        if status != "completed":
            saw_pending = True
            continue
        if conclusion in {"failure", "timed_out", "cancelled", "action_required", "stale"}:
            saw_failure = True
        elif conclusion in {"success", "neutral", "skipped"}:
            saw_success = True

    if saw_failure:
        return "failure"
    if saw_pending:
        return "pending"
    if saw_success:
        return "success"
    return "unknown"


def _tmux_alive(session: str) -> bool:
    proc = _run(["tmux", "has-session", "-t", session], timeout_s=5)
    return proc.returncode == 0


def _branch_exists(repo_path: Path, branch: str) -> bool:
    proc = _run(["git", "-C", str(repo_path), "show-ref", "--verify", f"refs/heads/{branch}"])
    return proc.returncode == 0


def _status_from_checks(checks: dict[str, object]) -> str:
    gates = checks.get("gates")
    if not isinstance(gates, dict):
        return "needs_attention"
    required = [
        bool(gates.get("pr_exists")),
        bool(gates.get("pr_base_dev")),
        bool(gates.get("ci_green")),
        bool(gates.get("branch_up_to_date_with_dev")),
    ]
    if all(required):
        return "ready_for_review"

    # Deterministic attention criteria.
    if not bool(gates.get("tmux_alive")):
        return "needs_attention"
    if bool(gates.get("pr_exists")) and not bool(gates.get("pr_base_dev")):
        return "needs_attention"
    if checks.get("ci_state") == "failure":
        return "needs_attention"
    if bool(checks.get("merge_conflict")):
        return "needs_attention"
    return "running"


def _evaluate_one(task: dict[str, object]) -> dict[str, object]:
    settings = get_settings()
    repo_path = Path(str(task.get("repo_path") or "")).expanduser().resolve()
    branch = str(task.get("branch") or "")
    session = str(task.get("tmux_session") or "")
    checks: dict[str, object] = {
        "task_id": str(task.get("id") or ""),
        "repo_path": str(repo_path),
        "branch": branch,
        "tmux_session": session,
    }

    tmux_ok = _tmux_alive(session)
    branch_ok = _branch_exists(repo_path, branch)
    checks["tmux_alive"] = tmux_ok
    checks["branch_exists"] = branch_ok

    remote_url = _git_remote(repo_path)
    repo_pair = _parse_github_repo(remote_url)
    checks["github_remote"] = remote_url

    pr_number: int | None = None
    pr_url = ""
    pr_base = ""
    mergeable_state = ""
    ci_state = "unknown"
    merge_conflict = False
    up_to_date = False

    token = settings.github_token.strip()
    if repo_pair is not None and token:
        owner, repo = repo_pair
        api_base = settings.github_api_base_url.rstrip("/")
        try:
            pr = _fetch_pr_for_branch(
                owner=owner,
                repo=repo,
                branch=branch,
                token=token,
                api_base=api_base,
            )
            if pr is not None:
                pr_number_raw = pr.get("number")
                pr_number = int(pr_number_raw) if isinstance(pr_number_raw, int) else None
                pr_url = str(pr.get("html_url") or "")
                base = pr.get("base")
                if isinstance(base, dict):
                    pr_base = str(base.get("ref") or "")
                head = pr.get("head")
                sha = ""
                if isinstance(head, dict):
                    sha = str(head.get("sha") or "")
                mergeable_state = str(pr.get("mergeable_state") or "").strip().lower()
                merge_conflict = mergeable_state == "dirty"
                up_to_date = mergeable_state not in {"behind", "dirty"}
                if sha:
                    ci_state = _ci_state(
                        owner=owner,
                        repo=repo,
                        sha=sha,
                        token=token,
                        api_base=api_base,
                    )
        except Exception as exc:  # noqa: BLE001
            checks["github_error"] = str(exc)

    checks["pr_number"] = pr_number
    checks["pr_url"] = pr_url
    checks["pr_base"] = pr_base
    checks["mergeable_state"] = mergeable_state
    checks["merge_conflict"] = merge_conflict
    checks["ci_state"] = ci_state

    gates = {
        "tmux_alive": tmux_ok,
        "branch_exists": branch_ok,
        "pr_exists": pr_number is not None,
        "pr_base_dev": pr_base == "dev" if pr_number is not None else False,
        "ci_green": ci_state == "success",
        "branch_up_to_date_with_dev": up_to_date,
    }
    checks["gates"] = gates
    checks["next_status"] = _status_from_checks(checks)
    return checks


def _update_comment_if_possible(
    task: dict[str, object],
    checks: dict[str, object],
) -> dict[str, object]:
    remote_url = str(checks.get("github_remote") or "")
    repo_pair = _parse_github_repo(remote_url)
    pr_number = checks.get("pr_number")
    if repo_pair is None or not isinstance(pr_number, int):
        return {"ok": True, "skipped": "missing_pr_context"}
    owner, repo = repo_pair
    return github_pr_swarm_status_comment(
        owner=owner,
        repo=repo,
        pull_number=int(pr_number),
        task_id=str(task.get("id") or ""),
        status=str(checks.get("next_status") or "running"),
        checks=checks,
    )


def refresh_task_status(task_id: str, *, trace_id: str | None = None) -> dict[str, object]:
    current_trace_id = trace_id or new_id("trc")
    with get_conn() as conn:
        task = get_devswarm_task(conn, task_id)
    if task is None:
        return {"ok": False, "error": "task_not_found", "task_id": task_id}

    checks = _evaluate_one(task)
    next_status = str(checks.get("next_status") or "running")
    if next_status not in SWARM_STATUSES:
        next_status = "needs_attention"
    prev_status = str(task.get("status") or "")
    pr_number = checks.get("pr_number")
    pr_number_int = int(pr_number) if isinstance(pr_number, int) else None
    pr_url = str(checks.get("pr_url") or "")

    with get_conn() as conn:
        update_devswarm_task(
            conn,
            task_id,
            status=next_status,
            pr_number=pr_number_int,
            pr_url=pr_url,
            checks_json=json.dumps(checks, sort_keys=True),
            completed_at=now_iso() if next_status in {"done", "failed"} else None,
        )
        refreshed = get_devswarm_task(conn, task_id)
    if isinstance(refreshed, dict):
        _enqueue_system_notification(
            "system.swarm.task.updated",
            {
                "task_id": task_id,
                "status": next_status,
                "checks": checks,
                "updated_at": str(refreshed.get("updated_at") or now_iso()),
            },
        )

    comment_result = _update_comment_if_possible(task, checks)
    response: dict[str, object] = {
        "ok": True,
        "task_id": task_id,
        "previous_status": prev_status,
        "next_status": next_status,
        "checks": checks,
        "comment": comment_result,
    }

    if prev_status != next_status and next_status in {"needs_attention", "ready_for_review"}:
        notif = _notify_whatsapp(task, checks, status=next_status)
        response["notification"] = notif
        _emit(
            trace_id=current_trace_id,
            event_type="devswarm.task.transition",
            payload={
                "task_id": task_id,
                "from": prev_status,
                "to": next_status,
                "checks": checks,
                "notification": notif,
            },
        )
    return response


def spawn_worker(task_id: str) -> dict[str, object]:
    settings = get_settings()
    with get_conn() as conn:
        task = get_devswarm_task(conn, task_id)
        if task is None:
            return {"ok": False, "error": "task_not_found", "task_id": task_id}

    trace_id = new_id("trc")
    repo_path = Path(str(task.get("repo_path") or "")).expanduser().resolve()
    worktree_path = Path(str(task.get("worktree_path") or "")).expanduser().resolve()
    session = str(task.get("tmux_session") or "")
    branch = str(task.get("branch") or "")
    model = str(task.get("model") or settings.lmstudio_model)
    max_attempts = int(task.get("max_attempts") or 3)
    attempt = int(task.get("attempt") or 0)

    if attempt >= max_attempts:
        with get_conn() as conn:
            update_devswarm_task(
                conn,
                task_id,
                status="failed",
                last_error="max_attempts_exhausted",
                completed_at=now_iso(),
            )
        return {"ok": False, "error": "max_attempts_exhausted", "task_id": task_id}

    try:
        _validate_opencode_preflight(repo_path)
        _ensure_tmux_available()
        prompts_root = _default_prompts_root(repo_path)
        logs_root = _default_logs_root(repo_path)
        prompts_root.mkdir(parents=True, exist_ok=True)
        logs_root.mkdir(parents=True, exist_ok=True)
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        prompt_file = prompts_root / f"{task_id}.md"
        if not prompt_file.exists():
            prompt_file.write_text(
                _render_prompt(
                    str(task.get("task_type") or "feature"),
                    str(task.get("description") or ""),
                    task_id,
                    str(task.get("base_branch") or "dev"),
                ),
                encoding="utf-8",
            )

        log_file = logs_root / f"{task_id}.log"
        if worktree_path.exists():
            _run(
                ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(worktree_path)],
                timeout_s=20,
            )
        add = _run(
            [
                "git",
                "-C",
                str(repo_path),
                "worktree",
                "add",
                "-B",
                branch,
                str(worktree_path),
                f"origin/{str(task.get('base_branch') or 'dev')}",
            ],
            timeout_s=60,
        )
        if add.returncode != 0:
            raise RuntimeError(add.stderr.strip() or "git worktree add failed")

        _run(["tmux", "kill-session", "-t", session], timeout_s=5)

        opencode_cmd = _opencode_command(prompt_file, model, task_id)
        cmd = _scrubbed_shell_command(opencode_cmd)
        shell_cmd = f"set -euo pipefail; {cmd} >> {shlex.quote(str(log_file))} 2>&1"
        start = _run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                session,
                "-c",
                str(worktree_path),
                f"bash -lc {shlex.quote(shell_cmd)}",
            ],
            timeout_s=15,
        )
        if start.returncode != 0:
            raise RuntimeError(start.stderr.strip() or "tmux new-session failed")

        with get_conn() as conn:
            update_devswarm_task(
                conn,
                task_id,
                status="running",
                attempt=attempt + 1,
                last_error="",
            )

        if not _wait_for_tmux_session(session, attempts=20, delay_seconds=0.3):
            log_excerpt = _tail_file(log_file, lines=40)
            msg = "worker exited immediately after launch"
            if log_excerpt:
                msg = f"{msg}; log_tail={log_excerpt[:800]}"
            raise RuntimeError(msg)
        time.sleep(1.0)
        if not _tmux_alive(session):
            log_excerpt = _tail_file(log_file, lines=40)
            msg = "worker exited shortly after launch"
            if log_excerpt:
                msg = f"{msg}; log_tail={log_excerpt[:800]}"
            raise RuntimeError(msg)

        _emit(
            trace_id=trace_id,
            event_type="devswarm.worker.spawned",
            payload={
                "task_id": task_id,
                "session": session,
                "branch": branch,
                "worktree_path": str(worktree_path),
                "log_path": str(log_file),
            },
        )
        return {
            "ok": True,
            "task_id": task_id,
            "status": "running",
            "session": session,
            "worktree_path": str(worktree_path),
            "log_path": str(log_file),
        }
    except Exception as exc:  # noqa: BLE001
        with get_conn() as conn:
            update_devswarm_task(
                conn,
                task_id,
                status="needs_attention",
                last_error=str(exc),
                completed_at=None,
            )
        _emit(
            trace_id=trace_id,
            event_type="devswarm.worker.spawn_failed",
            payload={"task_id": task_id, "error": str(exc)},
        )
        return {"ok": False, "task_id": task_id, "error": str(exc)}


def create_task(
    *,
    description: str,
    repo_path: str,
    model: str | None = None,
    task_type: str = "feature",
) -> dict[str, object]:
    settings = get_settings()
    normalized_type = task_type.strip().lower()
    if normalized_type not in {"feature", "bugfix", "refactor"}:
        return {"ok": False, "error": "invalid_task_type"}
    desc = description.strip()
    if not desc:
        return {"ok": False, "error": "task description is required"}

    repo = _normalize_repo_path(repo_path)
    try:
        _validate_opencode_preflight(repo)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    task_id = new_id("sch")
    branch = f"swarm/{task_id}"
    worktree_root = _default_worktree_root(repo)
    worktree_path = (worktree_root / task_id).resolve()
    session = f"swarm-{task_id}"
    selected_model = (model or settings.lmstudio_model).strip() or "local-model"

    with get_conn() as conn:
        create_devswarm_task(
            conn,
            task_id=task_id,
            task_type=normalized_type,
            description=desc,
            repo_path=str(repo),
            worktree_path=str(worktree_path),
            branch=branch,
            base_branch="dev",
            tmux_session=session,
            status="queued",
            max_attempts=max(1, int(settings.devswarm_max_attempts)),
            model=selected_model,
            provider="lmstudio",
        )

    trace_id = new_id("trc")
    _emit(
        trace_id=trace_id,
        event_type="devswarm.task.created",
        payload={
            "task_id": task_id,
            "task_type": normalized_type,
            "repo_path": str(repo),
            "branch": branch,
            "base_branch": "dev",
            "model": selected_model,
        },
    )
    _enqueue_system_notification(
        "system.swarm.task.created",
        {
            "task_id": task_id,
            "status": "queued",
            "task_type": normalized_type,
            "branch": branch,
            "created_at": now_iso(),
        },
    )

    spawn_result = spawn_worker(task_id)
    refresh_result = refresh_task_status(task_id, trace_id=trace_id)
    detail = get_task_detail(task_id)
    resolved_status = spawn_result.get("status", "queued")
    if isinstance(detail.get("item"), dict):
        resolved_status = str(detail["item"].get("status") or resolved_status)
    elif bool(refresh_result.get("ok")):
        resolved_status = str(refresh_result.get("next_status") or resolved_status)
    return {
        "ok": bool(spawn_result.get("ok")),
        "task_id": task_id,
        "status": resolved_status,
        "repo_path": str(repo),
        "worktree_path": str(worktree_path),
        "branch": branch,
        "tmux_session": session,
        "model": selected_model,
        "spawn": spawn_result,
        "refresh": refresh_result,
    }


def send_tmux(task_id: str, message: str) -> dict[str, object]:
    with get_conn() as conn:
        task = get_devswarm_task(conn, task_id)
    if task is None:
        return {"ok": False, "error": "task_not_found", "task_id": task_id}
    session = str(task.get("tmux_session") or "")
    text = message.strip()
    if not text:
        return {"ok": False, "error": "message is required", "task_id": task_id}

    proc = _run(["tmux", "send-keys", "-t", session, text, "C-m"], timeout_s=5)
    if proc.returncode != 0:
        refresh = refresh_task_status(task_id)
        return {
            "ok": False,
            "task_id": task_id,
            "error": proc.stderr.strip() or "tmux send-keys failed",
            "refresh": refresh,
        }
    _emit(
        trace_id=new_id("trc"),
        event_type="devswarm.worker.nudge",
        payload={"task_id": task_id, "session": session, "message": text[:500]},
    )
    _enqueue_system_notification(
        "system.swarm.task.nudged",
        {
            "task_id": task_id,
            "status": str(task.get("status") or ""),
            "message": text[:200],
            "updated_at": now_iso(),
        },
    )
    return {"ok": True, "task_id": task_id, "session": session}


def check_tasks(*, limit: int = 100) -> dict[str, object]:
    trace_id = new_id("trc")
    updates: list[dict[str, object]] = []
    with get_conn() as conn:
        tasks = list_active_devswarm_tasks(conn, limit=limit)

    for task in tasks:
        task_id = str(task.get("id") or "")
        updates.append(refresh_task_status(task_id, trace_id=trace_id))

    _emit(
        trace_id=trace_id,
        event_type="devswarm.monitor.tick",
        payload={"task_count": len(tasks), "updated": len(updates)},
    )
    _enqueue_system_notification(
        "system.swarm.monitor.tick",
        {
            "checked": len(tasks),
            "updated": len(updates),
            "created_at": now_iso(),
        },
    )
    return {"ok": True, "checked": len(tasks), "updates": updates}


def monitor_tasks() -> dict[str, object]:
    """Periodic task wrapper for deterministic DevSwarm monitoring."""
    return check_tasks(limit=200)


def cleanup(*, task_id: str | None = None, remove_worktrees: bool = True) -> dict[str, object]:
    removed: list[str] = []
    failures: list[dict[str, str]] = []

    with get_conn() as conn:
        tasks = (
            [get_devswarm_task(conn, task_id)]
            if task_id
            else list_devswarm_tasks(conn, limit=500)
        )
    task_items = [task for task in tasks if isinstance(task, dict)]

    for task in task_items:
        current_id = str(task.get("id") or "")
        session = str(task.get("tmux_session") or "")
        worktree_path = Path(str(task.get("worktree_path") or "")).expanduser().resolve()
        repo_path = Path(str(task.get("repo_path") or "")).expanduser().resolve()

        _run(["tmux", "kill-session", "-t", session], timeout_s=5)
        if remove_worktrees and worktree_path.exists():
            rm = _run(
                ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(worktree_path)],
                timeout_s=30,
            )
            if rm.returncode != 0:
                failures.append(
                    {
                        "task_id": current_id,
                        "error": rm.stderr.strip() or "worktree_remove_failed",
                    }
                )
                continue

        with get_conn() as conn:
            update_devswarm_task(
                conn,
                current_id,
                status="done",
                completed_at=now_iso(),
            )
            refreshed = get_devswarm_task(conn, current_id)
        if isinstance(refreshed, dict):
            _enqueue_system_notification(
                "system.swarm.task.cleaned",
                {
                    "task_id": current_id,
                    "status": "done",
                    "remove_worktrees": bool(remove_worktrees),
                    "updated_at": str(refreshed.get("updated_at") or now_iso()),
                },
            )
        removed.append(current_id)

    return {"ok": len(failures) == 0, "removed": removed, "failures": failures}


def status(*, limit: int = 50, status: str | None = None) -> dict[str, object]:
    with get_conn() as conn:
        items = list_devswarm_tasks(conn, limit=limit, status=status)
    normalized = [_normalize_task_row(row) for row in items]
    return {"ok": True, "count": len(normalized), "items": normalized}


def get_task_detail(task_id: str) -> dict[str, object]:
    with get_conn() as conn:
        row = get_devswarm_task(conn, task_id)
    if row is None:
        return {"ok": False, "error": "task_not_found", "task_id": task_id}
    return {"ok": True, "item": _normalize_task_row(row)}
