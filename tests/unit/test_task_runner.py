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


@pytest.mark.asyncio
async def test_shutdown_runtimeerror_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = TaskRunner(max_concurrent=1)
    completed = asyncio.Event()

    def _task() -> None:
        completed.set()

    async def _raise_runtimeerror(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr("jarvis.tasks.runner.asyncio.to_thread", _raise_runtimeerror)

    runner.register("demo.sync", _task)
    assert runner.send_task("demo.sync", kwargs={}) is True
    await asyncio.sleep(0.05)
    assert runner.in_flight == 0
    assert not completed.is_set()
    await runner.shutdown(timeout_s=1)
