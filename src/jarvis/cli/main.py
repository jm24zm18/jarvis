"""Click CLI group: setup, doctor, ask, and chat commands."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from jarvis.cli.chat import default_cli_user, format_reply, resolve_thread, send_and_wait
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.memory.skills import SkillsService


@click.group()
def cli() -> None:
    """Jarvis Agent Framework CLI."""


@cli.command()
def setup() -> None:
    """Launch the interactive TUI setup wizard."""
    from jarvis.cli.setup_wizard import run_setup_wizard

    run_setup_wizard()


@cli.command()
@click.option("--json", "json_output", is_flag=True, help="Append JSON output to the report.")
@click.option("--fix", is_flag=True, help="Try to auto-fix supported failed checks.")
def doctor(json_output: bool, fix: bool) -> None:
    """Run diagnostic checks and print a health report."""
    from jarvis.cli.doctor import run_doctor

    run_doctor(json_output=json_output, fix=fix)


@cli.command("gemini-login")
@click.option(
    "--token-path",
    type=click.Path(path_type=str),
    default=None,
    help="Override token cache path (default: GEMINI_CODE_ASSIST_TOKEN_PATH).",
)
def gemini_login(token_path: str | None) -> None:
    """Run manual Gemini OAuth login and write Code Assist token cache."""
    from jarvis.providers.google_gemini_cli import run_manual_login

    settings = get_settings()
    resolved = Path(token_path or settings.gemini_code_assist_token_path).expanduser()
    result = asyncio.run(run_manual_login(resolved))
    click.echo(f"token cache: {result['token_path']}")
    click.echo(f"cloudaicompanionProject: {result['cloudaicompanion_project']}")


@cli.command()
@click.argument("message")
@click.option("--thread-id", type=str, default=None, help="Use an existing thread ID.")
@click.option("--new-thread", is_flag=True, help="Create a new thread for this message.")
@click.option(
    "--user-id",
    type=str,
    default=default_cli_user,
    show_default="cli:<local-user>@<host>",
    help="External user ID used to group CLI threads.",
)
@click.option("--enqueue", is_flag=True, help="Queue agent step to worker and poll for response.")
@click.option("--timeout-s", type=float, default=30.0, show_default=True)
@click.option("--poll-interval-s", type=float, default=0.5, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print structured JSON response.")
def ask(
    message: str,
    thread_id: str | None,
    new_thread: bool,
    user_id: str,
    enqueue: bool,
    timeout_s: float,
    poll_interval_s: float,
    json_output: bool,
) -> None:
    """Send one message to the main agent and print the reply."""
    if timeout_s <= 0:
        raise click.ClickException("--timeout-s must be > 0")
    if poll_interval_s <= 0:
        raise click.ClickException("--poll-interval-s must be > 0")
    target_thread = resolve_thread(user_id, thread_id=thread_id, new_thread=new_thread)
    reply = send_and_wait(
        thread_id=target_thread,
        message=message,
        enqueue=enqueue,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )
    click.echo(format_reply(reply, json_output=json_output))


@cli.command()
@click.option("--thread-id", type=str, default=None, help="Use an existing thread ID.")
@click.option("--new-thread", is_flag=True, help="Create a new thread at startup.")
@click.option(
    "--user-id",
    type=str,
    default=default_cli_user,
    show_default="cli:<local-user>@<host>",
    help="External user ID used to group CLI threads.",
)
@click.option("--enqueue", is_flag=True, help="Queue agent step to worker and poll for response.")
@click.option("--timeout-s", type=float, default=30.0, show_default=True)
@click.option("--poll-interval-s", type=float, default=0.5, show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Print each assistant reply as JSON.")
def chat(
    thread_id: str | None,
    new_thread: bool,
    user_id: str,
    enqueue: bool,
    timeout_s: float,
    poll_interval_s: float,
    json_output: bool,
) -> None:
    """Interactive CLI chat loop with the main agent."""
    if timeout_s <= 0:
        raise click.ClickException("--timeout-s must be > 0")
    if poll_interval_s <= 0:
        raise click.ClickException("--poll-interval-s must be > 0")

    target_thread = resolve_thread(user_id, thread_id=thread_id, new_thread=new_thread)
    click.echo(f"thread: {target_thread} (type /quit to exit)")
    while True:
        try:
            message = click.prompt("you", prompt_suffix=" > ").strip()
        except (EOFError, KeyboardInterrupt):
            click.echo()
            break
        if not message:
            continue
        if message.lower() in {"/quit", "/exit"}:
            break
        reply = send_and_wait(
            thread_id=target_thread,
            message=message,
            enqueue=enqueue,
            timeout_s=timeout_s,
            poll_interval_s=poll_interval_s,
        )
        if json_output:
            click.echo(format_reply(reply, json_output=True))
        else:
            click.echo(f"assistant > {reply.assistant_text}")


@cli.command()
@click.argument("thread_id")
@click.option("--include-events", is_flag=True, help="Include event trace data in export.")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output file path (default: stdout).",
)
def export(thread_id: str, include_events: bool, output: str | None) -> None:
    """Export a thread's data as JSONL."""
    from jarvis.db.migrations.runner import run_migrations

    run_migrations()
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM threads WHERE id=? LIMIT 1", (thread_id,)).fetchone()
        if row is None:
            raise click.ClickException(f"thread not found: {thread_id}")

        messages = conn.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE thread_id=? ORDER BY created_at ASC",
            (thread_id,),
        ).fetchall()

        memory_items = conn.execute(
            "SELECT id, text, created_at FROM memory_items "
            "WHERE thread_id=? ORDER BY created_at ASC",
            (thread_id,),
        ).fetchall()

        events = []
        if include_events:
            events = conn.execute(
                "SELECT id, event_type, component, actor_type, actor_id, "
                "payload_redacted_json, created_at FROM events "
                "WHERE thread_id=? ORDER BY created_at ASC",
                (thread_id,),
            ).fetchall()

        summary = conn.execute(
            "SELECT short_summary, long_summary, updated_at FROM thread_summaries "
            "WHERE thread_id=?",
            (thread_id,),
        ).fetchone()

    out = open(output, "w") if output else sys.stdout
    try:
        for msg in messages:
            out.write(json.dumps({
                "type": "message",
                "id": str(msg["id"]),
                "role": str(msg["role"]),
                "content": str(msg["content"]),
                "created_at": str(msg["created_at"]),
            }) + "\n")
        for mem in memory_items:
            out.write(json.dumps({
                "type": "memory",
                "id": str(mem["id"]),
                "text": str(mem["text"]),
                "created_at": str(mem["created_at"]),
            }) + "\n")
        for evt in events:
            out.write(json.dumps({
                "type": "event",
                "id": str(evt["id"]),
                "event_type": str(evt["event_type"]),
                "component": str(evt["component"]),
                "created_at": str(evt["created_at"]),
            }) + "\n")
        if summary is not None:
            out.write(json.dumps({
                "type": "summary",
                "short_summary": str(summary["short_summary"]),
                "long_summary": str(summary["long_summary"]),
                "updated_at": str(summary["updated_at"]),
            }) + "\n")
    finally:
        if output:
            out.close()

    if output:
        click.echo(f"exported to {output}")


