"""API v1 router aggregation."""

from fastapi import APIRouter

from jarvis.routes.api import (
    agents,
    auth,
    bugs,
    events,
    memory,
    messages,
    permissions,
    schedules,
    selfupdate,
    system,
    threads,
    webhooks,
)

router = APIRouter(prefix="/api/v1", tags=["api"])
router.include_router(auth.router)
router.include_router(system.router)
router.include_router(threads.router)
router.include_router(messages.router)
router.include_router(agents.router)
router.include_router(events.router)
router.include_router(memory.router)
router.include_router(schedules.router)
router.include_router(selfupdate.router)
router.include_router(permissions.router)
router.include_router(bugs.router)
router.include_router(webhooks.router)
