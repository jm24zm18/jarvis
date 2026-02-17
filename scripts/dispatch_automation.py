#!/usr/bin/env python3
"""Orchestrate automation tasks by dispatching to Jarvis specialist agents.

Creates threads, inserts implementation prompts, and dispatches agent_step
Celery tasks to the appropriate specialist agents.

Usage:
    uv run python scripts/dispatch_automation.py --dry-run   # Print plan without dispatching
    uv run python scripts/dispatch_automation.py             # Execute all tasks
    uv run python scripts/dispatch_automation.py --status    # Check status of dispatched tasks
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field

import httpx

# Ensure project root is importable
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src"))

from jarvis.celery_app import celery_app  # noqa: E402, I001
from jarvis.db.connection import get_conn  # noqa: E402
from jarvis.db.queries import (  # noqa: E402
    create_thread,
    ensure_channel,
    ensure_root_user,
    ensure_system_state,
    insert_message,
)
from jarvis.ids import new_id  # noqa: E402


# ---------------------------------------------------------------------------
# Task definitions
# ---------------------------------------------------------------------------

BATCH_1: dict[str, str] = {
    "web_builder": """\
Item 2: Frontend CI

1. Create `web/eslint.config.mjs` — ESLint v9 flat config with @eslint/js, typescript-eslint, \
eslint-plugin-react-hooks, eslint-config-prettier.
2. Create `web/.prettierrc` — { "semi": true, "singleQuote": true }
3. Add devDependencies to `web/package.json`: eslint, @eslint/js, typescript-eslint, \
eslint-plugin-react-hooks, eslint-config-prettier, prettier.
4. Add scripts to `web/package.json`: "lint", "format:check", "typecheck" (tsc --noEmit).
5. Keep strict: false in web/tsconfig.json.

Branch: chore/frontend-ci
Verify: cd web && npm ci && npm run lint && npm run format:check && npm run typecheck && npm test
""",
    "coder": """\
Item 3: Agent Bundle Validation

