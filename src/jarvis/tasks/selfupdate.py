"""Self-update Celery tasks."""

import json
import subprocess
import time
from pathlib import Path

import httpx

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import consume_approval, get_system_state, now_iso, register_rollback
from jarvis.events.envelope import with_action_envelope
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.selfupdate.contracts import default_artifact, validate_evidence_packet
from jarvis.selfupdate.pipeline import (
    changed_files_from_patch,
    evaluate_test_gate,
    git_apply,
    git_apply_check,
    git_commit_applied,
    includes_test_changes,
    mark_applied,
    mark_rollback,
    mark_verified,
    read_context,
    read_patch,
    read_state,
    replay_patch_determinism_check,
    run_smoke_gate,
    touches_critical_paths,
    update_artifact_section,
    validate_patch_content,
    write_artifact,
    write_context,
    write_patch,
    write_state,
)
from jarvis.tasks.system import enqueue_restart, system_restart

PATCH_BASE = Path("/var/lib/agent/patches")


def _patch_base() -> Path:
    settings = get_settings()
    configured = settings.selfupdate_patch_dir.strip()
    if configured:
        return Path(configured)
    return PATCH_BASE


def _emit(trace_id: str, event_type: str, payload: dict[str, object]) -> None:
    enveloped = with_action_envelope(payload)
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=None,
                event_type=event_type,
                component="selfupdate",
                actor_type="system",
                actor_id="selfupdate",
                payload_json=json.dumps(enveloped),
                payload_redacted_json=json.dumps(redact_payload(enveloped)),
            ),
        )


def _readyz_ok(url: str, attempts: int) -> bool:
    if not url.strip():
        return True
    for _ in range(max(1, attempts)):
        try:
            response = httpx.get(url, timeout=5.0)
            if response.status_code < 400:
                body = response.json()
                if isinstance(body, dict) and bool(body.get("ok")):
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _critical_patterns() -> list[str]:
    settings = get_settings()
    configured = [
        item.strip()
        for item in settings.selfupdate_critical_paths.split(",")
        if item.strip()
    ]
    if configured:
        return configured
    return [
        "src/jarvis/policy/**",
        "src/jarvis/tools/runtime.py",
        "src/jarvis/auth/**",
        "src/jarvis/routes/api/**",
        "src/jarvis/db/migrations/**",
    ]


def _record_failure_capsule(trace_id: str, phase: str, reason: str) -> None:
    capsule_id = f"fcp_{new_id('evt')[4:]}"
    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT COALESCE(MAX(attempt), 0) AS n "
                "FROM failure_capsules WHERE trace_id=? AND phase=?"
            ),
            (trace_id, phase),
        ).fetchone()
        attempt = (int(row["n"]) if row is not None else 0) + 1
        details = {
            "trace_id": trace_id,
            "phase": phase,
            "reason": reason,
        }
        conn.execute(
            (
                "INSERT INTO failure_capsules("
                "id, trace_id, phase, error_summary, error_details_json, attempt, created_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                capsule_id,
                trace_id,
                phase,
                reason[:600],
                json.dumps(details, sort_keys=True),
                attempt,
                now_iso(),
            ),
        )


