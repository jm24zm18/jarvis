"""In-process periodic task scheduler."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from jarvis.tasks.runner import TaskRunner

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Entry:
    name: str
    interval_seconds: float
    kwargs: dict[str, object]
    next_run: float


class PeriodicScheduler:
    def __init__(self, runner: TaskRunner) -> None:
        self._runner = runner
        self._entries: list[_Entry] = []
        self._shutdown = asyncio.Event()

    def add(
        self,
        name: str,
        interval_seconds: float,
        kwargs: dict[str, object] | None = None,
    ) -> None:
        interval = max(1.0, float(interval_seconds))
        self._entries.append(
            _Entry(
                name=name,
                interval_seconds=interval,
                kwargs=kwargs or {},
                next_run=time.monotonic() + interval,
            )
        )

    async def run(self) -> None:
        while not self._shutdown.is_set():
            now = time.monotonic()
            for entry in self._entries:
                if now < entry.next_run:
                    continue
                ok = self._runner.send_task(entry.name, kwargs=entry.kwargs)
                if not ok:
                    logger.warning("Failed to dispatch periodic task: %s", entry.name)
                entry.next_run = now + entry.interval_seconds
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=1.0)
            except TimeoutError:
                continue

    async def shutdown(self) -> None:
        self._shutdown.set()