@cli.command("build")
@click.option("--thread-id", type=str, default=None, help="Use an existing thread ID.")
@click.option("--new-thread", is_flag=True, help="Create a new thread for this build run.")
@click.option(
    "--user-id",
    type=str,
    default=default_cli_user,
    show_default="cli:<local-user>@<host>",
    help="External user ID used to group CLI threads.",
)
@click.option(
    "--web", is_flag=True,
    help="Create thread under web_admin for web UI visibility.",
)
@click.option("--timeout-s", type=float, default=300.0, show_default=True)
@click.option(
    "--poll-interval-s", type=float, default=2.0, show_default=True,
    help="Seconds between polling for agent reply.",
)
def build(
    thread_id: str | None,
    new_thread: bool,
    user_id: str,
    web: bool,
    timeout_s: float,
    poll_interval_s: float,
) -> None:
    """Trigger Jarvis to build, test, and fix its own repo.

    Requires a running worker (make worker) since the build delegates to
    the coder agent asynchronously.
    """
    from jarvis.cli.build import run_build

    run_build(
        thread_id=thread_id,
        new_thread=new_thread,
        user_id=user_id,
        web=web,
        enqueue=True,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


@cli.command("test-gates")
@click.option("--fail-fast", is_flag=True, help="Stop on first failure.")
@click.option("--json", "json_output", is_flag=True, help="Print JSON summary.")
def test_gates(fail_fast: bool, json_output: bool) -> None:
    """Run all pre-commit quality gates (lint, typecheck, tests, coverage)."""
    from jarvis.cli.test_gates import run_test_gates

    run_test_gates(fail_fast=fail_fast, json_output=json_output)


@cli.group("skill")
def skill_group() -> None:
    """Managed skill package commands."""


@skill_group.command("install")
@click.argument("path", type=click.Path(exists=True, path_type=str))
@click.option("--scope", default="global", show_default=True)
@click.option("--actor-id", default="cli", show_default=True)
def skill_install(path: str, scope: str, actor_id: str) -> None:
    """Install a skill package from a local directory."""
    svc = SkillsService()
    with get_conn() as conn:
        result = svc.install_package(
            conn,
            package_path=path,
            scope=scope,
            actor_id=actor_id,
            install_source="local",
        )
    click.echo(f"installed: {result['slug']} v{result['version']}")
    warnings = result.get("warnings", [])
    if isinstance(warnings, list):
        for warning in warnings:
            click.echo(f"warning: {warning}")


@skill_group.command("list")
@click.option("--scope", default="global", show_default=True)
@click.option("--limit", default=50, show_default=True)
def skill_list(scope: str, limit: int) -> None:
    """List installed skills."""
    svc = SkillsService()
    with get_conn() as conn:
        items = svc.list_skills(conn, scope=scope, limit=limit)
    if not items:
        click.echo("no skills")
        return
    for item in items:
        click.echo(
            f"{item['slug']} v{item['version']} scope={item['scope']} "
            f"pinned={item['pinned']}"
        )


@skill_group.command("info")
@click.argument("slug")
@click.option("--scope", default="global", show_default=True)
def skill_info(slug: str, scope: str) -> None:
    """Show details for one skill."""
    svc = SkillsService()
    with get_conn() as conn:
        item = svc.get(conn, slug=slug, scope=scope)
        history = svc.get_install_history(conn, slug=slug)
    if item is None:
        raise click.ClickException(f"skill not found: {slug}")
    click.echo(f"slug: {item['slug']}")
    click.echo(f"title: {item['title']}")
    click.echo(f"scope: {item['scope']}")
    click.echo(f"version: {item['version']}")
    click.echo(f"source: {item['source']}")
    click.echo("install history:")
    if not history:
        click.echo("  none")
    else:
        for event in history:
            click.echo(
                f"  {event['created_at']} action={event['action']} "
                f"from={event['from_version']} to={event['to_version']} source={event['source']}"
            )


@cli.group("maintenance")
def maintenance_group() -> None:
    """Local maintenance loop controls."""


def _maintenance_status_payload() -> dict[str, object]:
    from jarvis.tasks import is_periodic_scheduler_configured
    from jarvis.tasks.maintenance import _commands_from_settings

    settings = get_settings()
    commands = _commands_from_settings(settings.maintenance_commands)

    with get_conn() as conn:
        open_count_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM bug_reports "
            "WHERE title LIKE 'Local maintenance check failed:%' "
            "AND status IN ('open','in_progress')"
        ).fetchone()
        heartbeat_row = conn.execute(
            "SELECT id, trace_id, created_at FROM events "
            "WHERE event_type='maintenance.heartbeat' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        latest_row = conn.execute(
            "SELECT id, title, created_at, status FROM bug_reports "
            "WHERE title LIKE 'Local maintenance check failed:%' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    latest: dict[str, str] | None = None
    if latest_row is not None:
        latest = {
            "id": str(latest_row["id"]),
            "title": str(latest_row["title"]),
            "created_at": str(latest_row["created_at"]),
            "status": str(latest_row["status"]),
        }

    last_heartbeat: dict[str, str] | None = None
    if heartbeat_row is not None:
        last_heartbeat = {
            "event_id": str(heartbeat_row["id"]),
            "trace_id": str(heartbeat_row["trace_id"]),
            "created_at": str(heartbeat_row["created_at"]),
        }

    return {
        "enabled": int(settings.maintenance_enabled) == 1,
        "heartbeat_interval_seconds": int(settings.maintenance_heartbeat_interval_seconds),
        "interval_seconds": int(settings.maintenance_interval_seconds),
        "timeout_seconds": int(settings.maintenance_timeout_seconds),
        "create_bugs": int(settings.maintenance_create_bugs) == 1,
        "workdir": settings.maintenance_workdir or str(Path.cwd()),
        "commands": commands,
        "periodic_scheduler_active": is_periodic_scheduler_configured(),
        "last_heartbeat": last_heartbeat,
        "open_maintenance_bugs": int(open_count_row["cnt"]) if open_count_row is not None else 0,
        "latest_maintenance_bug": latest,
    }


@maintenance_group.command("status")
@click.option("--json", "json_output", is_flag=True, help="Print full JSON status.")
def maintenance_status(json_output: bool) -> None:
    """Show maintenance configuration and local runtime status."""
    payload = _maintenance_status_payload()
    if json_output:
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    click.echo(f"enabled: {payload['enabled']}")
    click.echo(f"heartbeat_interval_seconds: {payload['heartbeat_interval_seconds']}")
    click.echo(f"interval_seconds: {payload['interval_seconds']}")
    click.echo(f"timeout_seconds: {payload['timeout_seconds']}")
    click.echo(f"create_bugs: {payload['create_bugs']}")
    click.echo(f"workdir: {payload['workdir']}")
    click.echo("commands:")
    commands = payload.get("commands")
    if not isinstance(commands, list):
        commands = []
    for command in commands:
        click.echo(f"  - {command}")
    click.echo(f"periodic_scheduler_active: {payload['periodic_scheduler_active']}")
    last_heartbeat = payload.get("last_heartbeat")
    if isinstance(last_heartbeat, dict):
        click.echo(
            "last_heartbeat: "
            f"{last_heartbeat.get('created_at')} trace={last_heartbeat.get('trace_id')}"
        )
    click.echo(f"open_maintenance_bugs: {payload['open_maintenance_bugs']}")
    latest = payload["latest_maintenance_bug"]
    if isinstance(latest, dict):
        click.echo(
            "latest_maintenance_bug: "
            f"{latest.get('id')} {latest.get('status')} {latest.get('created_at')}"
        )


@maintenance_group.command("run")
@click.option("--json", "json_output", is_flag=True, help="Print full JSON result.")
def maintenance_run(json_output: bool) -> None:
    """Run local maintenance checks immediately (in-process)."""
    from jarvis.tasks.maintenance import run_local_maintenance

    result = run_local_maintenance()
    if json_output:
        click.echo(json.dumps(result, indent=2, sort_keys=True))
        return
    if result.get("ok"):
        click.echo("maintenance run: ok")
    else:
        click.echo("maintenance run: failures detected")
    bug_ids = result.get("bug_ids", [])
    if isinstance(bug_ids, list) and bug_ids:
        click.echo(f"bugs created: {', '.join(str(item) for item in bug_ids)}")


@maintenance_group.command("enqueue")
def maintenance_enqueue() -> None:
    """Enqueue local maintenance checks onto the in-process task runner."""
    from jarvis.tasks import get_task_runner

    ok = get_task_runner().send_task(
        "jarvis.tasks.maintenance.run_local_maintenance",
        queue="agent_default",
    )
    click.echo("maintenance task queued" if ok else "failed to queue maintenance task")


@cli.group("memory")
def memory_group() -> None:
    """Structured memory operations."""


@memory_group.command("review")
@click.option("--conflicts", is_flag=True, help="Show open conflict review items.")
@click.option("--limit", default=50, show_default=True)
def memory_review(conflicts: bool, limit: int) -> None:
    """Review structured memory conflict queue."""
    if not conflicts:
        raise click.ClickException("only --conflicts is currently supported")
    with get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT id, uid, thread_id, reason, status, created_at "
                "FROM memory_review_queue WHERE status='open' "
                "ORDER BY created_at DESC LIMIT ?"
            ),
            (max(1, int(limit)),),
        ).fetchall()
    if not rows:
        click.echo("no open conflict reviews")
        return
    for row in rows:
        click.echo(
            f"{row['id']} uid={row['uid']} thread={row['thread_id']} "
            f"reason={row['reason']} status={row['status']} created_at={row['created_at']}"
        )