def _find_similar_failure_capsules(reason: str, limit: int = 5) -> list[dict[str, object]]:
    text = reason.strip()
    if not text:
        return []
    with get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT trace_id, phase, error_summary, attempt, created_at "
                "FROM failure_capsules "
                "WHERE error_summary LIKE ? "
                "ORDER BY created_at DESC LIMIT ?"
            ),
            (f"%{text[:64]}%", max(1, limit)),
        ).fetchall()
    return [
        {
            "trace_id": str(row["trace_id"]),
            "phase": str(row["phase"]),
            "error_summary": str(row["error_summary"]),
            "attempt": int(row["attempt"]),
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def _parse_repo_full_name(origin_url: str) -> str:
    url = origin_url.strip()
    if not url:
        return ""
    if url.endswith(".git"):
        url = url[:-4]
    if url.startswith("git@") and ":" in url:
        return url.split(":", 1)[1]
    if "/" in url:
        return "/".join(url.rstrip("/").split("/")[-2:])
    return ""


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Jarvis-Selfupdate/1.0",
    }


def self_update_open_pr(trace_id: str) -> dict[str, str]:
    settings = get_settings()
    patch_base = _patch_base()
    context = read_context(trace_id, patch_base)
    repo_path = context.get("repo_path", "")
    patch_path = patch_base / trace_id / "proposal.diff"
    branch = f"auto/{trace_id}"

    token = settings.github_token.strip()
    if not token:
        write_state(trace_id, patch_base, "pr_failed", "missing GITHUB_TOKEN")
        update_artifact_section(
            trace_id,
            patch_base,
            "pr",
            {"status": "failed", "detail": "missing GITHUB_TOKEN", "branch": branch},
        )
        _record_failure_capsule(trace_id, "pr", "missing GITHUB_TOKEN")
        return {"trace_id": trace_id, "status": "pr_failed", "reason": "missing GITHUB_TOKEN"}

    remote = subprocess.run(
        ["git", "-C", repo_path, "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if remote.returncode != 0:
        reason = remote.stderr.strip() or "missing origin remote"
        write_state(trace_id, patch_base, "pr_failed", reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "pr",
            {"status": "failed", "detail": reason, "branch": branch},
        )
        _record_failure_capsule(trace_id, "pr", reason)
        return {"trace_id": trace_id, "status": "pr_failed", "reason": reason}

    full_name = _parse_repo_full_name(remote.stdout)
    allowlist = [item.strip() for item in settings.github_repo_allowlist.split(",") if item.strip()]
    if allowlist and full_name not in allowlist:
        reason = f"repo_not_allowlisted:{full_name}"
        write_state(trace_id, patch_base, "pr_failed", reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "pr",
            {"status": "failed", "detail": reason, "branch": branch},
        )
        _record_failure_capsule(trace_id, "pr", reason)
        return {"trace_id": trace_id, "status": "pr_failed", "reason": reason}

    apply_result = git_apply(repo_path, patch_path)
    if not apply_result.ok:
        write_state(trace_id, patch_base, "pr_failed", apply_result.reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "pr",
            {"status": "failed", "detail": apply_result.reason, "branch": branch},
        )
        _record_failure_capsule(trace_id, "pr", apply_result.reason)
        return {"trace_id": trace_id, "status": "pr_failed", "reason": apply_result.reason}

    commit_result = git_commit_applied(repo_path, trace_id, branch=branch)
    if not commit_result.ok:
        write_state(trace_id, patch_base, "pr_failed", commit_result.reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "pr",
            {"status": "failed", "detail": commit_result.reason, "branch": branch},
        )
        _record_failure_capsule(trace_id, "pr", commit_result.reason)
        return {"trace_id": trace_id, "status": "pr_failed", "reason": commit_result.reason}

    push = subprocess.run(
        ["git", "-C", repo_path, "push", "-u", "origin", branch],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if push.returncode != 0:
        reason = push.stderr.strip() or "git push failed"
        write_state(trace_id, patch_base, "pr_failed", reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "pr",
            {"status": "failed", "detail": reason, "branch": branch},
        )
        _record_failure_capsule(trace_id, "pr", reason)
        return {"trace_id": trace_id, "status": "pr_failed", "reason": reason}

    if not full_name or "/" not in full_name:
        reason = "unable to parse repo full name"
        write_state(trace_id, patch_base, "pr_failed", reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "pr",
            {"status": "failed", "detail": reason, "branch": branch},
        )
        _record_failure_capsule(trace_id, "pr", reason)
        return {"trace_id": trace_id, "status": "pr_failed", "reason": reason}

    owner, repo = full_name.split("/", 1)
    payload = {
        "title": f"[auto] self-update {trace_id}",
        "body": "Automated self-update patch. Human review required.",
        "head": branch,
        "base": "dev",
        "draft": True,
    }
    base_url = settings.github_api_base_url.rstrip("/")
    with httpx.Client(timeout=15.0, headers=_github_headers(token)) as client:
        response = client.post(f"{base_url}/repos/{owner}/{repo}/pulls", json=payload)
    if response.status_code >= 400:
        reason = response.text[:300] or "pr create failed"
        write_state(trace_id, patch_base, "pr_failed", reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "pr",
            {"status": "failed", "detail": reason, "branch": branch},
        )
        _record_failure_capsule(trace_id, "pr", reason)
        return {"trace_id": trace_id, "status": "pr_failed", "reason": reason}

    body = response.json()
    pr_url = str(body.get("html_url", ""))
    pr_number_raw = body.get("number")
    pr_number = int(pr_number_raw) if isinstance(pr_number_raw, int | float) else None
    detail = f"draft pr opened: {pr_url}" if pr_url else "draft pr opened"
    write_state(trace_id, patch_base, "pr_opened", detail)
    update_artifact_section(
        trace_id,
        patch_base,
        "pr",
        {
            "status": "opened",
            "detail": detail,
            "branch": branch,
            "url": pr_url,
            "number": pr_number,
        },
    )
    _emit(trace_id, "self_update.pr_opened", {"status": "opened", "url": pr_url, "branch": branch})
    return {
        "trace_id": trace_id,
        "status": "pr_opened",
        "branch": branch,
        "url": pr_url,
        "number": str(pr_number) if pr_number is not None else "",
    }


def self_update_propose(
    trace_id: str,
    repo_path: str,
    patch_text: str,
    rationale: str,
    evidence: dict[str, object] | None = None,
) -> dict[str, str]:
    patch_base = _patch_base()
    issues = validate_evidence_packet(evidence)
    if issues:
        reason = "; ".join(f"{item.field}:{item.message}" for item in issues)
        write_state(trace_id, patch_base, "rejected", reason)
        _emit(
            trace_id,
            "evidence.check",
            {
                "status": "failed",
                "reason": reason,
                "result": {
                    "status": "failed",
                    "issues": [
                        {"field": item.field, "message": item.message}
                        for item in issues
                    ],
                },
            },
        )
        _record_failure_capsule(trace_id, "propose", reason)
        return {"trace_id": trace_id, "status": "rejected", "reason": reason}

    _emit(
        trace_id,
        "evidence.check",
        {"status": "passed", "result": {"status": "passed"}},
    )
    baseline_ref = ""
    proc = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if proc.returncode == 0:
        baseline_ref = proc.stdout.strip()
    path = write_patch(trace_id, patch_text, patch_base)
    write_context(trace_id, patch_base, repo_path, rationale, baseline_ref=baseline_ref)
    artifact = default_artifact(
        trace_id=trace_id,
        rationale=rationale,
        evidence=evidence or {},
        patch_text=patch_text,
    )
    write_artifact(trace_id, patch_base, artifact)
    write_state(trace_id, patch_base, "proposed", rationale)
    related = _find_similar_failure_capsules(rationale)
    _emit(
        trace_id,
        "failure_capsule.lookup",
        {"query": rationale[:120], "matches": len(related)},
    )
    _emit(trace_id, "self_update.propose", {"status": "proposed", "patch": str(path)})
    return {"trace_id": trace_id, "status": "proposed", "patch": str(path)}


def self_update_validate(trace_id: str) -> dict[str, str]:
    patch_base = _patch_base()
    context = read_context(trace_id, patch_base)
    patch_text = read_patch(trace_id, patch_base)
    patch_path = patch_base / trace_id / "proposal.diff"
    result = validate_patch_content(patch_text)
    if not result.ok:
        write_state(trace_id, patch_base, "rejected", result.reason)
        _emit(trace_id, "self_update.validate", {"status": "rejected", "reason": result.reason})
        _record_failure_capsule(trace_id, "validate", result.reason)
        return {"trace_id": trace_id, "status": "rejected", "reason": result.reason}

    git_result = git_apply_check(context["repo_path"], patch_path)
    if not git_result.ok:
        write_state(trace_id, patch_base, "rejected", git_result.reason)
        _emit(
            trace_id,
            "self_update.validate",
            {"status": "rejected", "reason": git_result.reason},
        )
        _record_failure_capsule(trace_id, "validate", git_result.reason)
        return {"trace_id": trace_id, "status": "rejected", "reason": git_result.reason}

    replay_result = replay_patch_determinism_check(
        repo_path=context["repo_path"],
        baseline_ref=context.get("baseline_ref", ""),
        patch_path=patch_path,
        work_dir=patch_base / trace_id,
    )
    if not replay_result.ok:
        write_state(trace_id, patch_base, "rejected", replay_result.reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "verification",
            {
                "status": "rejected",
                "detail": replay_result.reason,
                "replay": {
                    "status": "failed",
                    "detail": replay_result.reason,
                    "tree_hash": replay_result.tree_hash,
                    "changed_files": replay_result.changed_files,
                },
            },
        )
        _emit(
            trace_id,
            "self_update.validate",
            {
                "status": "rejected",
                "reason": replay_result.reason,
                "result": {"status": "rejected"},
            },
        )
        _record_failure_capsule(trace_id, "validate", replay_result.reason)
        return {"trace_id": trace_id, "status": "rejected", "reason": replay_result.reason}

    update_artifact_section(
        trace_id,
        patch_base,
        "verification",
        {
            "status": "validated",
            "detail": git_result.reason,
            "replay": {
                "status": "passed",
                "detail": replay_result.reason,
                "tree_hash": replay_result.tree_hash,
                "changed_files": replay_result.changed_files,
            },
        },
    )
    write_state(trace_id, patch_base, "validated", git_result.reason)
    _emit(
        trace_id,
        "self_update.validate",
        {
            "status": "validated",
            "result": {
                "status": "validated",
                "replay_tree_hash": replay_result.tree_hash,
            },
        },
    )
    return {"trace_id": trace_id, "status": "validated"}


def self_update_test(trace_id: str) -> dict[str, str]:
    settings = get_settings()
    patch_base = _patch_base()
    state = read_state(trace_id, patch_base)
    if state["state"] != "validated":
        return {
            "trace_id": trace_id,
            "status": "rejected",
            "reason": f"invalid state transition: {state['state']} -> tested",
        }

    patch_text = read_patch(trace_id, patch_base)
    patch_path = patch_base / trace_id / "proposal.diff"
    context = read_context(trace_id, patch_base)
    changed_files = changed_files_from_patch(patch_text)
    if touches_critical_paths(changed_files, _critical_patterns()) and not includes_test_changes(
        changed_files
    ):
        reason = "critical module change requires tests/ updates"
        write_state(trace_id, patch_base, "test_failed", reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "tests",
            {"result": "failed", "detail": reason, "changed_files": changed_files},
        )
        _emit(trace_id, "self_update.test", {"status": "failed", "reason": reason})
        _record_failure_capsule(trace_id, "test", reason)
        return {"trace_id": trace_id, "status": "failed", "reason": reason}

    result = evaluate_test_gate(patch_text)
    if not result.ok:
        write_state(trace_id, patch_base, "test_failed", result.reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "tests",
            {"result": "failed", "detail": result.reason, "changed_files": changed_files},
        )
        _emit(trace_id, "self_update.test", {"status": "failed", "reason": result.reason})
        _record_failure_capsule(trace_id, "test", result.reason)
        return {"trace_id": trace_id, "status": "failed", "reason": result.reason}

    smoke_result = run_smoke_gate(
        repo_path=context["repo_path"],
        patch_path=patch_path,
        work_dir=patch_base / trace_id,
        profile=settings.selfupdate_smoke_profile,
    )
    if not smoke_result.ok:
        write_state(trace_id, patch_base, "test_failed", smoke_result.reason)
        update_artifact_section(
            trace_id,
            patch_base,
            "tests",
            {"result": "failed", "detail": smoke_result.reason, "changed_files": changed_files},
        )
        _emit(trace_id, "self_update.test", {"status": "failed", "reason": smoke_result.reason})
        _record_failure_capsule(trace_id, "test", smoke_result.reason)
        return {"trace_id": trace_id, "status": "failed", "reason": smoke_result.reason}

    write_state(trace_id, patch_base, "tested", smoke_result.reason)
    update_artifact_section(
        trace_id,
        patch_base,
        "tests",
        {"result": "passed", "detail": smoke_result.reason, "changed_files": changed_files},
    )
    _emit(trace_id, "self_update.test", {"status": "passed"})

    if int(settings.selfupdate_pr_autoraise) == 1:
        return self_update_open_pr(trace_id)

    return {"trace_id": trace_id, "status": "passed"}


def self_update_apply(trace_id: str) -> dict[str, str]:
    settings = get_settings()
    patch_base = _patch_base()
    with get_conn() as conn:
        if get_system_state(conn)["lockdown"] == 1:
            return {
                "trace_id": trace_id,
                "status": "rejected",
                "reason": "lockdown active",
            }
    state = read_state(trace_id, patch_base)
    phase = state["state"]
    if int(settings.user_simulator_enabled) == 1 and settings.user_simulator_required_pack.strip():
        from jarvis.tasks.story_runner import latest_story_pack_status

        pack = settings.user_simulator_required_pack.strip()
        if latest_story_pack_status(pack) != "passed":
            return {
                "trace_id": trace_id,
                "status": "rejected",
                "reason": f"required story pack not passing: {pack}",
            }
    if settings.app_env == "prod":
        if phase in {"tested", "pr_opened"}:
            with get_conn() as conn:
                approved = consume_approval(
                    conn,
                    "selfupdate.apply",
                    target_ref=trace_id,
                    trace_id=trace_id,
                )
            if not approved:
                return {
                    "trace_id": trace_id,
                    "status": "rejected",
                    "reason": "missing admin approval: selfupdate.apply for trace_id",
                }
            write_state(trace_id, patch_base, "approved", "admin approval consumed")
            _emit(trace_id, "self_update.approve", {"status": "approved"})
            phase = "approved"
        if phase != "approved":
            return {
                "trace_id": trace_id,
                "status": "rejected",
                "reason": f"invalid state transition: {state['state']} -> applied",
            }
    elif phase not in {"tested", "approved", "pr_opened"}:
        return {
            "trace_id": trace_id,
            "status": "rejected",
            "reason": f"invalid state transition: {state['state']} -> applied",
        }

    context = read_context(trace_id, patch_base)
    patch_path = patch_base / trace_id / "proposal.diff"
    apply_result = git_apply(context["repo_path"], patch_path)
    if not apply_result.ok:
        write_state(trace_id, patch_base, "apply_failed", apply_result.reason)
        _emit(
            trace_id,
            "self_update.apply",
            {"status": "apply_failed", "reason": apply_result.reason},
        )
        _record_failure_capsule(trace_id, "apply", apply_result.reason)
        return {"trace_id": trace_id, "status": "apply_failed", "reason": apply_result.reason}
    commit_result = git_commit_applied(context["repo_path"], trace_id)
    if not commit_result.ok:
        write_state(trace_id, patch_base, "apply_failed", commit_result.reason)
        _emit(
            trace_id,
            "self_update.apply",
            {"status": "apply_failed", "reason": commit_result.reason},
        )
        _record_failure_capsule(trace_id, "apply", commit_result.reason)
        return {"trace_id": trace_id, "status": "apply_failed", "reason": commit_result.reason}

    marker = mark_applied(trace_id, patch_base)
    write_state(trace_id, patch_base, "applied", commit_result.reason)
    update_artifact_section(
        trace_id,
        patch_base,
        "verification",
        {"status": "applied", "detail": commit_result.reason},
    )
    _emit(
        trace_id,
        "self_update.apply",
        {"status": "applied", "marker": str(marker), "detail": commit_result.reason},
    )
    if not enqueue_restart(trace_id):
        _ = system_restart(trace_id)
    if not _readyz_ok(settings.selfupdate_readyz_url, settings.selfupdate_readyz_attempts):
        rollback = self_update_rollback(trace_id, "readyz failed after apply")
        return {
            "trace_id": trace_id,
            "status": "rolled_back",
            "marker": str(marker),
            "rollback_marker": rollback["marker"],
        }
    verified = mark_verified(trace_id, patch_base)
    write_state(trace_id, patch_base, "verified", "readyz passed after apply")
    update_artifact_section(
        trace_id,
        patch_base,
        "verification",
        {"status": "verified", "detail": "readyz passed after apply"},
    )
    _emit(trace_id, "self_update.verified", {"status": "verified", "marker": str(verified)})
    return {
        "trace_id": trace_id,
        "status": "verified",
        "marker": str(marker),
        "verified_marker": str(verified),
    }


def self_update_rollback(trace_id: str, reason: str = "auto rollback") -> dict[str, str]:
    settings = get_settings()
    patch_base = _patch_base()
    context = read_context(trace_id, patch_base)
    repo_path = context.get("repo_path", "")
    baseline_ref = context.get("baseline_ref", "")
    recovery = "noop"
    if repo_path and baseline_ref:
        checkout = subprocess.run(
            ["git", "-C", repo_path, "checkout", "--detach", baseline_ref],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if checkout.returncode == 0:
            reset = subprocess.run(
                ["git", "-C", repo_path, "reset", "--hard", baseline_ref],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            recovery = "git_ref_restored" if reset.returncode == 0 else "git_reset_failed"
        else:
            recovery = "git_checkout_failed"
    marker = mark_rollback(trace_id, patch_base, reason)
    write_state(trace_id, patch_base, "rolled_back", reason)
    update_artifact_section(
        trace_id,
        patch_base,
        "rollback",
        {"status": "rolled_back", "detail": reason, "recovery": recovery},
    )
    with get_conn() as conn:
        previous = get_system_state(conn)
        _ = register_rollback(
            conn,
            threshold_count=settings.lockdown_rollback_threshold,
            window_minutes=settings.lockdown_rollback_window_minutes,
        )
        current = get_system_state(conn)
        if previous["lockdown"] == 0 and current["lockdown"] == 1:
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=None,
                    event_type="lockdown.triggered",
                    component="selfupdate",
                    actor_type="system",
                    actor_id="selfupdate",
                    payload_json='{"reason":"rollback_burst"}',
                    payload_redacted_json='{"reason":"rollback_burst"}',
                ),
            )
    _emit(
        trace_id,
        "self_update.rollback",
        {"status": "rolled_back", "reason": reason, "recovery": recovery},
    )
    _record_failure_capsule(trace_id, "rollback", reason)
    return {
        "trace_id": trace_id,
        "status": "rolled_back",
        "marker": str(marker),
        "recovery": recovery,
    }
