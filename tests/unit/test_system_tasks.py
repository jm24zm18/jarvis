from jarvis.tasks.system import _collect_task_ids


def test_collect_task_ids_handles_active_and_scheduled_payloads() -> None:
    payload = {
        "worker-a": [
            {"id": "task-a"},
            {"request": {"id": "task-b"}},
            {"foo": "bar"},
        ]
    }
    task_ids = _collect_task_ids(payload)
    assert task_ids == {"task-a", "task-b"}