@memory_group.command("export")
@click.option("--format", "output_format", default="jsonl", show_default=True)
@click.option("--tier", default="", help="Optional tier filter.")
@click.option("--thread-id", default=None, help="Optional thread filter.")
@click.option("--output", "-o", type=click.Path(), default=None)
@click.option("--limit", default=1000, show_default=True)
def memory_export(
    output_format: str,
    tier: str,
    thread_id: str | None,
    output: str | None,
    limit: int,
) -> None:
    """Export structured memory as JSONL."""
    if output_format.lower() != "jsonl":
        raise click.ClickException("only --format=jsonl is supported")
    with get_conn() as conn:
        if thread_id:
            rows = conn.execute(
                (
                    "SELECT uid, thread_id, text, type_tag, status, tier, "
                    "importance_score, created_at "
                    "FROM state_items WHERE thread_id=? "
                    + ("AND tier=? " if tier.strip() else "")
                    + "ORDER BY created_at DESC LIMIT ?"
                ),
                (
                    (thread_id, tier, max(1, int(limit)))
                    if tier.strip()
                    else (thread_id, max(1, int(limit)))
                ),
            ).fetchall()
        else:
            rows = conn.execute(
                (
                    "SELECT uid, thread_id, text, type_tag, status, tier, "
                    "importance_score, created_at "
                    "FROM state_items "
                    + ("WHERE tier=? " if tier.strip() else "")
                    + "ORDER BY created_at DESC LIMIT ?"
                ),
                ((tier, max(1, int(limit))) if tier.strip() else (max(1, int(limit)),)),
            ).fetchall()
    out = open(output, "w") if output else sys.stdout
    try:
        for row in rows:
            out.write(
                json.dumps(
                    {
                        "uid": str(row["uid"]),
                        "thread_id": str(row["thread_id"]),
                        "text": str(row["text"]),
                        "type_tag": str(row["type_tag"]),
                        "status": str(row["status"]),
                        "tier": str(row["tier"]),
                        "importance_score": float(row["importance_score"]),
                        "created_at": str(row["created_at"]),
                    }
                )
                + "\n"
            )
    finally:
        if output:
            out.close()
    if output:
        click.echo(f"exported to {output}")
