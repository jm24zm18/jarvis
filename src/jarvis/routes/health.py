"""Health and readiness routes."""

import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import get_system_state, record_readyz_result
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event
from jarvis.ids import new_id
from jarvis.providers.factory import build_fallback_provider, build_primary_provider
from jarvis.providers.router import ProviderRouter

router = APIRouter(tags=["health"])

# Simple in-memory counters for /metrics
_metrics: dict[str, int] = {
    "agent_steps_total": 0,
    "tool_calls_total": 0,
    "channel_messages_sent": 0,
    "channel_messages_failed": 0,
    "tokens_used_total": 0,
}


def increment_metric(name: str, amount: int = 1) -> None:
    """Increment a named metric counter."""
    _metrics[name] = _metrics.get(name, 0) + amount


@router.get("/metrics")
async def metrics() -> JSONResponse:
    """Prometheus-compatible metrics in JSON format."""
    with get_conn() as conn:
        msg_count = conn.execute("SELECT COUNT(*) AS cnt FROM messages").fetchone()
        thread_count = conn.execute("SELECT COUNT(*) AS cnt FROM threads").fetchone()
        event_count = conn.execute("SELECT COUNT(*) AS cnt FROM events").fetchone()
        memory_items_count = conn.execute("SELECT COUNT(*) AS cnt FROM memory_items").fetchone()
        recon_rows = conn.execute(
            "SELECT updated_count, superseded_count, deduped_count, pruned_count, detail_json "
            "FROM state_reconciliation_runs "
            "WHERE created_at >= datetime('now', '-7 day')"
        ).fetchall()
        failure_rows = conn.execute(
            "SELECT error_summary, error_details_json FROM failure_capsules"
        ).fetchall()

    db_stats = {
        "messages_total": int(msg_count["cnt"]) if msg_count else 0,
        "threads_total": int(thread_count["cnt"]) if thread_count else 0,
        "events_total": int(event_count["cnt"]) if event_count else 0,
        "memory_items_count": int(memory_items_count["cnt"]) if memory_items_count else 0,
    }
    runs = len(recon_rows)
    runs_with_changes = 0
    tokens_saved_values: list[float] = []
    for row in recon_rows:
        changes = (
            int(row["updated_count"])
            + int(row["superseded_count"])
            + int(row["deduped_count"])
            + int(row["pruned_count"])
        )
        if changes > 0:
            runs_with_changes += 1
        raw_detail = row["detail_json"]
        if not isinstance(raw_detail, str) or not raw_detail:
            continue
        try:
            details = json.loads(raw_detail)
        except json.JSONDecodeError:
            continue
        if isinstance(details, dict):
            raw_tokens = details.get("tokens_saved")
            if isinstance(raw_tokens, int | float):
                tokens_saved_values.append(float(raw_tokens))
            elif isinstance(raw_tokens, str):
                try:
                    tokens_saved_values.append(float(raw_tokens))
                except ValueError:
                    pass
    hallucination_incidents = 0
    for row in failure_rows:
        summary = str(row["error_summary"]).lower()
        if "hallucinat" in summary:
            hallucination_incidents += 1
            continue
        raw_detail = row["error_details_json"]
        if not isinstance(raw_detail, str) or not raw_detail:
            continue
        try:
            details = json.loads(raw_detail)
        except json.JSONDecodeError:
            continue
        if not isinstance(details, dict):
            continue
        kind = str(details.get("error_kind") or details.get("kind") or "").lower()
        if "hallucinat" in kind:
            hallucination_incidents += 1
    kpi_stats = {
        "memory_avg_tokens_saved": (
            sum(tokens_saved_values) / len(tokens_saved_values) if tokens_saved_values else 0.0
        ),
        "memory_reconciliation_rate": (runs_with_changes / runs) if runs > 0 else 1.0,
        "memory_hallucination_incidents": hallucination_incidents,
    }
    return JSONResponse(content={**_metrics, **db_stats, **kpi_stats})


@router.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    settings = get_settings()
    db_ok = True
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
    except Exception:
        db_ok = False

    router_client = ProviderRouter(
        build_primary_provider(settings),
        build_fallback_provider(settings),
    )
    provider_status = await router_client.health()
    ok = db_ok and (provider_status["primary"] or provider_status["fallback"])
    with get_conn() as conn:
        previous = get_system_state(conn)
        locked = record_readyz_result(
            conn, ok=ok, threshold=settings.lockdown_readyz_fail_threshold
        )
        if locked and previous["lockdown"] == 0:
            emit_event(
                conn,
                EventInput(
                    trace_id=new_id("trc"),
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=None,
                    event_type="lockdown.triggered",
                    component="health",
                    actor_type="system",
                    actor_id="readyz",
                    payload_json='{"reason":"readyz_consecutive_failures"}',
                    payload_redacted_json='{"reason":"readyz_consecutive_failures"}',
                ),
            )
    status_code = 200 if ok else 503
    return JSONResponse(
        status_code=status_code,
        content={"ok": ok, "db": db_ok, "providers": provider_status},
    )
