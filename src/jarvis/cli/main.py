"""Click CLI group: setup, doctor, ask, and chat commands."""

from __future__ import annotations

import click

import json
import sys

from jarvis.cli.chat import default_cli_user, format_reply, resolve_thread, send_and_wait
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
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path (default: stdout).")
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
