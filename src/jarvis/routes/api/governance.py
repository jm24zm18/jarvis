"""Governance inspection and reload routes."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from jarvis.agents.loader import load_agent_registry, reset_loader_caches
from jarvis.agents.registry import sync_tool_permissions
from jarvis.auth.dependencies import UserContext, require_admin
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_failure_remediation_feedback,
    get_evolution_item,
    get_selfupdate_fitness_gate_config,
    latest_system_fitness_snapshot,
    list_evolution_items,
    list_failure_remediations,
    list_selfupdate_checks,
    list_selfupdate_transitions,
    list_system_fitness_snapshots,
    remediation_feedback_stats,
    update_remediation_confidence,
    upsert_evolution_item,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.selfupdate.pipeline import read_artifact, read_state
from jarvis.tasks.dependency_steward import run_dependency_steward
from jarvis.tasks.maintenance import refresh_learning_loop
from jarvis.tasks.release_candidate import build_release_candidate

router = APIRouter(prefix="/governance", tags=["api-governance"])


class EvolutionItemStatusInput(BaseModel):
    status: str = Field(pattern="^(started|verified|blocked)$")
    trace_id: str = Field(min_length=1)
    thread_id: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    result: dict[str, object] = Field(default_factory=dict)


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _slo_thresholds() -> dict[str, object]:
    settings = get_settings()
    fallback: dict[str, object] = {
        "max_snapshot_age_minutes": max(1, int(settings.selfupdate_fitness_max_age_minutes)),
        "min_build_success_rate": max(0.0, float(settings.selfupdate_min_build_success_rate)),
        "max_regression_frequency": max(0.0, float(settings.selfupdate_max_regression_frequency)),
        "max_rollback_frequency": max(0, int(settings.selfupdate_max_rollback_frequency)),
    }
    with get_conn() as conn:
        stored = get_selfupdate_fitness_gate_config(conn)
    if stored is None:
        return fallback
    return {
        "max_snapshot_age_minutes": _as_int(stored["max_snapshot_age_minutes"], 180),
        "min_build_success_rate": _as_float(stored["min_build_success_rate"], 0.8),
        "max_regression_frequency": _as_float(stored["max_regression_frequency"], 0.4),
        "max_rollback_frequency": _as_int(stored["max_rollback_frequency"], 3),
    }


def _evaluate_slo(
    snapshot: dict[str, object] | None, thresholds: dict[str, object]
) -> tuple[str, list[str], dict[str, object]]:
    reasons: list[str] = []
    if snapshot is None:
        return "blocked", ["missing_system_fitness_snapshot"], {"snapshot_age_minutes": None}

    created_at = str(snapshot.get("created_at", "")).strip()
    snapshot_age_minutes: int | None = None
    if created_at:
        try:
            snapshot_age_minutes = int(
                (datetime.now(UTC) - datetime.fromisoformat(created_at)).total_seconds() // 60
            )
        except ValueError:
            reasons.append("invalid_snapshot_timestamp")
    metrics = snapshot.get("metrics")
    m = metrics if isinstance(metrics, dict) else {}

    max_age = _as_int(thresholds.get("max_snapshot_age_minutes"), 180)
    if snapshot_age_minutes is None or snapshot_age_minutes > max_age:
        reasons.append(f"stale_snapshot>{max_age}m")

    build_success = _as_float(m.get("selfupdate_success_rate", 0.0), 0.0)
    if build_success < _as_float(thresholds.get("min_build_success_rate"), 0.8):
        reasons.append("low_build_success")

    regression = _as_float(m.get("failure_capsule_recurrence_rate", 0.0), 0.0)
    if regression > _as_float(thresholds.get("max_regression_frequency"), 0.4):
        reasons.append("high_regression_frequency")

    rollback_frequency = _as_int(m.get("rollback_frequency", 0), 0)
    if rollback_frequency > _as_int(thresholds.get("max_rollback_frequency"), 3):
        reasons.append("high_rollback_frequency")

    if not reasons:
        status = "safe"
    elif any(item.startswith("stale_snapshot") or item.startswith("missing_") for item in reasons):
        status = "blocked"
    else:
        status = "degraded"
    return status, reasons, {"snapshot_age_minutes": snapshot_age_minutes}


@router.get("/agents")
def list_agent_governance(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT principal_id, risk_tier, max_actions_per_step, allowed_paths_json, "
            "can_request_privileged_change, updated_at "
            "FROM agent_governance ORDER BY principal_id ASC"
        ).fetchall()
    return {
        "items": [
            {
                "principal_id": str(row["principal_id"]),
                "risk_tier": str(row["risk_tier"]),
                "max_actions_per_step": int(row["max_actions_per_step"]),
                "allowed_paths_json": str(row["allowed_paths_json"]),
                "can_request_privileged_change": int(row["can_request_privileged_change"]) == 1,
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]
    }


@router.post("/reload")
def reload_governance(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    reset_loader_caches()
    bundles = load_agent_registry(Path("agents"))
    with get_conn() as conn:
        sync_tool_permissions(conn, bundles)
    return {"ok": True, "agents": sorted(bundles.keys())}


@router.get("/audit")
def memory_governance_audit(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, thread_id, actor_id, decision, reason, target_kind, target_id, "
            "payload_redacted_json, created_at "
            "FROM memory_governance_audit ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    return {
        "items": [
            {
                "id": str(row["id"]),
                "thread_id": str(row["thread_id"]) if row["thread_id"] is not None else "",
                "actor_id": str(row["actor_id"]),
                "decision": str(row["decision"]),
                "reason": str(row["reason"]),
                "target_kind": str(row["target_kind"]),
                "target_id": str(row["target_id"]),
                "payload_redacted_json": str(row["payload_redacted_json"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
    }


@router.get("/fitness/latest")
def fitness_latest(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    with get_conn() as conn:
        item = latest_system_fitness_snapshot(conn)
    return {"item": item}


@router.get("/fitness/history")
def fitness_history(
    limit: int = Query(default=12, ge=1, le=104),
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    with get_conn() as conn:
        items = list_system_fitness_snapshots(conn, limit=limit)
    return {"items": items, "limit": limit}


@router.get("/slo")
def governance_slo(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    thresholds = _slo_thresholds()
    with get_conn() as conn:
        snapshot = latest_system_fitness_snapshot(conn)
    status, reasons, detail = _evaluate_slo(snapshot, thresholds)
    return {
        "status": status,
        "reasons": reasons,
        "thresholds": thresholds,
        "snapshot": snapshot,
        "detail": detail,
    }


@router.get("/slo/history")
def governance_slo_history(
    limit: int = Query(default=12, ge=1, le=104),
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    thresholds = _slo_thresholds()
    with get_conn() as conn:
        snapshots = list_system_fitness_snapshots(conn, limit=limit)
    items: list[dict[str, object]] = []
    for snapshot in snapshots:
        status, reasons, detail = _evaluate_slo(snapshot, thresholds)
        items.append(
            {
                "snapshot_id": snapshot.get("id", ""),
                "created_at": snapshot.get("created_at", ""),
                "status": status,
                "reasons": reasons,
                "detail": detail,
            }
        )
    return {"items": items, "thresholds": thresholds, "limit": limit}


@router.get("/dependency-steward")
def dependency_steward_status(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    return run_dependency_steward()


@router.get("/release-candidate")
def release_candidate_status(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    return build_release_candidate()


@router.get("/decision-timeline")
def decision_timeline(
    trace_id: str | None = Query(default=None),
    thread_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    filters: list[str] = [
        "("
        "event_type LIKE 'tool.call.%' OR "
        "event_type LIKE 'policy.%' OR "
        "event_type LIKE 'self_update.%' OR "
        "event_type LIKE 'agent.step.%' OR "
        "event_type='evidence.check' OR "
        "event_type LIKE 'evolution.item.%'"
        ")"
    ]
    params: list[object] = []
    if trace_id:
        filters.append("trace_id=?")
        params.append(trace_id)
    if thread_id:
        filters.append("thread_id=?")
        params.append(thread_id)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_redacted_json, created_at FROM events "
                f"{where} ORDER BY created_at DESC LIMIT ?"
            ),
            (*params, limit),
        ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        raw_payload = str(row["payload_redacted_json"])
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            payload = {"raw": raw_payload}
        if not isinstance(payload, dict):
            payload = {"raw": raw_payload}
        items.append(
            {
                "id": str(row["id"]),
                "trace_id": str(row["trace_id"]),
                "span_id": str(row["span_id"]),
                "parent_span_id": (
                    str(row["parent_span_id"]) if row["parent_span_id"] is not None else None
                ),
                "thread_id": str(row["thread_id"]) if row["thread_id"] is not None else None,
                "event_type": str(row["event_type"]),
                "component": str(row["component"]),
                "actor_type": str(row["actor_type"]),
                "actor_id": str(row["actor_id"]),
                "intent": payload.get("intent", ""),
                "evidence": payload.get("evidence", {}),
                "plan": payload.get("plan", {}),
                "diff": payload.get("diff", {}),
                "tests": payload.get("tests", {}),
                "result": payload.get("result", {}),
                "payload": payload,
                "created_at": str(row["created_at"]),
            }
        )
    return {
        "items": items,
        "filters": {"trace_id": trace_id or "", "thread_id": thread_id or "", "limit": limit},
    }


@router.get("/evolution/items")
def evolution_items(
    status: str | None = Query(default=None),
    trace_id: str | None = Query(default=None),
    thread_id: str | None = Query(default=None),
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=200, ge=1, le=1000),
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    with get_conn() as conn:
        items = list_evolution_items(
            conn,
            status=status.strip() if isinstance(status, str) else None,
            trace_id=trace_id.strip() if isinstance(trace_id, str) else None,
            thread_id=thread_id.strip() if isinstance(thread_id, str) else None,
            from_ts=from_ts.strip() if isinstance(from_ts, str) else None,
            to_ts=to_ts.strip() if isinstance(to_ts, str) else None,
            limit=limit,
        )
    return {
        "items": items,
        "filters": {
            "status": status or "",
            "trace_id": trace_id or "",
            "thread_id": thread_id or "",
            "from": from_ts or "",
            "to": to_ts or "",
            "limit": limit,
        },
    }


@router.post("/evolution/items/{item_id}/status")
def evolution_item_set_status(
    item_id: str,
    input_data: EvolutionItemStatusInput,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    normalized_item_id = item_id.strip()
    if not normalized_item_id:
        return {"ok": False, "error": "invalid_item_id"}
    next_status = input_data.status.strip()
    transition_allow = {
        "started": {"verified", "blocked"},
        "blocked": {"started"},
        "verified": set(),
    }
    with get_conn() as conn:
        existing = get_evolution_item(conn, normalized_item_id)
        if existing is None:
            if next_status != "started":
                return {"ok": False, "error": "item_not_started"}
            previous_status = ""
        else:
            previous_status = str(existing.get("status") or "")
            allowed = transition_allow.get(previous_status, set())
            if next_status != previous_status and next_status not in allowed:
                return {
                    "ok": False,
                    "error": "invalid_transition",
                    "from_status": previous_status,
                    "to_status": next_status,
                }
        actor_id = str(ctx.user_id)
        normalized_trace_id = input_data.trace_id.strip()
        normalized_thread_id = input_data.thread_id.strip()
        upsert_evolution_item(
            conn,
            item_id=normalized_item_id,
            trace_id=normalized_trace_id,
            thread_id=normalized_thread_id or None,
            status=next_status,
            evidence_refs=[str(item) for item in input_data.evidence_refs],
            result=dict(input_data.result),
            updated_by=actor_id,
        )
        payload: dict[str, object] = {
            "item_id": normalized_item_id,
            "trace_id": normalized_trace_id,
            "status": next_status,
            "evidence_refs": [str(item) for item in input_data.evidence_refs],
            "result": dict(input_data.result),
        }
        event_type = f"evolution.item.{next_status}"
        emit_event(
            conn,
            EventInput(
                trace_id=normalized_trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=normalized_thread_id or None,
                event_type=event_type,
                component="governance.evolution",
                actor_type="admin",
                actor_id=actor_id,
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )
        current = get_evolution_item(conn, normalized_item_id)
    return {
        "ok": True,
        "item": current or {},
        "transition": {"from_status": previous_status, "to_status": next_status},
    }


@router.get("/patch-lifecycle/{trace_id}")
def patch_lifecycle(
    trace_id: str,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    with get_conn() as conn:
        transitions = list_selfupdate_transitions(conn, trace_id)
        checks = list_selfupdate_checks(conn, trace_id)
    base = Path(get_settings().selfupdate_patch_dir)
    artifact: dict[str, object] = {}
    state: dict[str, str] = {}
    if (base / trace_id).exists():
        try:
            artifact = read_artifact(trace_id, base)
        except Exception:
            artifact = {}
        try:
            state = read_state(trace_id, base)
        except Exception:
            state = {}
    fitness_gate = next(
        (item for item in checks if str(item.get("check_type")) == "apply.fitness_gate"),
        None,
    )
    blocking_reasons: list[str] = []
    for item in checks:
        if str(item.get("status")) not in {"failed", "warning"}:
            continue
        detail = str(item.get("detail", "")).strip()
        if detail:
            blocking_reasons.append(detail)
    return {
        "trace_id": trace_id,
        "state": state,
        "transitions": transitions,
        "checks": checks,
        "artifact": artifact,
        "fitness_gate": fitness_gate,
        "blocking_reasons": blocking_reasons,
    }


@router.get("/learning-loop")
def learning_loop(
    window_days: int = Query(default=14, ge=1, le=90),
    refresh: bool = Query(default=True),
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    refresh_result: dict[str, object] | None = None
    if refresh:
        refresh_result = refresh_learning_loop(days=window_days)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, signature, phase, count, latest_reason, latest_trace_id, "
            "first_seen_at, last_seen_at FROM failure_patterns "
            "ORDER BY count DESC, last_seen_at DESC LIMIT 200"
        ).fetchall()
        items = [
            {
                "id": str(row["id"]),
                "signature": str(row["signature"]),
                "phase": str(row["phase"]),
                "count": int(row["count"]),
                "latest_reason": str(row["latest_reason"]),
                "latest_trace_id": str(row["latest_trace_id"]),
                "first_seen_at": str(row["first_seen_at"]),
                "last_seen_at": str(row["last_seen_at"]),
                "remediations": list_failure_remediations(conn, str(row["id"]), limit=5),
            }
            for row in rows
        ]
    return {"window_days": window_days, "refresh": refresh_result, "items": items}


@router.post("/remediations/{remediation_id}/feedback")
def remediation_feedback(
    remediation_id: str,
    payload: Annotated[dict[str, object] | None, Body()] = None,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    raw_payload = payload if isinstance(payload, dict) else {}
    feedback = str(raw_payload.get("feedback", "")).strip().lower()
    if feedback not in {"accepted", "rejected"}:
        return {"ok": False, "error": "feedback must be accepted|rejected"}
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM failure_pattern_remediations WHERE id=? LIMIT 1",
            (remediation_id,),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "remediation not found"}
        feedback_id = create_failure_remediation_feedback(
            conn,
            remediation_id=remediation_id,
            actor_id=ctx.user_id,
            feedback=feedback,
        )
        stats = remediation_feedback_stats(conn, remediation_id)
        total = stats["accepted"] + stats["rejected"]
        ratio = (stats["accepted"] / total) if total > 0 else 0.0
        confidence = "high" if ratio >= 0.75 else ("medium" if ratio >= 0.45 else "low")
        update_remediation_confidence(conn, remediation_id, confidence)
    return {
        "ok": True,
        "id": feedback_id,
        "remediation_id": remediation_id,
        "feedback": feedback,
        "stats": stats,
        "confidence": confidence,
    }
