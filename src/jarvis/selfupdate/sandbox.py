"""Docker sandbox helpers for self-update smoke gate isolation."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from jarvis.errors import ConfigError


@dataclass(slots=True)
class SandboxResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int


@dataclass(slots=True)
class SandboxContext:
    sandbox_id: str
    worktree_path: Path
    image: str


def create_sandbox(trace_id: str, worktree_path: Path, image: str) -> SandboxContext:
    """Build a SandboxContext and verify Docker is available."""
    check = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if check.returncode != 0:
        raise ConfigError(
            f"Docker is not available (exit {check.returncode}): {check.stderr.strip()}"
        )
    return SandboxContext(
        sandbox_id=f"jarvis-sandbox-{trace_id}",
        worktree_path=worktree_path,
        image=image,
    )


def run_in_sandbox(
    ctx: SandboxContext,
    cmd: list[str],
    env: dict[str, str] | None = None,
    timeout: int = 300,
) -> SandboxResult:
    """Run *cmd* inside a Docker container with the worktree mounted read-only.

    The container is removed on exit (--rm). Network access is disabled
    (--network=none). Memory and CPU are capped.
    """
    env_flags: list[str] = []
    for k, v in (env or {}).items():
        env_flags += ["-e", f"{k}={v}"]

    docker_cmd = [
        "docker", "run", "--rm",
        "--read-only",
        "--network=none",
        "--memory=1g",
        "--cpus=1.0",
        "-v", f"{ctx.worktree_path}:/workspace:ro",
        "-w", "/workspace",
        *env_flags,
        ctx.image,
        *cmd,
    ]

    started = time.monotonic()
    try:
        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        return SandboxResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
            duration_ms=duration_ms,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if exc.stderr else ""
        return SandboxResult(
            ok=False,
            stdout="",
            stderr=f"timeout after {timeout}s: {stderr}",
            exit_code=-1,
            duration_ms=duration_ms,
        )


def cleanup_sandbox(ctx: SandboxContext) -> None:
    """No-op: Docker --rm handles cleanup automatically.

    Reserved for future persistent-container strategies.
    """


def generate_diff_summary(
    repo_path: str,
    worktree_path: Path,
    patch_path: Path,
) -> dict[str, object]:
    """Return a dict with file-change metadata for the applied patch.

    Detects migration files and returns stat output.
    """
    stat_result = subprocess.run(
        ["git", "diff", "--stat", "HEAD"],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    stat = stat_result.stdout.strip()

    name_result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=str(worktree_path),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    files = [f.strip() for f in name_result.stdout.splitlines() if f.strip()]
    migration_files = [f for f in files if "migrations" in f and f.endswith(".sql")]

    return {
        "files_changed": len(files),
        "files": files,
        "migration_pending": bool(migration_files),
        "migration_files": migration_files,
        "stat": stat,
    }
