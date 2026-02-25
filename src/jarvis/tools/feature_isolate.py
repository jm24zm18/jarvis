"""Ephemeral workspace orchestration and validation for feature builds."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SAFE_FEATURE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class IsolationError(RuntimeError):
    """Raised when workspace isolation checks fail."""


@dataclass(slots=True)
class WorkspaceContext:
    feature_id: str
    workspace_path: Path
    created_at: str
    expires_at: str
    dependency_snapshot: dict[str, object]


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    log_path: str
    error: str
    details: dict[str, object]


def sanitize_feature_id(feat_id: str) -> str:
    cleaned = feat_id.strip()
    if not cleaned or not _SAFE_FEATURE_ID.fullmatch(cleaned):
        raise IsolationError(f"invalid feature id for workspace: {feat_id!r}")
    return cleaned


def _sha256_file(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def ensure_tmp_capacity(min_free_gb: int = 10, *, target_dir: str = "/tmp") -> None:
    usage = shutil.disk_usage(target_dir)
    free_gb = usage.free // (1024**3)
    if free_gb < int(min_free_gb):
        raise IsolationError(
            f"insufficient free space in {target_dir}: {free_gb}GB < {int(min_free_gb)}GB"
        )


def collect_dependency_snapshot(workspace: Path) -> dict[str, object]:
    lock_path = workspace / "uv.lock"
    pyproject_path = workspace / "pyproject.toml"
    if not lock_path.exists():
        raise IsolationError("uv.lock missing in workspace")
    if not pyproject_path.exists():
        raise IsolationError("pyproject.toml missing in workspace")
    return {
        "uv_lock_sha256": _sha256_file(lock_path),
        "pyproject_sha256": _sha256_file(pyproject_path),
    }


def create_workspace(
    feat_id: str,
    *,
    repo_root: Path,
    tmp_prefix: str = "/tmp/jarvis-feature",
    clone_ref: str = "origin/dev",
    ttl_hours: int = 24,
    min_free_gb: int = 10,
) -> WorkspaceContext:
    safe_id = sanitize_feature_id(feat_id)
    timestamp = int(time.time())
    workspace = Path(f"{tmp_prefix}-{safe_id}-{timestamp}")
    workspace.parent.mkdir(parents=True, exist_ok=True)

    ensure_tmp_capacity(int(min_free_gb), target_dir=str(workspace.parent))
    subprocess.run(
        ["git", "-C", str(repo_root), "fetch", "origin", "dev", "--depth", "1"],
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            "dev",
            str(repo_root),
            str(workspace),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    commit = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    created_dt = datetime.now(UTC)
    expires_dt = created_dt + timedelta(hours=max(1, int(ttl_hours)))
    snapshot = collect_dependency_snapshot(workspace)
    payload = {
        "feature_id": safe_id,
        "clone_ref": clone_ref,
        "commit": commit,
        "created_at": created_dt.isoformat(),
        "expires_at": expires_dt.isoformat(),
        "dependencies": snapshot,
    }
    (workspace / "FEATURE_LOCK").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return WorkspaceContext(
        feature_id=safe_id,
        workspace_path=workspace,
        created_at=created_dt.isoformat(),
        expires_at=expires_dt.isoformat(),
        dependency_snapshot=snapshot,
    )


def validate_workspace(ctx: WorkspaceContext, *, min_free_gb: int = 10) -> ValidationResult:
    workspace = ctx.workspace_path
    logs_dir = workspace / "validation"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "validate.log"
    try:
        ensure_tmp_capacity(int(min_free_gb), target_dir=str(workspace.parent))
        lock_path = workspace / "FEATURE_LOCK"
        if not lock_path.exists():
            raise IsolationError("FEATURE_LOCK is missing")
        current_snapshot = collect_dependency_snapshot(workspace)
        lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))
        expected = lock_payload.get("dependencies", {})
        if not isinstance(expected, dict):
            raise IsolationError("invalid FEATURE_LOCK dependency snapshot")
        if expected != current_snapshot:
            raise IsolationError("dependency snapshot mismatch in clean workspace")
        proc = subprocess.run(
            ["uv", "sync", "--frozen"],
            cwd=str(workspace),
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = (
            f"[command] uv sync --frozen\n"
            f"[exit_code] {proc.returncode}\n\n"
            f"[stdout]\n{proc.stdout}\n\n"
            f"[stderr]\n{proc.stderr}\n"
        )
        log_path.write_text(output, encoding="utf-8")
        if proc.returncode != 0:
            return ValidationResult(
                ok=False,
                log_path=str(log_path),
                error="uv sync --frozen failed",
                details={"exit_code": proc.returncode},
            )
        return ValidationResult(
            ok=True,
            log_path=str(log_path),
            error="",
            details={"snapshot": current_snapshot},
        )
    except Exception as exc:
        log_path.write_text(str(exc), encoding="utf-8")
        return ValidationResult(
            ok=False,
            log_path=str(log_path),
            error=str(exc),
            details={},
        )


def cleanup_workspace(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def cleanup_expired_workspaces(
    *, tmp_prefix: str = "/tmp/jarvis-feature", ttl_hours: int = 24
) -> int:
    parent = Path(tmp_prefix).parent
    stem = Path(tmp_prefix).name
    if not parent.exists():
        return 0
    cutoff = time.time() - (max(1, int(ttl_hours)) * 3600)
    removed = 0
    for candidate in parent.iterdir():
        if not candidate.is_dir():
            continue
        if not candidate.name.startswith(stem + "-"):
            continue
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        cleanup_workspace(candidate)
        removed += 1
    return removed
