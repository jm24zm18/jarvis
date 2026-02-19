"""Self-update pipeline helpers with safety gates."""

import json
import os
import re
import shlex
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
GOVERNANCE_IDENTITY_FIELDS = {
    "allowed_tools",
    "risk_tier",
    "max_actions_per_step",
    "allowed_paths",
    "can_request_privileged_change",
}
_IDENTITY_LIST_FIELDS = {"allowed_tools", "allowed_paths"}


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    reason: str


@dataclass(slots=True)
class ReplayResult:
    ok: bool
    reason: str
    tree_hash: str
    changed_files: list[str]


@dataclass(slots=True)
class CommandResult:
    command: str
    exit_code: int
    ok: bool
    stdout: str
    stderr: str
    duration_ms: int


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


def governance_identity_edits_from_patch(patch_text: str) -> list[str]:
    flagged: set[str] = set()
    current_file = ""
    current_key = ""
    for raw_line in patch_text.splitlines():
        if raw_line.startswith("diff --git "):
            parts = raw_line.split()
            current_file = ""
            current_key = ""
            if len(parts) >= 4:
                candidate = parts[3]
                if candidate.startswith("b/"):
                    candidate = candidate[2:]
                if candidate.startswith("agents/") and candidate.endswith("/identity.md"):
                    current_file = candidate
            continue
        if not current_file:
            continue
        if raw_line.startswith("@@"):
            current_key = ""
            continue
        if raw_line.startswith("+++ ") or raw_line.startswith("--- "):
            continue
        if not raw_line or raw_line[0] not in {" ", "+", "-"}:
            continue
        marker = raw_line[0]
        content = raw_line[1:]
        key_match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", content)
        if key_match:
            current_key = key_match.group(1)
            if marker in {"+", "-"} and current_key in GOVERNANCE_IDENTITY_FIELDS:
                flagged.add(current_file)
                continue
        if (
            marker in {"+", "-"}
            and current_key in _IDENTITY_LIST_FIELDS
            and re.match(r"\s*-\s+\S+", content)
        ):
            flagged.add(current_file)
    return sorted(flagged)


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


def evaluate_test_first_gate(
    *,
    artifact: dict[str, object] | None,
    changed_files: list[str],
    critical_patterns: list[str],
    min_coverage_pct: float,
    require_critical_path_tests: bool,
) -> tuple[bool, list[dict[str, str]], dict[str, object]]:
    failures: list[dict[str, str]] = []
    tests = artifact.get("tests") if isinstance(artifact, dict) else None
    tests_dict = tests if isinstance(tests, dict) else {}
    result = str(tests_dict.get("result") or "").strip().lower()
    command_results = tests_dict.get("command_results")
    has_command_evidence = isinstance(command_results, list) and len(command_results) > 0

    if result == "failed":
        failures.append(
            {
                "code": "failing_test_evidence",
                "message": "artifact.tests.result is failed",
            }
        )
    elif result != "passed" or not has_command_evidence:
        failures.append(
            {
                "code": "missing_test_evidence",
                "message": "artifact.tests.result=passed with command_results is required",
            }
        )

    coverage_pct = tests_dict.get("coverage_pct")
    parsed_coverage: float | None = None
    if isinstance(coverage_pct, int | float):
        parsed_coverage = float(coverage_pct)
    elif isinstance(coverage_pct, str):
        try:
            parsed_coverage = float(coverage_pct.strip())
        except Exception:
            parsed_coverage = None
    if min_coverage_pct > 0:
        if parsed_coverage is None:
            failures.append(
                {
                    "code": "missing_coverage_evidence",
                    "message": "artifact.tests.coverage_pct is required in enforce mode",
                }
            )
        elif parsed_coverage < min_coverage_pct:
            failures.append(
                {
                    "code": "coverage_floor_failed",
                    "message": (
                        f"coverage {parsed_coverage:.2f} is below configured floor "
                        f"{min_coverage_pct:.2f}"
                    ),
                }
            )

    critical_change = touches_critical_paths(changed_files, critical_patterns)
    if require_critical_path_tests and critical_change and not includes_test_changes(changed_files):
        failures.append(
            {
                "code": "critical_path_tests_missing",
                "message": "critical-path patch must include tests/ changes",
            }
        )

    detail = {
        "changed_files": changed_files,
        "critical_change": critical_change,
        "require_critical_path_tests": require_critical_path_tests,
        "min_coverage_pct": min_coverage_pct,
        "observed_coverage_pct": parsed_coverage,
        "test_result": result or "missing",
        "has_command_evidence": has_command_evidence,
        "failure_codes": [item["code"] for item in failures],
    }
    return (len(failures) == 0), failures, detail


