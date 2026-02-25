"""Admin routes for channel integration management."""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from jarvis.auth.dependencies import UserContext, require_admin
from jarvis.channels.whatsapp.baileys_client import BaileysClient
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
logger = logging.getLogger(__name__)


class PairingCodeInput(BaseModel):
    number: str = Field(min_length=6, max_length=32, pattern=r"^\+?[0-9]{6,32}$")


class WhatsAppReviewResolveInput(BaseModel):
    decision: str = Field(pattern="^(allow|deny)$")
    reason: str = Field(default="", max_length=500)


@router.get("/whatsapp/status")
def whatsapp_status(ctx: UserContext = Depends(require_admin)) -> dict[str, object]:  # noqa: B008
    del ctx
    settings = get_settings()
    client = BaileysClient()
    if not client.enabled:
        return {
            "enabled": False,
            "instance": settings.whatsapp_instance,
            "status": "cloud_fallback",
        }
    try:
        status_code, payload = asyncio.run(client.status())
    except Exception as exc:
        logger.warning("Baileys API unreachable: %s", exc)
        return {
            "enabled": True,
            "instance": client.instance,
            "status": "unreachable",
            "error": str(exc),
        }
    connector_state = str(
        payload.get("instance", {}).get("state") or payload.get("state") or "unknown"
    )
    raw_disconnect_code = payload.get("last_disconnect_code")
    disconnect_code = raw_disconnect_code if isinstance(raw_disconnect_code, int) else None
    disconnect_reason = str(payload.get("last_disconnect_reason") or "").strip()
    last_error_at = str(payload.get("last_error_at") or "").strip()
    autoheal_attempted = bool(payload.get("autoheal_attempted"))
    relink_required = bool(payload.get("relink_required"))
    can_reconnect = bool(payload.get("can_reconnect", True))
    if disconnect_code == status.HTTP_401_UNAUTHORIZED and "loggedout" in disconnect_reason.lower():
        relink_required = True
    recoverable = not relink_required and can_reconnect
    callback_status_code: int | None = 200 if client.webhook_enabled else None
    callback_payload: dict[str, object] = (
        {"success": True, "mode": "managed_by_sidecar"} if client.webhook_enabled else {}
    )
    callback_ok = client.webhook_enabled
    callback_error = "" if callback_ok else "webhook_url_not_configured"
    with get_conn() as conn:
        upsert_whatsapp_instance(
            conn,
            instance=client.instance,
            status=connector_state,
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
        "status": connector_state,
        "status_code": status_code,
        "payload": payload,
        "diagnostics": {
            "disconnect_code": disconnect_code,
            "disconnect_reason": disconnect_reason,
            "last_error_at": last_error_at,
            "autoheal_attempted": autoheal_attempted,
            "relink_required": relink_required,
            "can_reconnect": can_reconnect,
            "recoverable": recoverable,
        },
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
    client = BaileysClient()
    if not client.enabled:
        return {"ok": False, "error": "baileys_api_disabled"}
    try:
        status_code, payload = asyncio.run(client.create_instance())
    except Exception as exc:
        logger.warning("Baileys API unreachable on create: %s", exc)
        return {"ok": False, "error": f"baileys_api_unreachable: {exc}"}
    callback_status_code: int | None = 200 if client.webhook_enabled else None
    callback_payload: dict[str, object] = (
        {"success": True, "mode": "managed_by_sidecar"} if client.webhook_enabled else {}
    )
    callback_ok = client.webhook_enabled
    callback_error = "" if callback_ok else "webhook_url_not_configured"
    connector_state = str(
        payload.get("instance", {}).get("state") or payload.get("state") or "created"
    )
    with get_conn() as conn:
        upsert_whatsapp_instance(
            conn,
            instance=client.instance,
            status=connector_state,
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
    client = BaileysClient()
    if not client.enabled:
        return {"ok": False, "error": "baileys_api_disabled"}
    try:
        status_code, payload = asyncio.run(client.qrcode())
    except Exception as exc:
        logger.warning("Baileys API unreachable on qrcode: %s", exc)
        return {"ok": False, "error": f"baileys_api_unreachable: {exc}"}
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
    client = BaileysClient()
    if not client.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="baileys_api_disabled",
        )
    try:
        status_code, payload = asyncio.run(client.pairing_code(input_data.number))
    except Exception as exc:
        logger.warning("Baileys API unreachable on pairing-code: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"baileys_api_unreachable: {exc}",
        ) from exc
    if status_code >= 400:
        error_detail = str(
            payload.get("error")
            or payload.get("message")
            or payload.get("detail")
            or "pairing_code_failed"
        ).strip()
        if (
            status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            and "QR state not reached" in error_detail
        ):
            error_detail = (
                "qr_not_ready: QR state not reached yet; initialize connection "
                "and wait for QR"
            )
        raise HTTPException(status_code=status_code, detail=error_detail)
    code = payload.get("code") if isinstance(payload.get("code"), str) else ""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="pairing_code_missing",
        )
    return {"ok": status_code < 400, "status_code": status_code, "code": code}


@router.post("/whatsapp/reset")
@_limiter.limit("5/minute")
def whatsapp_reset(
    request: Request,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    """Clear saved Baileys credentials and force a full re-pair."""
    del request, ctx
    client = BaileysClient()
    if not client.enabled:
        return {"ok": False, "error": "baileys_api_disabled"}
    try:
        status_code, payload = asyncio.run(client.reset_instance())
    except Exception as exc:
        logger.warning("Baileys API unreachable on reset: %s", exc)
        return {"ok": False, "error": f"baileys_api_unreachable: {exc}"}
    with get_conn() as conn:
        upsert_whatsapp_instance(
            conn,
            instance=client.instance,
            status="connecting",
            metadata=payload,
            callback_url=client.webhook_url,
            callback_by_events=client.webhook_by_events,
            callback_events=client.webhook_events,
            callback_configured=False,
            callback_last_error="reset_requested",
        )
    return {"ok": status_code < 400, "status_code": status_code, "payload": payload}


@router.post("/whatsapp/restart")
@_limiter.limit("3/minute")
def whatsapp_restart(
    request: Request,
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    """Restart the Baileys Node process. Docker restart:always revives it automatically."""
    del request, ctx
    client = BaileysClient()
    if not client.enabled:
        raise HTTPException(status_code=503, detail="Baileys not configured")
    try:
        asyncio.run(client.restart_server())
    except Exception:
        pass  # Process exits before returning — that's expected
    return {"ok": True, "message": "Baileys process restarting"}


@router.post("/whatsapp/disconnect")
def whatsapp_disconnect(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    client = BaileysClient()
    if not client.enabled:
        return {"ok": False, "error": "baileys_api_disabled"}
    try:
        status_code, payload = asyncio.run(client.disconnect())
    except Exception as exc:
        logger.warning("Baileys API unreachable on disconnect: %s", exc)
        return {"ok": False, "error": f"baileys_api_unreachable: {exc}"}
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
