from fastapi.testclient import TestClient

from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, ensure_user, now_iso
from jarvis.main import app


def test_healthz_ok() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_readyz_shape() -> None:
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code in {200, 503}
    data = response.json()
    assert "ok" in data
    assert "providers" in data


def test_readyz_returns_503_when_dependencies_unhealthy(monkeypatch) -> None:
    from jarvis.routes import health as health_route

    async def unhealthy(self):
        del self
        return {"primary": False, "fallback": False}

    monkeypatch.setattr(health_route.ProviderRouter, "health", unhealthy)

    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["ok"] is False


def test_metrics_include_memory_kpis() -> None:
    with get_conn() as conn:
        user_id = ensure_user(conn, "15551239999")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)
        now = now_iso()
        conn.execute(
            (
                "INSERT INTO memory_items(id, thread_id, text, metadata_json, created_at) "
                "VALUES(?,?,?,?,?)"
            ),
            ("mem_metrics_1", thread_id, "memory text", "{}", now),
        )
        conn.execute(
            (
                "INSERT INTO state_reconciliation_runs("
                "id, scope, stale_before, updated_count, superseded_count, deduped_count, "
                "pruned_count, detail_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?)"
            ),
            ("rec_metrics_1", "global", now, 1, 0, 0, 0, '{"tokens_saved": 42}', now),
        )
        conn.execute(
            (
                "INSERT INTO failure_capsules("
                "id, trace_id, phase, error_summary, error_details_json, attempt, created_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                "flc_metrics_1",
                "trc_metrics_1",
                "planner",
                "hallucination detected in summary",
                "{}",
                1,
                now,
            ),
        )

    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["memory_items_count"] >= 1
    assert data["memory_avg_tokens_saved"] >= 42
    assert data["memory_reconciliation_rate"] > 0
    assert data["memory_hallucination_incidents"] >= 1
