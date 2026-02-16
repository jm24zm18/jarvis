"""System status + lockdown API routes."""

import json

from fastapi import APIRouter, Depends

from jarvis.auth.dependencies import UserContext, require_admin, require_auth
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import get_system_state, now_iso
from jarvis.providers.factory import build_primary_provider
from jarvis.providers.router import ProviderRouter
from jarvis.providers.sglang import SGLangProvider
from jarvis.scheduler.service import estimate_schedule_backlog
from jarvis.tasks.monitoring import _queue_depth_by_name

router = APIRouter(prefix="/system", tags=["api-system"])


@router.get("/status")
async def system_status(ctx: UserContext = Depends(require_auth)) -> dict[str, object]:
    del ctx
    settings = get_settings()
    provider_status = await ProviderRouter(
        build_primary_provider(settings),
        SGLangProvider(settings.sglang_model),
    ).health()
    queue_depths = _queue_depth_by_name()
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
        "providers": provider_status,
        "provider_errors": {"last_primary_failure": last_provider_error},
        "queue_depths": queue_depths,
        "scheduler": backlog,
    }


@router.post("/lockdown")
def toggle_lockdown(
    payload: dict[str, object],
    ctx: UserContext = Depends(require_admin),  # TODO: admin-only now
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