1. Create `scripts/validate_agents.py`:
   - Scan all agents/*/ directories
   - Check each has identity.md, soul.md, heartbeat.md
   - Parse YAML frontmatter from identity.md, validate agent_id matches directory name
   - Validate allowed_tools is non-empty
   - Auto-discover registered tools by regex-scanning src/jarvis/tasks/agent.py
   - Exit 0 on success, exit 1 with errors
2. Add validate-agents job to .github/workflows/ci.yml
3. Add validate-agents target to Makefile

Branch: chore/agent-validation
Verify: uv run python scripts/validate_agents.py
""",
    "data_migrator": """\
Item 4: DB Migration CI Testing

1. Create `scripts/test_migrations.py`:
   - Create temp SQLite DB
   - Apply all src/jarvis/db/migrations/*.sql in sorted order
   - Track in schema_migrations table
   - Run PRAGMA integrity_check
   - Print applied count + table names
   - Pure stdlib (sqlite3, pathlib, tempfile)
2. Add test-migrations job to .github/workflows/ci.yml (just python, no uv)
3. Add test-migrations target to Makefile

Branch: chore/migration-testing
Verify: python scripts/test_migrations.py
""",
    "security_reviewer": """\
Item 5: Security Scanning

1. Add to pyproject.toml dev deps: bandit>=1.8,<2 and pip-audit>=2.7,<3
2. Add [tool.bandit] config: exclude_dirs = ["tests"], skips = ["B101"]
3. Add security job to .github/workflows/ci.yml:
   - uv run bandit -r src/jarvis -c pyproject.toml -ll
   - uv run pip-audit
   - trufflesecurity/trufflehog@main action (--only-verified)
4. Add security target to Makefile

Branch: chore/security-scanning
Verify: make security
""",
    "release_ops": """\
Item 6+7: Dependabot + Release Automation

1. Create `.github/dependabot.yml`:
   - pip ecosystem (/, weekly Monday, limit 5)
   - npm ecosystem (/web, weekly Monday, limit 5)
   - github-actions ecosystem (/, weekly Monday, limit 3)
2. Add python-semantic-release>=9.0,<10 to pyproject.toml dev deps
3. Add [tool.semantic_release] config: version_variables, branch = "master"
4. Create `.github/workflows/release.yml`:
   - Trigger on push to master
   - semantic-release version + publish
5. Update docs/build-release.md with automated release flow

Branch: chore/release-automation
Verify: Push to remote, check GitHub Settings > Dependabot
""",
    "tester": """\
Item 8: Coverage Improvements

1. Add diff-cover>=9.0,<10 to pyproject.toml dev deps
2. Update coverage job in .github/workflows/ci.yml:
   - Generate both XML (coverage.xml) and JSON reports
   - Add codecov/codecov-action@v4 upload step
   - Add diff-cover coverage.xml --compare-branch=origin/dev --fail-under=80 for PRs

Branch: chore/coverage-improvements
Verify: Open a PR to dev, verify diff-cover runs
""",
}

BATCH_2: dict[str, str] = {
    "lintfixer": """\
Item 1: Pre-commit Hooks

1. Create `.pre-commit-config.yaml`:
   - pre-commit/pre-commit-hooks: trailing-whitespace, end-of-file-fixer, check-yaml, check-json
   - astral-sh/ruff-pre-commit: ruff check --fix, ruff-format
   - local hooks: mypy (uv run mypy src), validate-agents (uv run python scripts/validate_agents.py)
2. Add pre-commit>=4.0,<5 to pyproject.toml dev deps
3. Add hooks target to Makefile: uv run pre-commit install

Branch: chore/pre-commit-hooks
Verify: make hooks && uv run pre-commit run --all-files
""",
    "coder": """\
Item 9: Source Code Wiring Fixes

1. In src/jarvis/tasks/agent.py:
   - Line 209: Change hardcoded agent list hint to generic "to_agent_id is required"
   - Line 467: Change "Target agent ID (main, researcher, planner, coder)" to "Target agent ID"
2. Update Makefile test-gates to include validate-agents and test-migrations
3. Update docs/testing.md with validate-agents and test-migrations gates

Branch: chore/agent-wiring-fixes
Verify: make test-gates
""",
}


@dataclass
class DispatchedTask:
    agent_id: str
    thread_id: str
    trace_id: str
    user_msg_id: str
    user_msg_at: str
    description: str
    status: str = "dispatched"
    result: str | None = None


@dataclass
class Dispatcher:
    api_base: str = "http://localhost:8000"
    tasks: list[DispatchedTask] = field(default_factory=list)

    def get_max_concurrency(self) -> int:
        """Check provider health to determine concurrency level."""
        try:
            resp = httpx.get(f"{self.api_base}/readyz", timeout=3.0)
            data = resp.json()
            providers = data.get("providers", {})
            if providers.get("primary"):
                return 7  # all batch 1 tasks in parallel
            return 1  # local LLM, sequential only
        except Exception:
            return 1

    def dispatch_task(self, agent_id: str, prompt: str) -> DispatchedTask:
        """Create a thread, insert the prompt, and dispatch agent_step."""
        with get_conn() as conn:
            ensure_system_state(conn)
            user_id = ensure_root_user(conn)
            channel_id = ensure_channel(conn, user_id, "cli")
            thread_id = create_thread(conn, user_id, channel_id)
            user_msg_id = insert_message(conn, thread_id, "user", prompt)
            # Get the created_at timestamp
            row = conn.execute(
                "SELECT created_at FROM messages WHERE id=?", (user_msg_id,)
            ).fetchone()
            user_msg_at = str(row["created_at"]) if row else ""

        trace_id = new_id("trc")
        celery_app.send_task(
            "jarvis.tasks.agent.agent_step",
            kwargs={
                "trace_id": trace_id,
                "thread_id": thread_id,
                "actor_id": agent_id,
            },
            queue="agent_priority",
        )

        task = DispatchedTask(
            agent_id=agent_id,
            thread_id=thread_id,
            trace_id=trace_id,
            user_msg_id=user_msg_id,
            user_msg_at=user_msg_at,
            description=prompt.split("\n")[0],
        )
        self.tasks.append(task)
        return task

    def check_task_status(self, task: DispatchedTask) -> str:
        """Poll for an assistant response."""
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id, content FROM messages "
                "WHERE thread_id=? AND role='assistant' AND created_at>=? "
                "ORDER BY created_at ASC LIMIT 1",
                (task.thread_id, task.user_msg_at),
            ).fetchone()
        if row is not None:
            task.status = "completed"
            task.result = str(row["content"])[:200]
            return "completed"
        return "pending"

    def dispatch_batch(
        self, batch: dict[str, str], max_concurrency: int
    ) -> list[DispatchedTask]:
        """Dispatch a batch of tasks respecting concurrency limits."""
        items = list(batch.items())
        dispatched: list[DispatchedTask] = []

        if max_concurrency >= len(items):
            # All in parallel
            for agent_id, prompt in items:
                task = self.dispatch_task(agent_id, prompt)
                print(f"  Dispatched to {agent_id}: {task.thread_id}")
                dispatched.append(task)
        else:
            # Sequential
            for agent_id, prompt in items:
                task = self.dispatch_task(agent_id, prompt)
                print(f"  Dispatched to {agent_id}: {task.thread_id}")
                dispatched.append(task)
                # Wait for completion before next
                if max_concurrency == 1:
                    print(f"    Waiting for {agent_id}...")
                    self._wait_for_task(task, timeout=600)

        return dispatched

    def _wait_for_task(self, task: DispatchedTask, timeout: float = 600) -> None:
        """Poll until task completes or times out."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.check_task_status(task) == "completed":
                print(f"    {task.agent_id} completed")
                return
            time.sleep(5)
        print(f"    {task.agent_id} timed out after {timeout}s")
        task.status = "timeout"

    def wait_for_batch(self, tasks: list[DispatchedTask], timeout: float = 900) -> None:
        """Wait for all tasks in a batch to complete."""
        deadline = time.monotonic() + timeout
        pending = set(range(len(tasks)))
        while pending and time.monotonic() < deadline:
            for i in list(pending):
                if self.check_task_status(tasks[i]) == "completed":
                    print(f"  {tasks[i].agent_id} completed")
                    pending.discard(i)
            if pending:
                time.sleep(5)
        for i in pending:
            tasks[i].status = "timeout"
            print(f"  {tasks[i].agent_id} timed out")

    def print_status(self) -> None:
        """Print status of all dispatched tasks."""
        print("\n--- Task Status ---")
        for task in self.tasks:
            self.check_task_status(task)
            result_preview = f" | {task.result}" if task.result else ""
            print(
                f"  [{task.status:>9}] {task.agent_id:<20} "
                f"thread={task.thread_id}{result_preview}"
            )


def dry_run() -> None:
    """Print the plan without dispatching."""
    print("=== Batch 1 (parallel) ===\n")
    for agent_id, prompt in BATCH_1.items():
        print(f"  Agent: {agent_id}")
        print(f"  Task:  {prompt.split(chr(10))[0]}")
        print()

    print("=== Batch 2 (after Batch 1) ===\n")
    for agent_id, prompt in BATCH_2.items():
        print(f"  Agent: {agent_id}")
        print(f"  Task:  {prompt.split(chr(10))[0]}")
        print()

    print(f"Total: {len(BATCH_1)} + {len(BATCH_2)} = {len(BATCH_1) + len(BATCH_2)} tasks")


def run_status() -> None:
    """Check status of recent orchestrator threads."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT t.id, t.created_at, "
            "(SELECT COUNT(*) FROM messages m "
            "WHERE m.thread_id=t.id AND m.role='assistant') as replies "
            "FROM threads t "
            "JOIN channels c ON c.id=t.channel_id "
            "JOIN users u ON u.id=t.user_id "
            "WHERE u.external_id='system:root' "
            "ORDER BY t.created_at DESC LIMIT 20"
        ).fetchall()

    if not rows:
        print("No orchestrator threads found.")
        return

    print("Recent orchestrator threads:")
    for row in rows:
        status = "completed" if row["replies"] > 0 else "pending"
        print(f"  [{status:>9}] {row['id']}  created={row['created_at']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Dispatch automation tasks to Jarvis agents")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without dispatching")
    parser.add_argument("--status", action="store_true", help="Check status of dispatched tasks")
    parser.add_argument(
        "--api-base", default="http://localhost:8000", help="Jarvis API base URL"
    )
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
        return 0

    if args.status:
        run_status()
        return 0

    dispatcher = Dispatcher(api_base=args.api_base)
    max_concurrency = dispatcher.get_max_concurrency()
    print(f"Provider concurrency: {max_concurrency}")

    print("\n=== Dispatching Batch 1 ===")
    batch1_tasks = dispatcher.dispatch_batch(BATCH_1, max_concurrency)

    print("\nWaiting for Batch 1 to complete...")
    dispatcher.wait_for_batch(batch1_tasks, timeout=900)

    # Re-check concurrency in case primary came back
    max_concurrency = dispatcher.get_max_concurrency()

    print("\n=== Dispatching Batch 2 ===")
    batch2_tasks = dispatcher.dispatch_batch(BATCH_2, max_concurrency)

    print("\nWaiting for Batch 2 to complete...")
    dispatcher.wait_for_batch(batch2_tasks, timeout=600)

    dispatcher.print_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
