"""Self-update Celery tasks."""

import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    consume_approval,
    get_selfupdate_fitness_gate_config,
    get_system_guardrails,
    get_system_state,
    insert_guardrail_trip,
    insert_selfupdate_check,
    insert_selfupdate_transition,
    latest_system_fitness_snapshot,
    list_failure_remediations,
    now_iso,
    register_rollback,
    trigger_lockdown,
    update_selfupdate_run_state,
    upsert_selfupdate_run,
)
from jarvis.events.envelope import with_action_envelope
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.selfupdate.contracts import (
    default_artifact,
    validate_evidence_context,
    validate_evidence_packet,
)
from jarvis.selfupdate.pipeline import (
    changed_files_from_patch,
    execute_test_plan,
    git_apply,
    git_apply_check,
    git_commit_applied,
    includes_test_changes,
    mark_applied,
    mark_rollback,
    mark_verified,
    read_artifact,
    read_context,
    read_patch,
    read_state,
    replay_patch_determinism_check,
    run_smoke_gate,
    touches_critical_paths,
    update_artifact_section,
    validate_evidence_refs_in_repo,
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


def _record_check(
    trace_id: str,
    *,
    check_type: str,
    status: str,
    detail: str,
    payload: dict[str, object] | None = None,
) -> None:
    with get_conn() as conn:
        insert_selfupdate_check(
            conn,
            trace_id=trace_id,
            check_type=check_type,
            status=status,
            detail=detail[:1000],
            payload=payload or {},
        )


def _record_transition(
    trace_id: str,
    *,
    from_state: str,
    to_state: str,
    reason: str,
) -> None:
    with get_conn() as conn:
        insert_selfupdate_transition(
            conn,
            trace_id=trace_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason[:1000],
        )
        update_selfupdate_run_state(conn, trace_id=trace_id, state=to_state)


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


def _fitness_gate_thresholds() -> dict[str, float | int]:
    settings = get_settings()
    thresholds: dict[str, float | int] = {
        "max_snapshot_age_minutes": max(1, int(settings.selfupdate_fitness_max_age_minutes)),
        "min_build_success_rate": max(0.0, float(settings.selfupdate_min_build_success_rate)),
        "max_regression_frequency": max(0.0, float(settings.selfupdate_max_regression_frequency)),
        "max_rollback_frequency": max(0, int(settings.selfupdate_max_rollback_frequency)),
    }
    with get_conn() as conn:
        stored = get_selfupdate_fitness_gate_config(conn)
    if stored is None:
        return thresholds
    thresholds["max_snapshot_age_minutes"] = int(stored["max_snapshot_age_minutes"])
    thresholds["min_build_success_rate"] = float(stored["min_build_success_rate"])
    thresholds["max_regression_frequency"] = float(stored["max_regression_frequency"])
    thresholds["max_rollback_frequency"] = int(stored["max_rollback_frequency"])
    return thresholds


def _evaluate_fitness_gate() -> tuple[bool, list[str], dict[str, object]]:
    thresholds = _fitness_gate_thresholds()
    snapshot: dict[str, object] | None
    with get_conn() as conn:
        snapshot = latest_system_fitness_snapshot(conn)
    if snapshot is None:
        detail = {
            "thresholds": thresholds,
            "snapshot": None,
            "reasons": ["missing_system_fitness_snapshot"],
        }
        return False, ["missing_system_fitness_snapshot"], detail

    reasons: list[str] = []
    metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else {}
    metrics_dict = metrics if isinstance(metrics, dict) else {}
    created_at = str(snapshot.get("created_at", "")).strip()
    snapshot_age_minutes = 10**9
    if created_at:
        try:
            then = datetime.fromisoformat(created_at)
            snapshot_age_minutes = int((datetime.now(UTC) - then).total_seconds() // 60)
        except ValueError:
            reasons.append("invalid_snapshot_timestamp")
    max_age = int(thresholds["max_snapshot_age_minutes"])
    if snapshot_age_minutes > max_age:
        reasons.append(f"stale_snapshot:{snapshot_age_minutes}>{max_age}")

    build_success = float(metrics_dict.get("selfupdate_success_rate", 0.0) or 0.0)
    min_build = float(thresholds["min_build_success_rate"])
    if build_success < min_build:
        reasons.append(f"build_success_rate:{build_success:.4f}<{min_build:.4f}")

    regression = float(metrics_dict.get("failure_capsule_recurrence_rate", 0.0) or 0.0)
    max_regression = float(thresholds["max_regression_frequency"])
    if regression > max_regression:
        reasons.append(f"regression_frequency:{regression:.4f}>{max_regression:.4f}")

    rollback_freq = int(metrics_dict.get("rollback_frequency", 0) or 0)
    max_rollbacks = int(thresholds["max_rollback_frequency"])
    if rollback_freq > max_rollbacks:
        reasons.append(f"rollback_frequency:{rollback_freq}>{max_rollbacks}")

    detail = {
        "thresholds": thresholds,
        "snapshot": snapshot,
        "snapshot_age_minutes": snapshot_age_minutes,
        "metrics": metrics_dict,
        "reasons": reasons,
    }
    return len(reasons) == 0, reasons, detail


def _lookup_remediation_candidates(
    phase: str, reason: str, limit: int = 3
) -> list[dict[str, object]]:
    query = reason.strip().lower()[:80]
    if not query:
        return []
    with get_conn() as conn:
        patterns = conn.execute(
            (
                "SELECT id FROM failure_patterns WHERE phase=? "
                "AND lower(latest_reason) LIKE ? "
                "ORDER BY count DESC, last_seen_at DESC LIMIT 5"
            ),
            (phase, f"%{query}%"),
        ).fetchall()
        out: list[dict[str, object]] = []
        for pattern in patterns:
            out.extend(list_failure_remediations(conn, str(pattern["id"]), limit=limit))
            if len(out) >= limit:
                break
    return out[:limit]


def _record_failure_capsule(trace_id: str, phase: str, reason: str) -> None:
    capsule_id = f"fcp_{new_id('evt')[4:]}"
    remediations = _lookup_remediation_candidates(phase, reason, limit=3)
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
            "remediations": remediations,
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


def _risk_score_for_patch(changed_files: list[str]) -> int:
    if not changed_files:
        return 0
    score = min(10, len(changed_files) // 8 + 1)
    if touches_critical_paths(changed_files, _critical_patterns()):
        score = min(10, score + 4)
    if includes_test_changes(changed_files):
        score = max(0, score - 1)
    return score


def _guardrail_check(
    trace_id: str, *, changed_files: list[str], check_pr_count: bool
) -> str | None:
    with get_conn() as conn:
        guardrails = get_system_guardrails(conn)
        today_prefix = now_iso()[:10]

        if len(changed_files) > int(guardrails["max_files_per_patch"]):
            insert_guardrail_trip(
                conn,
                guardrail_key="max_files_per_patch",
                actual_value=len(changed_files),
                threshold_value=int(guardrails["max_files_per_patch"]),
                trace_id=trace_id,
                detail={"changed_files": changed_files[:50]},
            )
            trigger_lockdown(conn, "guardrail.max_files_per_patch")
            return "guardrail.max_files_per_patch"

        risk_score = _risk_score_for_patch(changed_files)
        if risk_score > int(guardrails["max_risk_score"]):
            insert_guardrail_trip(
                conn,
                guardrail_key="max_risk_score",
                actual_value=risk_score,
                threshold_value=int(guardrails["max_risk_score"]),
                trace_id=trace_id,
                detail={"changed_files": changed_files[:50]},
            )
            trigger_lockdown(conn, "guardrail.max_risk_score")
            return "guardrail.max_risk_score"

        attempts_row = conn.execute(
            "SELECT COUNT(*) AS n FROM selfupdate_runs WHERE created_at LIKE ?",
            (f"{today_prefix}%",),
        ).fetchone()
        attempts = int(attempts_row["n"]) if attempts_row is not None else 0
        if attempts >= int(guardrails["max_patch_attempts_per_day"]):
            insert_guardrail_trip(
                conn,
                guardrail_key="max_patch_attempts_per_day",
                actual_value=attempts,
                threshold_value=int(guardrails["max_patch_attempts_per_day"]),
                trace_id=trace_id,
                detail={},
            )
            trigger_lockdown(conn, "guardrail.max_patch_attempts_per_day")
            return "guardrail.max_patch_attempts_per_day"

        if check_pr_count:
            pr_row = conn.execute(
                "SELECT COUNT(*) AS n FROM events "
                "WHERE event_type='self_update.pr_opened' AND created_at LIKE ?",
                (f"{today_prefix}%",),
            ).fetchone()
            pr_count = int(pr_row["n"]) if pr_row is not None else 0
            if pr_count >= int(guardrails["max_prs_per_day"]):
                insert_guardrail_trip(
                    conn,
                    guardrail_key="max_prs_per_day",
                    actual_value=pr_count,
                    threshold_value=int(guardrails["max_prs_per_day"]),
                    trace_id=trace_id,
                    detail={},
                )
                trigger_lockdown(conn, "guardrail.max_prs_per_day")
                return "guardrail.max_prs_per_day"
    return None


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
    changed_files = changed_files_from_patch(read_patch(trace_id, patch_base))
    guardrail_reason = _guardrail_check(trace_id, changed_files=changed_files, check_pr_count=True)
    if guardrail_reason:
        write_state(trace_id, patch_base, "pr_failed", guardrail_reason)
        _record_transition(
            trace_id,
            from_state="tested",
            to_state="pr_failed",
            reason=guardrail_reason,
        )
        _record_check(
            trace_id,
            check_type="guardrail",
            status="failed",
            detail=guardrail_reason,
        )
        _record_failure_capsule(trace_id, "pr", guardrail_reason)
        return {"trace_id": trace_id, "status": "pr_failed", "reason": guardrail_reason}

    token = settings.github_token.strip()
    if not token:
        write_state(trace_id, patch_base, "pr_failed", "missing GITHUB_TOKEN")
        _record_transition(
            trace_id,
            from_state="tested",
            to_state="pr_failed",
            reason="missing GITHUB_TOKEN",
        )
        _record_check(
            trace_id,
            check_type="pr.open",
            status="failed",
            detail="missing GITHUB_TOKEN",
        )
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
        _record_transition(
            trace_id,
            from_state="tested",
            to_state="pr_failed",
            reason=reason,
        )
        _record_check(
            trace_id,
            check_type="pr.open",
            status="failed",
            detail=reason,
        )
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
        _record_transition(
            trace_id,
            from_state="tested",
            to_state="pr_failed",
            reason=reason,
        )
        _record_check(
            trace_id,
            check_type="pr.open",
            status="failed",
            detail=reason,
        )
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
        _record_transition(
            trace_id,
            from_state="tested",
            to_state="pr_failed",
            reason=apply_result.reason,
        )
        _record_check(
            trace_id,
            check_type="pr.open",
            status="failed",
            detail=apply_result.reason,
        )
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
        _record_transition(
            trace_id,
            from_state="tested",
            to_state="pr_failed",
            reason=commit_result.reason,
        )
        _record_check(
            trace_id,
            check_type="pr.open",
            status="failed",
            detail=commit_result.reason,
        )
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
        _record_transition(
            trace_id,
            from_state="tested",
            to_state="pr_failed",
            reason=reason,
        )
        _record_check(
            trace_id,
            check_type="pr.open",
            status="failed",
            detail=reason,
        )
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
        _record_transition(
            trace_id,
            from_state="tested",
            to_state="pr_failed",
            reason=reason,
        )
        _record_check(
            trace_id,
            check_type="pr.open",
            status="failed",
            detail=reason,
        )
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
        _record_transition(
            trace_id,
            from_state="tested",
            to_state="pr_failed",
            reason=reason,
        )
        _record_check(
            trace_id,
            check_type="pr.open",
            status="failed",
            detail=reason,
        )
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
    _record_transition(
        trace_id,
        from_state="tested",
        to_state="pr_opened",
        reason=detail,
    )
    _record_check(
        trace_id,
        check_type="pr.open",
        status="passed",
        detail=detail,
        payload={"url": pr_url, "branch": branch},
    )
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
    changed_files = changed_files_from_patch(patch_text)
    guardrail_reason = _guardrail_check(trace_id, changed_files=changed_files, check_pr_count=False)
    if guardrail_reason:
        write_state(trace_id, patch_base, "rejected", guardrail_reason)
        _record_check(
            trace_id,
            check_type="guardrail",
            status="failed",
            detail=guardrail_reason,
        )
        _record_transition(
            trace_id,
            from_state="new",
            to_state="rejected",
            reason=guardrail_reason,
        )
        _record_failure_capsule(trace_id, "propose", guardrail_reason)
        return {"trace_id": trace_id, "status": "rejected", "reason": guardrail_reason}
    with get_conn() as conn:
        upsert_selfupdate_run(
            conn,
            trace_id=trace_id,
            state="new",
            baseline_ref="",
            repo_path=repo_path,
            rationale=rationale,
            changed_files=changed_files,
        )
    issues = validate_evidence_packet(evidence)
    issues.extend(
        validate_evidence_context(
            evidence,
            changed_files=changed_files,
            critical_change=touches_critical_paths(changed_files, _critical_patterns()),
        )
    )
    if issues:
        reason = "; ".join(f"{item.field}:{item.message}" for item in issues)
        write_state(trace_id, patch_base, "rejected", reason)
        _record_check(
            trace_id,
            check_type="evidence.contract",
            status="failed",
            detail=reason,
            payload={
                "issues": [{"field": item.field, "message": item.message} for item in issues],
            },
        )
        _record_transition(
            trace_id,
            from_state="new",
            to_state="rejected",
            reason=reason,
        )
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
    repo_evidence = validate_evidence_refs_in_repo(
        repo_path=repo_path,
        baseline_ref=baseline_ref,
        file_refs=[
            str(item)
            for item in (evidence or {}).get("file_refs", [])
            if isinstance(item, str)
        ],
        line_refs=[
            str(item)
            for item in (evidence or {}).get("line_refs", [])
            if isinstance(item, str)
        ],
        changed_files=changed_files,
    )
    if not repo_evidence.ok:
        write_state(trace_id, patch_base, "rejected", repo_evidence.reason)
        _record_check(
            trace_id,
            check_type="evidence.repo_refs",
            status="failed",
            detail=repo_evidence.reason,
            payload={"changed_files": changed_files},
        )
        _record_transition(
            trace_id,
            from_state="new",
            to_state="rejected",
            reason=repo_evidence.reason,
        )
        _emit(
            trace_id,
            "evidence.check",
            {
                "status": "failed",
                "reason": repo_evidence.reason,
                "result": {"status": "failed"},
            },
        )
        _record_failure_capsule(trace_id, "propose", repo_evidence.reason)
        return {"trace_id": trace_id, "status": "rejected", "reason": repo_evidence.reason}

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
    with get_conn() as conn:
        upsert_selfupdate_run(
            conn,
            trace_id=trace_id,
            state="proposed",
            baseline_ref=baseline_ref,
            repo_path=repo_path,
            rationale=rationale,
            changed_files=changed_files,
        )
    _record_check(
        trace_id,
        check_type="evidence.contract",
        status="passed",
        detail="evidence contract validated",
        payload={"changed_files": changed_files},
    )
    _record_check(
        trace_id,
        check_type="evidence.repo_refs",
        status="passed",
        detail=repo_evidence.reason,
        payload={"changed_files": changed_files},
    )
    _record_transition(
        trace_id,
        from_state="new",
        to_state="proposed",
        reason=rationale,
    )
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
        _record_check(
            trace_id,
            check_type="patch.content",
            status="failed",
            detail=result.reason,
        )
        _record_transition(
            trace_id,
            from_state="proposed",
            to_state="rejected",
            reason=result.reason,
        )
        _emit(trace_id, "self_update.validate", {"status": "rejected", "reason": result.reason})
        _record_failure_capsule(trace_id, "validate", result.reason)
        return {"trace_id": trace_id, "status": "rejected", "reason": result.reason}
    _record_check(
        trace_id,
        check_type="patch.content",
        status="passed",
        detail=result.reason,
    )

    git_result = git_apply_check(context["repo_path"], patch_path)
    if not git_result.ok:
        write_state(trace_id, patch_base, "rejected", git_result.reason)
        _record_check(
            trace_id,
            check_type="patch.apply_check",
            status="failed",
            detail=git_result.reason,
        )
        _record_transition(
            trace_id,
            from_state="proposed",
            to_state="rejected",
            reason=git_result.reason,
        )
        _emit(
            trace_id,
            "self_update.validate",
            {"status": "rejected", "reason": git_result.reason},
        )
        _record_failure_capsule(trace_id, "validate", git_result.reason)
        return {"trace_id": trace_id, "status": "rejected", "reason": git_result.reason}
    _record_check(
        trace_id,
        check_type="patch.apply_check",
        status="passed",
        detail=git_result.reason,
    )

    replay_result = replay_patch_determinism_check(
        repo_path=context["repo_path"],
        baseline_ref=context.get("baseline_ref", ""),
        patch_path=patch_path,
        work_dir=patch_base / trace_id,
    )
    if not replay_result.ok:
        write_state(trace_id, patch_base, "rejected", replay_result.reason)
        _record_check(
            trace_id,
            check_type="patch.replay",
            status="failed",
            detail=replay_result.reason,
            payload={
                "tree_hash": replay_result.tree_hash,
                "changed_files": replay_result.changed_files,
            },
        )
        _record_transition(
            trace_id,
            from_state="proposed",
            to_state="rejected",
            reason=replay_result.reason,
        )
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
    _record_check(
        trace_id,
        check_type="patch.replay",
        status="passed",
        detail=replay_result.reason,
        payload={
            "tree_hash": replay_result.tree_hash,
            "changed_files": replay_result.changed_files,
        },
    )

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
    _record_transition(
        trace_id,
        from_state="proposed",
        to_state="validated",
        reason=git_result.reason,
    )
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
    artifact = read_artifact(trace_id, patch_base)
    context = read_context(trace_id, patch_base)
    changed_files = changed_files_from_patch(patch_text)
    if touches_critical_paths(changed_files, _critical_patterns()) and not includes_test_changes(
        changed_files
    ):
        reason = "critical module change requires tests/ updates"
        write_state(trace_id, patch_base, "test_failed", reason)
        _record_check(
            trace_id,
            check_type="tests.critical_path",
            status="failed",
            detail=reason,
            payload={"changed_files": changed_files},
        )
        _record_transition(
            trace_id,
            from_state="validated",
            to_state="test_failed",
            reason=reason,
        )
        update_artifact_section(
            trace_id,
            patch_base,
            "tests",
            {"result": "failed", "detail": reason, "changed_files": changed_files},
        )
        _emit(trace_id, "self_update.test", {"status": "failed", "reason": reason})
        _record_failure_capsule(trace_id, "test", reason)
        return {"trace_id": trace_id, "status": "failed", "reason": reason}
    _record_check(
        trace_id,
        check_type="tests.critical_path",
        status="passed",
        detail="critical path requirements satisfied",
        payload={"changed_files": changed_files},
    )

    tests_section = artifact.get("tests") if isinstance(artifact, dict) else {}
    test_plan = (
        tests_section.get("commands")
        if isinstance(tests_section, dict)
        else []
    )
    commands = [
        str(item).strip()
        for item in test_plan
        if isinstance(item, str) and str(item).strip()
    ]
    if not commands:
        reason = "artifact.tests.commands is empty"
        write_state(trace_id, patch_base, "test_failed", reason)
        _record_check(
            trace_id,
            check_type="tests.plan",
            status="failed",
            detail=reason,
        )
        _record_transition(
            trace_id,
            from_state="validated",
            to_state="test_failed",
            reason=reason,
        )
        update_artifact_section(
            trace_id,
            patch_base,
            "tests",
            {"result": "failed", "detail": reason, "changed_files": changed_files},
        )
        _emit(trace_id, "self_update.test", {"status": "failed", "reason": reason})
        _record_failure_capsule(trace_id, "test", reason)
        return {"trace_id": trace_id, "status": "failed", "reason": reason}

    plan_result, command_results = execute_test_plan(
        repo_path=context["repo_path"],
        patch_path=patch_path,
        work_dir=patch_base / trace_id,
        commands=commands,
    )
    if not plan_result.ok:
        write_state(trace_id, patch_base, "test_failed", plan_result.reason)
        _record_check(
            trace_id,
            check_type="tests.plan",
            status="failed",
            detail=plan_result.reason,
            payload={
                "commands": [
                    {
                        "command": item.command,
                        "ok": item.ok,
                        "exit_code": item.exit_code,
                        "duration_ms": item.duration_ms,
                    }
                    for item in command_results
                ],
            },
        )
        _record_transition(
            trace_id,
            from_state="validated",
            to_state="test_failed",
            reason=plan_result.reason,
        )
        update_artifact_section(
            trace_id,
            patch_base,
            "tests",
            {
                "result": "failed",
                "detail": plan_result.reason,
                "changed_files": changed_files,
                "command_results": [
                    {
                        "command": item.command,
                        "ok": item.ok,
                        "exit_code": item.exit_code,
                        "duration_ms": item.duration_ms,
                        "stdout": item.stdout,
                        "stderr": item.stderr,
                    }
                    for item in command_results
                ],
            },
        )
        _emit(trace_id, "self_update.test", {"status": "failed", "reason": plan_result.reason})
        _record_failure_capsule(trace_id, "test", plan_result.reason)
        return {"trace_id": trace_id, "status": "failed", "reason": plan_result.reason}
    _record_check(
        trace_id,
        check_type="tests.plan",
        status="passed",
        detail=plan_result.reason,
        payload={
            "commands": [
                {
                    "command": item.command,
                    "ok": item.ok,
                    "exit_code": item.exit_code,
                    "duration_ms": item.duration_ms,
                }
                for item in command_results
            ],
        },
    )

    smoke_result = run_smoke_gate(
        repo_path=context["repo_path"],
        patch_path=patch_path,
        work_dir=patch_base / trace_id,
        profile=settings.selfupdate_smoke_profile,
    )
    if not smoke_result.ok:
        write_state(trace_id, patch_base, "test_failed", smoke_result.reason)
        _record_check(
            trace_id,
            check_type="tests.smoke",
            status="failed",
            detail=smoke_result.reason,
        )
        _record_transition(
            trace_id,
            from_state="validated",
            to_state="test_failed",
            reason=smoke_result.reason,
        )
        update_artifact_section(
            trace_id,
            patch_base,
            "tests",
            {"result": "failed", "detail": smoke_result.reason, "changed_files": changed_files},
        )
        _emit(trace_id, "self_update.test", {"status": "failed", "reason": smoke_result.reason})
        _record_failure_capsule(trace_id, "test", smoke_result.reason)
        return {"trace_id": trace_id, "status": "failed", "reason": smoke_result.reason}
    _record_check(
        trace_id,
        check_type="tests.smoke",
        status="passed",
        detail=smoke_result.reason,
    )

    write_state(trace_id, patch_base, "tested", smoke_result.reason)
    _record_transition(
        trace_id,
        from_state="validated",
        to_state="tested",
        reason=smoke_result.reason,
    )
    update_artifact_section(
        trace_id,
        patch_base,
        "tests",
        {
            "result": "passed",
            "detail": smoke_result.reason,
            "changed_files": changed_files,
            "command_results": [
                {
                    "command": item.command,
                    "ok": item.ok,
                    "exit_code": item.exit_code,
                    "duration_ms": item.duration_ms,
                    "stdout": item.stdout,
                    "stderr": item.stderr,
                }
                for item in command_results
            ],
        },
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
            _record_check(
                trace_id,
                check_type="apply.lockdown",
                status="failed",
                detail="lockdown active",
            )
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
            _record_check(
                trace_id,
                check_type="apply.story_pack",
                status="failed",
                detail=f"required story pack not passing: {pack}",
            )
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
                _record_check(
                    trace_id,
                    check_type="apply.approval",
                    status="failed",
                    detail="missing admin approval",
                )
                return {
                    "trace_id": trace_id,
                    "status": "rejected",
                    "reason": "missing admin approval: selfupdate.apply for trace_id",
                }
            write_state(trace_id, patch_base, "approved", "admin approval consumed")
            _record_transition(
                trace_id,
                from_state=state["state"],
                to_state="approved",
                reason="admin approval consumed",
            )
            _record_check(
                trace_id,
                check_type="apply.approval",
                status="passed",
                detail="admin approval consumed",
            )
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

    gate_ok, gate_reasons, gate_detail = _evaluate_fitness_gate()
    gate_mode = settings.selfupdate_fitness_gate_mode.strip().lower()
    if not gate_ok and gate_mode == "enforce":
        detail = "; ".join(gate_reasons) if gate_reasons else "fitness gate failed"
        _record_check(
            trace_id,
            check_type="apply.fitness_gate",
            status="failed",
            detail=detail,
            payload=gate_detail,
        )
        update_artifact_section(
            trace_id,
            patch_base,
            "verification",
            {
                "status": "blocked",
                "detail": detail,
                "fitness_gate": {
                    "status": "failed",
                    "blocking_reasons": gate_reasons,
                    **gate_detail,
                },
            },
        )
        return {
            "trace_id": trace_id,
            "status": "rejected",
            "reason": f"fitness gate blocked apply: {detail}",
        }
    if not gate_ok:
        _record_check(
            trace_id,
            check_type="apply.fitness_gate",
            status="warning",
            detail="; ".join(gate_reasons) if gate_reasons else "fitness gate warning",
            payload=gate_detail,
        )
    else:
        _record_check(
            trace_id,
            check_type="apply.fitness_gate",
            status="passed",
            detail="fitness gate passed",
            payload=gate_detail,
        )
    update_artifact_section(
        trace_id,
        patch_base,
        "verification",
        {
            "fitness_gate": {
                "status": (
                    "passed"
                    if gate_ok
                    else ("failed" if gate_mode == "enforce" else "warning")
                ),
                "blocking_reasons": gate_reasons,
                **gate_detail,
            }
        },
    )

    context = read_context(trace_id, patch_base)
    patch_path = patch_base / trace_id / "proposal.diff"
    apply_result = git_apply(context["repo_path"], patch_path)
    if not apply_result.ok:
        write_state(trace_id, patch_base, "apply_failed", apply_result.reason)
        _record_check(
            trace_id,
            check_type="apply.git_apply",
            status="failed",
            detail=apply_result.reason,
        )
        _record_transition(
            trace_id,
            from_state=phase,
            to_state="apply_failed",
            reason=apply_result.reason,
        )
        _emit(
            trace_id,
            "self_update.apply",
            {"status": "apply_failed", "reason": apply_result.reason},
        )
        _record_failure_capsule(trace_id, "apply", apply_result.reason)
        return {"trace_id": trace_id, "status": "apply_failed", "reason": apply_result.reason}
    _record_check(
        trace_id,
        check_type="apply.git_apply",
        status="passed",
        detail=apply_result.reason,
    )
    commit_result = git_commit_applied(context["repo_path"], trace_id)
    if not commit_result.ok:
        write_state(trace_id, patch_base, "apply_failed", commit_result.reason)
        _record_check(
            trace_id,
            check_type="apply.git_commit",
            status="failed",
            detail=commit_result.reason,
        )
        _record_transition(
            trace_id,
            from_state=phase,
            to_state="apply_failed",
            reason=commit_result.reason,
        )
        _emit(
            trace_id,
            "self_update.apply",
            {"status": "apply_failed", "reason": commit_result.reason},
        )
        _record_failure_capsule(trace_id, "apply", commit_result.reason)
        return {"trace_id": trace_id, "status": "apply_failed", "reason": commit_result.reason}
    _record_check(
        trace_id,
        check_type="apply.git_commit",
        status="passed",
        detail=commit_result.reason,
    )

    marker = mark_applied(trace_id, patch_base)
    write_state(trace_id, patch_base, "applied", commit_result.reason)
    _record_transition(
        trace_id,
        from_state=phase,
        to_state="applied",
        reason=commit_result.reason,
    )
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
        _record_check(
            trace_id,
            check_type="apply.readyz",
            status="failed",
            detail="readyz failed after apply",
        )
        rollback = self_update_rollback(trace_id, "readyz failed after apply")
        return {
            "trace_id": trace_id,
            "status": "rolled_back",
            "marker": str(marker),
            "rollback_marker": rollback["marker"],
        }
    verified = mark_verified(trace_id, patch_base)
    write_state(trace_id, patch_base, "verified", "readyz passed after apply")
    _record_check(
        trace_id,
        check_type="apply.readyz",
        status="passed",
        detail="readyz passed after apply",
    )
    _record_transition(
        trace_id,
        from_state="applied",
        to_state="verified",
        reason="readyz passed after apply",
    )
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
    previous_state = ""
    try:
        previous_state = read_state(trace_id, patch_base).get("state", "")
    except Exception:
        previous_state = ""
    write_state(trace_id, patch_base, "rolled_back", reason)
    _record_transition(
        trace_id,
        from_state=previous_state or "unknown",
        to_state="rolled_back",
        reason=reason,
    )
    _record_check(
        trace_id,
        check_type="rollback",
        status="passed",
        detail=reason,
        payload={"recovery": recovery},
    )
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
