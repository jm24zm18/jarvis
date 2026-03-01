import os
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.main import app


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert response.status_code == 200
    return str(response.json()["token"])


def test_swarm_tasks_requires_auth() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/swarm/tasks")
    assert response.status_code == 401


def test_swarm_list_endpoint(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    def fake_status(*, limit: int = 50, status: str | None = None) -> dict[str, object]:
        assert limit == 25
        assert status == "running"
        return {"ok": True, "count": 1, "items": [{"id": "sch_swarm1", "status": "running"}]}

    monkeypatch.setattr("jarvis.routes.api.swarm.devswarm.status", fake_status)

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/v1/swarm/tasks?limit=25&status=running", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["count"] == 1


def test_swarm_create_uses_workspace_repo(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    captured: dict[str, object] = {}

    def fake_create_task(
        *,
        description: str,
        repo_path: str,
        model: str | None = None,
        task_type: str = "feature",
    ) -> dict[str, object]:
        captured["description"] = description
        captured["repo_path"] = repo_path
        captured["model"] = model
        captured["task_type"] = task_type
        return {"ok": True, "task_id": "sch_swarm2", "status": "running"}

    def fake_detail(task_id: str) -> dict[str, object]:
        assert task_id == "sch_swarm2"
        return {"ok": True, "item": {"id": "sch_swarm2", "status": "running"}}

    monkeypatch.setattr("jarvis.routes.api.swarm.devswarm.create_task", fake_create_task)
    monkeypatch.setattr("jarvis.routes.api.swarm.devswarm.get_task_detail", fake_detail)

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(
        "/api/v1/swarm/tasks",
        headers=headers,
        json={
            "description": "Implement swarm UI",
            "task_type": "feature",
            "model": "local-model",
        },
    )
    assert response.status_code == 200
    assert Path(str(captured["repo_path"])) == Path.cwd().resolve()
    assert captured["description"] == "Implement swarm UI"
    assert captured["task_type"] == "feature"


def test_swarm_create_preflight_error_returns_400(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    def fake_create_task(
        *,
        description: str,
        repo_path: str,
        model: str | None = None,
        task_type: str = "feature",
    ) -> dict[str, object]:
        del description, repo_path, model, task_type
        return {"ok": False, "error": "invalid OpenCode config at /tmp/opencode.json"}

    monkeypatch.setattr("jarvis.routes.api.swarm.devswarm.create_task", fake_create_task)

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(
        "/api/v1/swarm/tasks",
        headers=headers,
        json={"description": "Implement swarm UI"},
    )
    assert response.status_code == 400
    assert "invalid OpenCode config" in str(response.json().get("detail") or "")


def test_swarm_nudge_and_cleanup(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    def fake_send(task_id: str, message: str) -> dict[str, object]:
        assert task_id == "sch_existing"
        assert message == "re-run tests"
        return {"ok": True, "task_id": task_id, "session": "swarm-sch_existing"}

    cleanup_calls: list[bool] = []

    def fake_cleanup(
        *,
        task_id: str | None = None,
        remove_worktrees: bool = True,
    ) -> dict[str, object]:
        assert task_id == "sch_existing"
        cleanup_calls.append(remove_worktrees)
        return {"ok": True, "removed": ["sch_existing"], "failures": []}

    def fake_detail(task_id: str) -> dict[str, object]:
        return {"ok": True, "item": {"id": task_id, "status": "running"}}

    monkeypatch.setattr("jarvis.routes.api.swarm.devswarm.send_tmux", fake_send)
    monkeypatch.setattr("jarvis.routes.api.swarm.devswarm.cleanup", fake_cleanup)
    monkeypatch.setattr("jarvis.routes.api.swarm.devswarm.get_task_detail", fake_detail)

    from jarvis.db.connection import get_conn

    with get_conn() as conn:
        conn.execute(
            (
                "INSERT OR REPLACE INTO devswarm_tasks("
                "id, task_type, description, repo_path, worktree_path, branch, "
                "base_branch, tmux_session, status, attempt, max_attempts, "
                "model, provider, checks_json, last_error, completed_at, "
                "created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "sch_existing",
                "feature",
                "Existing task",
                str(Path.cwd()),
                str(Path.cwd() / ".jarvis/worktrees/sch_existing"),
                "swarm/sch_existing",
                "dev",
                "swarm-sch_existing",
                "running",
                1,
                3,
                "local-model",
                "lmstudio",
                "{}",
                "",
                None,
                "2026-02-28T00:00:00Z",
                "2026-02-28T00:00:00Z",
            ),
        )

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    nudge = client.post(
        "/api/v1/swarm/tasks/sch_existing/nudge",
        headers=headers,
        json={"message": "re-run tests"},
    )
    assert nudge.status_code == 200
    assert nudge.json()["ok"] is True

    cleanup_default = client.post(
        "/api/v1/swarm/tasks/sch_existing/cleanup",
        headers=headers,
        json={},
    )
    assert cleanup_default.status_code == 200
    cleanup_remove = client.post(
        "/api/v1/swarm/tasks/sch_existing/cleanup",
        headers=headers,
        json={"remove_worktrees": True},
    )
    assert cleanup_remove.status_code == 200
    assert cleanup_calls == [False, True]
