"""FastAPI entrypoint."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from jarvis.agents.loader import load_agent_registry
from jarvis.agents.registry import sync_tool_permissions
from jarvis.agents.seed import ensure_main_agent_seed, sync_seed_skills
from jarvis.channels.generic_webhook import router as generic_webhook_router
from jarvis.channels.registry import register_channel
from jarvis.channels.whatsapp.adapter import WhatsAppAdapter
from jarvis.channels.whatsapp.router import router as whatsapp_router
from jarvis.config import get_settings, validate_settings_for_env
from jarvis.db.connection import get_conn
from jarvis.db.migrations.runner import run_migrations
from jarvis.db.queries import ensure_root_user, ensure_system_state
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
    if ensure_main_agent_seed(Path("agents")):
        logger.info("Seeded default main agent bundle files at startup")
    bundles = {}
    try:
        bundles = load_agent_registry(Path("agents"))
    except RuntimeError as exc:
        logger.warning("Agent bundle load skipped at startup: %s", exc)
    with get_conn() as conn:
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
app.include_router(generic_webhook_router)
app.include_router(api_router)
app.include_router(ws_router)

web_dist = Path("web/dist")
if web_dist.exists():
    app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")
