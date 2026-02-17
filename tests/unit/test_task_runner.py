from __future__ import annotations

import asyncio

import pytest

from jarvis.tasks.runner import TaskRunner


def test_send_task_unknown_returns_false() -> None:
    runner = TaskRunner(max_concurrent=1)
    assert runner.send_task("unknown.task", kwargs={}) is False


@pytest.mark.asyncio
async def test_send_task_dispatches_registered_sync_task() -> None:
    runner = TaskRunner(max_concurrent=1)
    done = asyncio.Event()

    def _task(value: str) -> None:
        if value == "ok":
            done.set()

    runner.register("demo.task", _task)
    assert runner.send_task("demo.task", kwargs={"value": "ok"}) is True
    await asyncio.wait_for(done.wait(), timeout=1.0)
    await runner.shutdown(timeout_s=1)


@pytest.mark.asyncio
async def test_shutdown_drains_inflight_tasks() -> None:
    runner = TaskRunner(max_concurrent=1)
    completed = asyncio.Event()

    async def _task() -> None:
        await asyncio.sleep(0.05)
        completed.set()

    runner.register("demo.async", _task)
    assert runner.send_task("demo.async", kwargs={}) is True
    await runner.shutdown(timeout_s=1)
    assert completed.is_set()
