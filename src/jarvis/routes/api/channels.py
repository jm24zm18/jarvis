"""Admin routes for channel integration management."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from jarvis.auth.dependencies import UserContext, require_admin
from jarvis.channels.whatsapp.evolution_client import EvolutionClient
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import upsert_whatsapp_instance

router = APIRouter(prefix="/channels", tags=["api-channels"])
_limiter = Limiter(key_func=get_remote_address)


class PairingCodeInput(BaseModel):
    number: str = Field(min_length=6, max_length=32)


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
    with get_conn() as conn:
        upsert_whatsapp_instance(
            conn,
            instance=client.instance,
            status=evo_state,
            metadata=payload,
        )
    return {
        "enabled": True,
        "instance": client.instance,
        "status_code": status_code,
        "payload": payload,
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
    evo_state = str(payload.get("instance", {}).get("state") or payload.get("state") or "created")
    with get_conn() as conn:
        upsert_whatsapp_instance(
            conn,
            instance=client.instance,
            status=evo_state,
            metadata=payload,
        )
    return {"ok": status_code < 400, "status_code": status_code, "payload": payload}


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
        )
    return {"ok": status_code < 400, "status_code": status_code, "payload": payload}
