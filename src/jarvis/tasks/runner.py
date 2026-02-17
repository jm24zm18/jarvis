"""In-process async task runner."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from jarvis.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _LoopThread:
    loop: asyncio.AbstractEventLoop
    thread: threading.Thread


class TaskRunner:
    """Lightweight fire-and-forget task dispatcher for local runtime."""

    def __init__(self, max_concurrent: int | None = None) -> None:
        settings = get_settings()
        self._registry: dict[str, Callable[..., Any]] = {}
        limit = max_concurrent or int(settings.task_runner_max_concurrent)
        self._max_concurrent = max(1, limit)
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._shutdown = asyncio.Event()
        self._lock = threading.Lock()
        self._loop_thread: _LoopThread | None = None

    @property
    def in_flight(self) -> int:
        return len(self._background_tasks)

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    def register(self, name: str, func: Callable[..., Any]) -> None:
        self._registry[name] = func

    def send_task(
        self,
        name: str,
        kwargs: dict[str, Any] | None = None,
        queue: str | None = None,
    ) -> bool:
        del queue  # compatibility no-op
        if self._shutdown.is_set():
            logger.warning("Task runner is shutting down; skipping task %s", name)
            return False
        func = self._registry.get(name)
        if func is None:
            logger.error("Unknown task: %s", name)
            return False
        payload = kwargs or {}

        try:
            loop = asyncio.get_running_loop()
            self._schedule_on_loop(loop, name, func, payload)
            return True
        except RuntimeError:
            return self._schedule_from_sync(name, func, payload)

    async def shutdown(self, timeout_s: float) -> None:
        self._shutdown.set()
        if self._background_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*list(self._background_tasks), return_exceptions=True),
                    timeout=max(1.0, float(timeout_s)),
                )
            except TimeoutError:
                logger.warning(
                    "Task runner shutdown timed out; cancelling %d tasks",
                    len(self._background_tasks),
                )
                for task in list(self._background_tasks):
                    task.cancel()
        with self._lock:
            loop_thread = self._loop_thread
            self._loop_thread = None
        if loop_thread is not None:
            loop_thread.loop.call_soon_threadsafe(loop_thread.loop.stop)
            loop_thread.thread.join(timeout=2)

    def _schedule_from_sync(
        self,
        name: str,
        func: Callable[..., Any],
        payload: dict[str, Any],
    ) -> bool:
        loop_thread = self._ensure_loop_thread()
        if loop_thread is None:
            logger.error("Failed to create task runner loop thread for %s", name)
            return False

        fut: Future[None] = asyncio.run_coroutine_threadsafe(
            self._schedule_in_loop(name, func, payload),
            loop_thread.loop,
        )
        try:
            fut.result(timeout=2.0)
            return True
        except Exception:
            logger.exception("Failed to enqueue task %s", name)
            return False

    async def _schedule_in_loop(
        self,
        name: str,
        func: Callable[..., Any],
        payload: dict[str, Any],
    ) -> None:
        self._schedule_on_loop(asyncio.get_running_loop(), name, func, payload)

    def _schedule_on_loop(
        self,
        loop: asyncio.AbstractEventLoop,
        name: str,
        func: Callable[..., Any],
        payload: dict[str, Any],
    ) -> None:
        task = loop.create_task(self._execute(name, func, payload))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _execute(
        self,
        name: str,
        func: Callable[..., Any],
        payload: dict[str, Any],
    ) -> None:
        async with self._semaphore:
            try:
                if inspect.iscoroutinefunction(func):
                    await func(**payload)
                    return
                result = await asyncio.to_thread(func, **payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Task failed: %s", name)

    def _ensure_loop_thread(self) -> _LoopThread | None:
        with self._lock:
            current = self._loop_thread
            if current is not None and current.thread.is_alive():
                return current

            loop = asyncio.new_event_loop()

            def _run() -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            thread = threading.Thread(target=_run, name="jarvis-task-runner", daemon=True)
            thread.start()
            self._loop_thread = _LoopThread(loop=loop, thread=thread)
            return self._loop_thread
