"""Self-update pipeline helpers with safety gates."""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import cast

PROTECTED_PATH_PATTERNS = (
    re.compile(r"^/etc/systemd/system/"),
    re.compile(r"^/etc/sudoers$"),
    re.compile(r"^/etc/sudoers\.d/"),
    re.compile(r"^/etc/ssh/"),
    re.compile(r"^/etc/.*iptables"),
    re.compile(r"^/etc/nftables"),
    re.compile(r"^/root/"),
)


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    reason: str


def trace_dir(base_dir: Path, trace_id: str) -> Path:
    return base_dir / trace_id


def write_patch(trace_id: str, patch_text: str, base_dir: Path) -> Path:
    directory = trace_dir(base_dir, trace_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "proposal.diff"
    path.write_text(patch_text)
    return path


def read_patch(trace_id: str, base_dir: Path) -> str:
    return (trace_dir(base_dir, trace_id) / "proposal.diff").read_text()


def write_artifact(trace_id: str, base_dir: Path, artifact: dict[str, object]) -> Path:
    directory = trace_dir(base_dir, trace_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "artifact.json"
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True))
    return path


def read_artifact(trace_id: str, base_dir: Path) -> dict[str, object]:
    path = trace_dir(base_dir, trace_id) / "artifact.json"
    if not path.exists():
        return {}
    decoded = json.loads(path.read_text())
    return cast(dict[str, object], decoded if isinstance(decoded, dict) else {})


def update_artifact_section(
    trace_id: str,
    base_dir: Path,
    section: str,
    payload: dict[str, object],
) -> dict[str, object]:
    artifact = read_artifact(trace_id, base_dir)
    current = artifact.get(section)
    merged: dict[str, object] = {}
    if isinstance(current, dict):
        merged.update(current)
    merged.update(payload)
    artifact[section] = merged
    write_artifact(trace_id, base_dir, artifact)
    return artifact


def write_state(trace_id: str, base_dir: Path, state: str, detail: str = "") -> Path:
    directory = trace_dir(base_dir, trace_id)
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "state.json"
    state_path.write_text(json.dumps({"trace_id": trace_id, "state": state, "detail": detail}))
    return state_path


def read_state(trace_id: str, base_dir: Path) -> dict[str, str]:
    state = json.loads((trace_dir(base_dir, trace_id) / "state.json").read_text())
    return cast(dict[str, str], state)


def write_context(
    trace_id: str,
    base_dir: Path,
    repo_path: str,
    rationale: str,
    baseline_ref: str = "",
) -> Path:
    directory = trace_dir(base_dir, trace_id)
    directory.mkdir(parents=True, exist_ok=True)
    context_path = directory / "context.json"
    context_path.write_text(
        json.dumps(
            {
                "trace_id": trace_id,
                "repo_path": repo_path,
                "rationale": rationale,
                "baseline_ref": baseline_ref,
            }
        )
    )
    return context_path


def read_context(trace_id: str, base_dir: Path) -> dict[str, str]:
    context = json.loads((trace_dir(base_dir, trace_id) / "context.json").read_text())
    return cast(dict[str, str], context)


def changed_files_from_patch(patch_text: str) -> list[str]:
    changed: list[str] = []
    for line in patch_text.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        for candidate in (parts[2], parts[3]):
            normalized = candidate
            if normalized.startswith("a/") or normalized.startswith("b/"):
                normalized = normalized[2:]
            if normalized and normalized != "/dev/null":
                changed.append(normalized)
    unique: list[str] = []
    seen: set[str] = set()
    for path in changed:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def touches_critical_paths(changed_files: list[str], critical_patterns: list[str]) -> bool:
    for file_path in changed_files:
        for pattern in critical_patterns:
            if fnmatch(file_path, pattern):
                return True
    return False


def includes_test_changes(changed_files: list[str]) -> bool:
    return any(path.startswith("tests/") for path in changed_files)


def validate_patch_content(patch_text: str) -> ValidationResult:
    if not patch_text.strip():
        return ValidationResult(ok=False, reason="empty patch")
    if "diff --git" not in patch_text:
        return ValidationResult(ok=False, reason="missing unified diff header")

    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                for candidate in (parts[2], parts[3]):
                    normalized = candidate
                    if normalized.startswith("a/") or normalized.startswith("b/"):
                        normalized = normalized[2:]
                    absolute = f"/{normalized.lstrip('/')}"
                    if any(pattern.match(absolute) for pattern in PROTECTED_PATH_PATTERNS):
                        return ValidationResult(
                            ok=False, reason=f"protected path rejected: {absolute}"
                        )
        if line.startswith("+++ ") or line.startswith("--- "):
            candidate = line[4:].strip()
            if candidate.startswith("a/") or candidate.startswith("b/"):
                candidate = candidate[2:]
            if candidate == "/dev/null":
                continue
            absolute = f"/{candidate.lstrip('/')}"
            if any(pattern.match(absolute) for pattern in PROTECTED_PATH_PATTERNS):
                return ValidationResult(ok=False, reason=f"protected path rejected: {absolute}")
    return ValidationResult(ok=True, reason="validated")


