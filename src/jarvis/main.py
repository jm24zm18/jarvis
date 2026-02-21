"""FastAPI entrypoint."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from jarvis.agents.loader import load_agent_registry
from jarvis.agents.registry import sync_tool_permissions
from jarvis.agents.seed import ensure_main_agent_seed, sync_seed_skills
from jarvis.channels.generic_webhook import router as generic_webhook_router
from jarvis.channels.registry import register_channel
from jarvis.channels.telegram.adapter import TelegramAdapter
from jarvis.channels.telegram.router import router as telegram_router
from jarvis.channels.whatsapp.adapter import WhatsAppAdapter
from jarvis.channels.whatsapp.baileys_client import BaileysClient
from jarvis.channels.whatsapp.router import router as whatsapp_router
from jarvis.config import get_settings, validate_settings_for_env
from jarvis.db.connection import get_conn
from jarvis.db.migrations.runner import run_migrations
from jarvis.db.queries import (
    ensure_root_user,
    ensure_system_state,
    prune_whatsapp_thread_map_orphans,
    upsert_whatsapp_instance,
)
from jarvis.logging import configure_logging
from jarvis.memory.service import MemoryService
from jarvis.repo_index import write_repo_index
from jarvis.routes.api import router as api_router
from jarvis.routes.health import router as health_router
from jarvis.routes.ws import router as ws_router
from jarvis.routes.ws import start_notification_poller
from jarvis.tasks import get_periodic_scheduler, get_task_runner

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    validate_settings_for_env(settings)
    configure_logging(settings.log_level)
    run_migrations()
    write_repo_index(Path.cwd())
    register_channel(WhatsAppAdapter())
    if settings.telegram_bot_token.strip():
        register_channel(TelegramAdapter())
        logger.info("Telegram channel adapter registered")
    baileys = BaileysClient()
    if baileys.enabled and int(settings.whatsapp_auto_create_on_startup) == 1:
        status_code, payload = await baileys.create_instance()
        callback_status_code: int | None = None
        callback_payload: dict[str, object] = {}
        callback_ok = False
        callback_error = ""
        if baileys.webhook_enabled:
            callback_status_code, callback_payload = await baileys.configure_webhook()
            callback_ok = callback_status_code < 400
            if not callback_ok:
                callback_error = str(callback_payload.get("error") or "configure_webhook_failed")
        with get_conn() as conn:
            evo_state = str(
                payload.get("instance", {}).get("state")
                or payload.get("state")
                or "unknown"
            )
            upsert_whatsapp_instance(
                conn,
                instance=baileys.instance,
                status=evo_state,
                metadata={
                    "status_code": status_code,
                    "payload": payload,
                    "callback_status_code": callback_status_code,
                    "callback_payload": callback_payload,
                },
                callback_url=baileys.webhook_url,
                callback_by_events=baileys.webhook_by_events,
                callback_events=baileys.webhook_events,
                callback_configured=callback_ok,
                callback_last_error=callback_error,
            )
    if ensure_main_agent_seed(Path("agents")):
        logger.info("Seeded default main agent bundle files at startup")
    bundles = {}
    try:
        bundles = load_agent_registry(Path("agents"))
    except RuntimeError as exc:
        logger.warning("Agent bundle load skipped at startup: %s", exc)
    with get_conn() as conn:
        pruned = prune_whatsapp_thread_map_orphans(conn)
        if pruned > 0:
            logger.info("Pruned %d stale whatsapp_thread_map rows", pruned)
        ensure_system_state(conn)
        root_user_id = ensure_root_user(conn)
        logger.info("Root user ready: %s", root_user_id)
        sync_stats = sync_seed_skills(conn)
        if (sync_stats["inserted"] + sync_stats["updated"]) > 0:
            logger.info(
                "Seed skill sync complete (inserted=%d updated=%d skipped=%d)",
                sync_stats["inserted"],
                sync_stats["updated"],
                sync_stats["skipped"],
            )
        if bundles:
            sync_tool_permissions(conn, bundles)
        MemoryService().ensure_vector_indexes(conn)
    poller_task, poller_stop = start_notification_poller()
    task_runner = get_task_runner()
    periodic = get_periodic_scheduler()
    periodic_task = asyncio.create_task(periodic.run())
    yield
    poller_stop.set()
    await poller_task
    await periodic.shutdown()
    await periodic_task
    await task_runner.shutdown(timeout_s=float(settings.task_runner_shutdown_timeout_seconds))


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Jarvis Agent Framework", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": "rate limit exceeded", "detail": str(exc.detail)},
    )

@app.exception_handler(404)
async def spa_fallback(request: Request, exc: Exception) -> FileResponse | JSONResponse:
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    index_path = Path("web/dist/index.html")
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"detail": "Not Found"}, status_code=404)

settings = get_settings()
cors_origins = [item.strip() for item in settings.web_cors_origins.split(",") if item.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
app.include_router(health_router)
app.include_router(whatsapp_router)
app.include_router(telegram_router)
app.include_router(generic_webhook_router)
app.include_router(api_router)
app.include_router(ws_router)

web_dist = Path("web/dist")
if web_dist.exists():
    app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")
