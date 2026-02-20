"""System status + lockdown API routes."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from jarvis.agents.loader import reset_loader_caches
from jarvis.auth.dependencies import UserContext, require_admin, require_auth
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_system_state, get_system_state, now_iso
from jarvis.providers.factory import (
    build_fallback_provider,
    build_primary_provider,
    resolve_primary_provider_name,
)
from jarvis.providers.router import ProviderRouter
from jarvis.repo_index import read_repo_index, write_repo_index
from jarvis.scheduler.service import estimate_schedule_backlog
from jarvis.tasks import get_task_runner

router = APIRouter(prefix="/system", tags=["api-system"])

_RESET_FTS_TABLES = (
    "event_fts",
    "memory_fts",
    "skills_fts",
    "knowledge_docs_fts",
)
_RESET_DATA_TABLES = (
    "story_runs",
    "memory_governance_audit",
    "agent_governance",
    "state_item_embeddings",
    "state_extraction_watermarks",
    "state_items",
    "failure_capsules",
    "webhook_triggers",
    "skill_install_log",
    "bug_reports",
    "knowledge_docs",
    "skills",
    "onboarding_states",
    "web_notifications",
    "web_sessions",
    "thread_summaries",
    "schedule_dispatches",
    "schedules",
    "approvals",
    "tool_permissions",
    "principals",
    "event_vec_index_map",
    "memory_vec_index_map",
    "event_vec",
    "memory_vec",
    "event_text",
    "memory_embeddings",
    "memory_items",
    "external_messages",
    "events",
    "messages",
    "thread_settings",
    "threads",
    "channels",
    "users",
    "sessions",
    "session_participants",
    "system_state",
)


@router.get("/status")
async def system_status(ctx: UserContext = Depends(require_auth)) -> dict[str, object]:  # noqa: B008
    del ctx
    settings = get_settings()
    primary_provider_name = resolve_primary_provider_name(settings)
    fallback_provider_name = "gemini" if primary_provider_name == "sglang" else "sglang"
    provider_status = await ProviderRouter(
        build_primary_provider(settings),
        build_fallback_provider(settings),
    ).health()
    runner = get_task_runner()
    queue_depths = {"in_flight": runner.in_flight}
    with get_conn() as conn:
        state = get_system_state(conn)
        backlog = estimate_schedule_backlog(
            conn, default_max_catchup=settings.scheduler_max_catchup
        )
        last_provider_error_row = conn.execute(
            "SELECT payload_json, created_at FROM events "
            "WHERE event_type='model.fallback' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    last_provider_error: dict[str, str] | None = None
    if last_provider_error_row is not None:
        payload_raw = str(last_provider_error_row["payload_json"])
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            reason = payload.get("primary_error")
            if isinstance(reason, str) and reason.strip():
                last_provider_error = {
                    "reason": reason.strip(),
                    "at": str(last_provider_error_row["created_at"]),
                }
    return {
        "time": now_iso(),
        "system": state,
        "providers": {
            **provider_status,
            "primary_name": primary_provider_name,
            "fallback_name": fallback_provider_name,
        },
        "provider_errors": {"last_primary_failure": last_provider_error},
        "queue_depths": queue_depths,
        "scheduler": backlog,
    }


@router.post("/lockdown")
def toggle_lockdown(
    payload: dict[str, object],
    ctx: UserContext = Depends(require_admin),  # TODO: admin-only now  # noqa: B008
) -> dict[str, object]:
    del ctx
    enabled = bool(payload.get("lockdown", False))
    reason = str(payload.get("reason", "manual"))
    with get_conn() as conn:
        conn.execute(
            (
                "UPDATE system_state SET lockdown=?, lockdown_reason=?, updated_at=? "
                "WHERE id='singleton'"
            ),
            (1 if enabled else 0, reason if enabled else "", now_iso()),
        )
        state = get_system_state(conn)
    return {"ok": True, "system": state}


@router.post("/reset-db")
def reset_db(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, bool]:
    del ctx
    with get_conn() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("BEGIN")
            for table in _RESET_FTS_TABLES:
                conn.execute(f"DELETE FROM {table}")
            for table in _RESET_DATA_TABLES:
                conn.execute(f"DELETE FROM {table}")
            ensure_system_state(conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys = ON")
    return {"ok": True}


@router.post("/reload-agents")
def reload_agents(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, bool]:
    del ctx
    reset_loader_caches()
    return {"ok": True}


@router.get("/repo-index")
def repo_index(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    root = Path.cwd()
    out_path, _hash_path = write_repo_index(root)
    payload = read_repo_index(root) or {}
    return {"ok": True, "path": str(out_path), "index": payload}
