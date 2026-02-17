"""Self-update Celery tasks."""

import json
import subprocess
import time
from pathlib import Path

import httpx

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import consume_approval, get_system_state, register_rollback
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.selfupdate.pipeline import (
    evaluate_test_gate,
    git_apply,
    git_apply_check,
    git_commit_applied,
    mark_applied,
    mark_rollback,
    mark_verified,
    read_context,
    read_patch,
    read_state,
    run_smoke_gate,
    validate_patch_content,
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


def _emit(trace_id: str, event_type: str, payload: dict[str, str]) -> None:
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
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
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


def self_update_propose(
    trace_id: str, repo_path: str, patch_text: str, rationale: str
) -> dict[str, str]:
    patch_base = _patch_base()
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
    write_state(trace_id, patch_base, "proposed", rationale)
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
        return {"trace_id": trace_id, "status": "rejected", "reason": result.reason}

    git_result = git_apply_check(context["repo_path"], patch_path)
    if not git_result.ok:
        write_state(trace_id, patch_base, "rejected", git_result.reason)
        _emit(
            trace_id,
            "self_update.validate",
            {"status": "rejected", "reason": git_result.reason},
        )
        return {"trace_id": trace_id, "status": "rejected", "reason": git_result.reason}

    write_state(trace_id, patch_base, "validated", git_result.reason)
    _emit(trace_id, "self_update.validate", {"status": "validated"})
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
    result = evaluate_test_gate(patch_text)
    if not result.ok:
        write_state(trace_id, patch_base, "test_failed", result.reason)
        _emit(trace_id, "self_update.test", {"status": "failed", "reason": result.reason})
        return {"trace_id": trace_id, "status": "failed", "reason": result.reason}

    smoke_result = run_smoke_gate(
        repo_path=context["repo_path"],
        patch_path=patch_path,
        work_dir=patch_base / trace_id,
        profile=settings.selfupdate_smoke_profile,
    )
    if not smoke_result.ok:
        write_state(trace_id, patch_base, "test_failed", smoke_result.reason)
        _emit(trace_id, "self_update.test", {"status": "failed", "reason": smoke_result.reason})
        return {"trace_id": trace_id, "status": "failed", "reason": smoke_result.reason}

    write_state(trace_id, patch_base, "tested", smoke_result.reason)
    _emit(trace_id, "self_update.test", {"status": "passed"})
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
    if settings.app_env == "prod":
        if phase == "tested":
            with get_conn() as conn:
                approved = consume_approval(conn, "selfupdate.apply")
            if not approved:
                return {
                    "trace_id": trace_id,
                    "status": "rejected",
                    "reason": "missing admin approval: selfupdate.apply",
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
    elif phase not in {"tested", "approved"}:
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
        return {"trace_id": trace_id, "status": "apply_failed", "reason": apply_result.reason}
    commit_result = git_commit_applied(context["repo_path"], trace_id)
    if not commit_result.ok:
        write_state(trace_id, patch_base, "apply_failed", commit_result.reason)
        _emit(
            trace_id,
            "self_update.apply",
            {"status": "apply_failed", "reason": commit_result.reason},
        )
        return {"trace_id": trace_id, "status": "apply_failed", "reason": commit_result.reason}

    marker = mark_applied(trace_id, patch_base)
    write_state(trace_id, patch_base, "applied", commit_result.reason)
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
    return {
        "trace_id": trace_id,
        "status": "rolled_back",
        "marker": str(marker),
        "recovery": recovery,
    }