def _git_show_file(repo_path: str, baseline_ref: str, path: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo_path, "show", f"{baseline_ref}:{path}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise FileNotFoundError(path)
    return proc.stdout


def validate_evidence_refs_in_repo(
    *,
    repo_path: str,
    baseline_ref: str,
    file_refs: list[str],
    line_refs: list[str],
    changed_files: list[str],
) -> ValidationResult:
    baseline = baseline_ref.strip()
    if not baseline:
        return ValidationResult(ok=False, reason="missing baseline_ref for evidence verification")

    expected_files = set(changed_files)
    if not expected_files:
        return ValidationResult(
            ok=False,
            reason="patch must include changed files for evidence check",
        )

    missing_files = []
    for item in file_refs:
        path = item.split(":", 1)[0].strip()
        if path and path not in expected_files:
            missing_files.append(path)
    if missing_files:
        return ValidationResult(
            ok=False,
            reason=f"file_refs not present in patch: {sorted(set(missing_files))}",
        )

    for raw in line_refs:
        try:
            path, line_str = raw.split(":", 1)
            line_no = int(line_str)
        except Exception:
            return ValidationResult(ok=False, reason=f"invalid line_ref: {raw}")
        if path not in expected_files:
            return ValidationResult(ok=False, reason=f"line_ref path not in patch: {raw}")
        try:
            content = _git_show_file(repo_path, baseline, path)
        except FileNotFoundError:
            return ValidationResult(ok=False, reason=f"line_ref file missing at baseline: {path}")
        lines = content.splitlines()
        if line_no < 1 or line_no > max(1, len(lines)):
            return ValidationResult(ok=False, reason=f"line_ref out of range: {raw}")
    return ValidationResult(ok=True, reason="evidence refs verified")


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


def execute_test_plan(
    *,
    repo_path: str,
    patch_path: Path,
    work_dir: Path,
    commands: list[str],
) -> tuple[ValidationResult, list[CommandResult]]:
    work_dir.mkdir(parents=True, exist_ok=True)
    worktree = work_dir / "test_worktree"
    if worktree.exists():
        subprocess.run(
            ["git", "-C", repo_path, "worktree", "remove", "--force", str(worktree)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    add = subprocess.run(
        ["git", "-C", repo_path, "worktree", "add", "--detach", str(worktree), "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if add.returncode != 0:
        return (
            ValidationResult(ok=False, reason=add.stderr.strip() or "test worktree add failed"),
            [],
        )

    results: list[CommandResult] = []
    try:
        apply_result = git_apply(str(worktree), patch_path)
        if not apply_result.ok:
            return apply_result, []
        for command in commands:
            started = datetime.now(UTC)
            proc = subprocess.run(
                ["/bin/bash", "-lc", command],
                cwd=worktree,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            finished = datetime.now(UTC)
            duration_ms = int((finished - started).total_seconds() * 1000)
            result = CommandResult(
                command=command,
                exit_code=proc.returncode,
                ok=proc.returncode == 0,
                stdout=(proc.stdout or "")[:5000],
                stderr=(proc.stderr or "")[:5000],
                duration_ms=duration_ms,
            )
            results.append(result)
            if proc.returncode != 0:
                prefix = shlex.split(command)[0] if command.strip() else "command"
                detail = (proc.stderr or proc.stdout or f"{prefix} failed").strip()
                return ValidationResult(ok=False, reason=detail[:500]), results
        return ValidationResult(ok=True, reason="test plan passed"), results
    except subprocess.TimeoutExpired:
        return ValidationResult(ok=False, reason="test plan command timed out"), results
    finally:
        subprocess.run(
            ["git", "-C", repo_path, "worktree", "remove", "--force", str(worktree)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )


def replay_patch_determinism_check(
    repo_path: str,
    baseline_ref: str,
    patch_path: Path,
    work_dir: Path,
) -> ReplayResult:
    baseline = baseline_ref.strip()
    if not baseline:
        return ReplayResult(
            ok=False,
            reason="missing baseline_ref for replay verification",
            tree_hash="",
            changed_files=[],
        )
    work_dir.mkdir(parents=True, exist_ok=True)
    worktree = work_dir / "replay_worktree"
    if worktree.exists():
        subprocess.run(
            ["git", "-C", repo_path, "worktree", "remove", "--force", str(worktree)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    add = subprocess.run(
        ["git", "-C", repo_path, "worktree", "add", "--detach", str(worktree), baseline],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if add.returncode != 0:
        return ReplayResult(
            ok=False,
            reason=add.stderr.strip() or "replay worktree add failed",
            tree_hash="",
            changed_files=[],
        )
    try:
        apply_result = git_apply(str(worktree), patch_path)
        if not apply_result.ok:
            return ReplayResult(
                ok=False,
                reason=apply_result.reason,
                tree_hash="",
                changed_files=[],
            )
        patch_text = patch_path.read_text()
        expected_files = sorted(changed_files_from_patch(patch_text))
        diff_proc = subprocess.run(
            ["git", "-C", str(worktree), "diff", "--name-only"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if diff_proc.returncode != 0:
            return ReplayResult(
                ok=False,
                reason=diff_proc.stderr.strip() or "replay diff listing failed",
                tree_hash="",
                changed_files=[],
            )
        changed_files = sorted(
            [line.strip() for line in diff_proc.stdout.splitlines() if line.strip()]
        )
        if changed_files != expected_files:
            return ReplayResult(
                ok=False,
                reason="replay changed files mismatch",
                tree_hash="",
                changed_files=changed_files,
            )
        write_tree = subprocess.run(
            ["git", "-C", str(worktree), "write-tree"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if write_tree.returncode != 0:
            return ReplayResult(
                ok=False,
                reason=write_tree.stderr.strip() or "replay write-tree failed",
                tree_hash="",
                changed_files=changed_files,
            )
        tree_hash = write_tree.stdout.strip()
        if not tree_hash:
            return ReplayResult(
                ok=False,
                reason="replay tree hash missing",
                tree_hash="",
                changed_files=changed_files,
            )
        return ReplayResult(
            ok=True,
            reason="replay verification passed",
            tree_hash=tree_hash,
            changed_files=changed_files,
        )
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
