"""Admin routes for channel integration management."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from jarvis.auth.dependencies import UserContext, require_admin
from jarvis.channels.whatsapp.evolution_client import EvolutionClient
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    get_whatsapp_instance,
    list_whatsapp_sender_reviews,
    resolve_whatsapp_sender_review,
    upsert_whatsapp_instance,
)

router = APIRouter(prefix="/channels", tags=["api-channels"])
_limiter = Limiter(key_func=get_remote_address)


class PairingCodeInput(BaseModel):
    number: str = Field(min_length=6, max_length=32, pattern=r"^\+?[0-9]{6,32}$")


class WhatsAppReviewResolveInput(BaseModel):
    decision: str = Field(pattern="^(allow|deny)$")
    reason: str = Field(default="", max_length=500)


@router.get("/whatsapp/status")
def whatsapp_status(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    settings = get_settings()
    client = EvolutionClient()
    if not client.enabled:
        return {
            "enabled": False,
            "instance": settings.whatsapp_instance,
            "status": "cloud_fallback",
        }
    status_code, payload = asyncio.run(client.status())
    evo_state = str(payload.get("instance", {}).get("state") or payload.get("state") or "unknown")
    callback_status_code: int | None = None
    callback_payload: dict[str, object] = {}
    callback_ok = False
    callback_error = ""
    if client.webhook_enabled:
        callback_status_code, callback_payload = asyncio.run(client.configure_webhook())
        callback_ok = callback_status_code < 400
        if not callback_ok:
            callback_error = str(callback_payload.get("error") or "configure_webhook_failed")
    with get_conn() as conn:
        upsert_whatsapp_instance(
            conn,
            instance=client.instance,
            status=evo_state,
            metadata={
                "status_code": status_code,
                "payload": payload,
                "callback_status_code": callback_status_code,
                "callback_payload": callback_payload,
            },
            callback_url=client.webhook_url,
            callback_by_events=client.webhook_by_events,
            callback_events=client.webhook_events,
            callback_configured=callback_ok,
            callback_last_error=callback_error,
        )
        db_state = get_whatsapp_instance(conn, client.instance)
    return {
        "enabled": True,
        "instance": client.instance,
        "status_code": status_code,
        "payload": payload,
        "callback": {
            "enabled": client.webhook_enabled,
            "url": client.webhook_url,
            "by_events": client.webhook_by_events,
            "events": client.webhook_events,
            "status_code": callback_status_code,
            "configured": callback_ok,
            "error": callback_error,
        },
        "instance_state": db_state or {},
    }


@router.post("/whatsapp/create")
@_limiter.limit("5/minute")
def whatsapp_create(
    request: Request,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del request, ctx
    client = EvolutionClient()
    if not client.enabled:
        return {"ok": False, "error": "evolution_api_disabled"}
    status_code, payload = asyncio.run(client.create_instance())
    callback_status_code: int | None = None
    callback_payload: dict[str, object] = {}
    callback_ok = False
    callback_error = ""
    if client.webhook_enabled:
        callback_status_code, callback_payload = asyncio.run(client.configure_webhook())
        callback_ok = callback_status_code < 400
        if not callback_ok:
            callback_error = str(callback_payload.get("error") or "configure_webhook_failed")
    evo_state = str(payload.get("instance", {}).get("state") or payload.get("state") or "created")
    with get_conn() as conn:
        upsert_whatsapp_instance(
            conn,
            instance=client.instance,
            status=evo_state,
            metadata={
                "status_code": status_code,
                "payload": payload,
                "callback_status_code": callback_status_code,
                "callback_payload": callback_payload,
            },
            callback_url=client.webhook_url,
            callback_by_events=client.webhook_by_events,
            callback_events=client.webhook_events,
            callback_configured=callback_ok,
            callback_last_error=callback_error,
        )
    return {
        "ok": status_code < 400,
        "status_code": status_code,
        "payload": payload,
        "callback": {
            "enabled": client.webhook_enabled,
            "status_code": callback_status_code,
            "configured": callback_ok,
            "error": callback_error,
        },
    }


@router.get("/whatsapp/qrcode")
def whatsapp_qrcode(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    client = EvolutionClient()
    if not client.enabled:
        return {"ok": False, "error": "evolution_api_disabled"}
    status_code, payload = asyncio.run(client.qrcode())
    return {
        "ok": status_code < 400,
        "status_code": status_code,
        "qrcode": payload.get("base64") or payload.get("qrcode") or "",
        "payload": payload,
    }


@router.post("/whatsapp/pairing-code")
@_limiter.limit("5/minute")
def whatsapp_pairing_code(
    input_data: PairingCodeInput,
    request: Request,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del request, ctx
    client = EvolutionClient()
    if not client.enabled:
        return {"ok": False, "error": "evolution_api_disabled"}
    status_code, payload = asyncio.run(client.pairing_code(input_data.number))
    code = payload.get("code") if isinstance(payload.get("code"), str) else ""
    return {"ok": status_code < 400, "status_code": status_code, "code": code}


@router.post("/whatsapp/disconnect")
def whatsapp_disconnect(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    client = EvolutionClient()
    if not client.enabled:
        return {"ok": False, "error": "evolution_api_disabled"}
    status_code, payload = asyncio.run(client.disconnect())
    with get_conn() as conn:
        upsert_whatsapp_instance(
            conn,
            instance=client.instance,
            status="disconnected",
            metadata=payload,
            callback_url=client.webhook_url,
            callback_by_events=client.webhook_by_events,
            callback_events=client.webhook_events,
            callback_configured=False,
            callback_last_error="disconnected",
        )
    return {"ok": status_code < 400, "status_code": status_code, "payload": payload}


@router.get("/whatsapp/review-queue")
def whatsapp_review_queue(
    status: str = "open",
    limit: int = 50,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    normalized_status = status.strip().lower()
    if normalized_status not in {"open", "allowed", "denied"}:
        normalized_status = "open"
    with get_conn() as conn:
        items = list_whatsapp_sender_reviews(conn, status=normalized_status, limit=limit)
    return {"items": items, "status": normalized_status, "count": len(items)}


@router.post("/whatsapp/review-queue/{review_id}/resolve")
def whatsapp_resolve_review_item(
    review_id: str,
    input_data: WhatsAppReviewResolveInput,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    with get_conn() as conn:
        decision: Literal["allow", "deny"] = (
            "allow" if input_data.decision == "allow" else "deny"
        )
        resolved = resolve_whatsapp_sender_review(
            conn,
            review_id=review_id,
            decision=decision,
            reviewer_id=ctx.user_id,
            resolution_note=input_data.reason,
        )
    if resolved is None:
        return {"ok": False, "error": "not_found", "review_id": review_id}
    return {"ok": True, "item": resolved}

@router.get("/telegram/status")
def telegram_status(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    settings = get_settings()
    enabled = bool(settings.telegram_bot_token)
    return {
        "enabled": enabled,
        "token_configured": enabled,
        "allowed_chat_ids": settings.telegram_allowed_chat_ids,
    }