def evaluate_test_gate(patch_text: str) -> ValidationResult:
    if "FAIL_TEST" in patch_text:
        return ValidationResult(ok=False, reason="test gate failed marker")
    return ValidationResult(ok=True, reason="test gate passed")


def git_apply_check(repo_path: str, patch_path: Path) -> ValidationResult:
    proc = subprocess.run(
        ["git", "-C", repo_path, "apply", "--check", str(patch_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "git apply --check failed"
        return ValidationResult(ok=False, reason=stderr)
    return ValidationResult(ok=True, reason="git apply check passed")


def git_apply(repo_path: str, patch_path: Path) -> ValidationResult:
    proc = subprocess.run(
        ["git", "-C", repo_path, "apply", str(patch_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "git apply failed"
        return ValidationResult(ok=False, reason=stderr)
    return ValidationResult(ok=True, reason="git apply passed")


def git_commit_applied(
    repo_path: str, trace_id: str, branch: str | None = None
) -> ValidationResult:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    selected_branch = branch or f"auto/{stamp}"
    checkout = subprocess.run(
        ["git", "-C", repo_path, "checkout", "-B", selected_branch],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if checkout.returncode != 0:
        return ValidationResult(ok=False, reason=checkout.stderr.strip() or "branch create failed")

    add = subprocess.run(
        ["git", "-C", repo_path, "add", "-A"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if add.returncode != 0:
        return ValidationResult(ok=False, reason=add.stderr.strip() or "git add failed")

    message = f"auto-update {trace_id}"
    commit = subprocess.run(
        ["git", "-C", repo_path, "commit", "-m", message],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if commit.returncode != 0:
        return ValidationResult(ok=False, reason=commit.stderr.strip() or "git commit failed")
    return ValidationResult(ok=True, reason=f"committed on {selected_branch}")


def smoke_commands(profile: str, has_src: bool, has_tests: bool) -> list[list[str]]:
    commands: list[list[str]] = []
    if has_src or has_tests:
        targets: list[str] = []
        if has_src:
            targets.append("src")
        if has_tests:
            targets.append("tests")
        commands.append(["ruff", "check", *targets])
    if has_tests:
        commands.append(["pytest", "tests", "-q"])
    if profile == "prod" and has_src:
        commands.append(["mypy", "src"])
    return commands


def run_smoke_gate(
    repo_path: str,
    patch_path: Path,
    work_dir: Path,
    profile: str,
) -> ValidationResult:
    work_dir.mkdir(parents=True, exist_ok=True)
    worktree = work_dir / "worktree"

    add = subprocess.run(
        ["git", "-C", repo_path, "worktree", "add", "--detach", str(worktree), "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if add.returncode != 0:
        return ValidationResult(ok=False, reason=add.stderr.strip() or "worktree add failed")

    try:
        apply_result = git_apply(str(worktree), patch_path)
        if not apply_result.ok:
            return apply_result

        has_src = (worktree / "src").exists()
        has_tests = (worktree / "tests").exists()
        checks = smoke_commands(profile=profile, has_src=has_src, has_tests=has_tests)

        if not checks:
            return ValidationResult(ok=True, reason="no smoke targets")

        env = os.environ.copy()
        for cmd in checks:
            proc = subprocess.run(
                cmd,
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.strip()
                stdout = proc.stdout.strip()
                detail = stderr or stdout or f"{cmd[0]} failed"
                return ValidationResult(ok=False, reason=detail)
        return ValidationResult(ok=True, reason="smoke gate passed")
    finally:
        subprocess.run(
            ["git", "-C", repo_path, "worktree", "remove", "--force", str(worktree)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )


def mark_applied(trace_id: str, base_dir: Path) -> Path:
    marker = trace_dir(base_dir, trace_id) / "applied.txt"
    marker.write_text("applied")
    return marker


def mark_verified(trace_id: str, base_dir: Path) -> Path:
    marker = trace_dir(base_dir, trace_id) / "verified.txt"
    marker.write_text("verified")
    return marker


def mark_rollback(trace_id: str, base_dir: Path, reason: str) -> Path:
    marker = trace_dir(base_dir, trace_id) / "rollback.txt"
    marker.write_text(reason)
    return marker
