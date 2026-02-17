import os

from fastapi.testclient import TestClient

from jarvis.agents import loader as agent_loader
from jarvis.agents.types import AgentBundle
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_thread,
    ensure_channel,
    ensure_system_state,
    ensure_user,
    insert_message,
    now_iso,
)
from jarvis.main import app


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert response.status_code == 200
    return str(response.json()["token"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _count(conn, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    assert row is not None
    return int(row["n"])


def test_reset_db() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    client = TestClient(app)
    token = _login(client)

    with get_conn() as conn:
        ensure_system_state(conn)
        user_id = ensure_user(conn, "reset-user")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)
        _ = insert_message(conn, thread_id, "user", "hello")
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "evt_reset",
                "trc_reset",
                "spn_reset",
                None,
                thread_id,
                "agent.step.end",
                "orchestrator",
                "agent",
                "main",
                "{}",
                "{}",
                now_iso(),
            ),
        )
        conn.execute(
            "INSERT INTO external_messages(id, channel_type, external_msg_id, trace_id, created_at)"
            " VALUES(?,?,?,?,?)",
            ("ext_reset", "web", "external-1", "trc_reset", now_iso()),
        )
        conn.execute(
            (
                "INSERT INTO memory_items("
                "id, thread_id, text, metadata_json, created_at"
                ") VALUES(?,?,?,?,?)"
            ),
            ("mem_reset", thread_id, "remember", "{}", now_iso()),
        )
        conn.execute(
            (
                "INSERT INTO memory_embeddings("
                "memory_id, model, vector_json, created_at"
                ") VALUES(?,?,?,?)"
            ),
            ("mem_reset", "test", "[0.1]", now_iso()),
        )
        conn.execute(
            (
                "UPDATE system_state SET lockdown=1, restarting=1, lockdown_reason=?, updated_at=? "
                "WHERE id='singleton'"
            ),
            ("test-reset", now_iso()),
        )
        migration_count_before = _count(conn, "schema_migrations")

    response = client.post("/api/v1/system/reset-db", headers=_headers(token), json={})
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    with get_conn() as conn:
        assert _count(conn, "users") == 0
        assert _count(conn, "channels") == 0
        assert _count(conn, "threads") == 0
        assert _count(conn, "messages") == 0
        assert _count(conn, "events") == 0
        assert _count(conn, "external_messages") == 0
        assert _count(conn, "memory_items") == 0
        assert _count(conn, "memory_embeddings") == 0
        assert _count(conn, "sessions") == 0
        assert _count(conn, "session_participants") == 0
        assert _count(conn, "schema_migrations") == migration_count_before
        state = conn.execute(
            "SELECT id, lockdown, restarting FROM system_state WHERE id='singleton'"
        ).fetchone()
        assert state is not None
        assert state["id"] == "singleton"
        assert int(state["lockdown"]) == 0
        assert int(state["restarting"]) == 0


def test_reload_agents() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()

    client = TestClient(app)
    token = _login(client)

    agent_loader._agent_ids_cache = (frozenset({"main"}), 1.0)
    agent_loader._bundle_cache["main"] = (
        AgentBundle(
            agent_id="main",
            identity_markdown="---\nallowed_tools:\n- echo\n---",
            soul_markdown="soul",
            heartbeat_markdown="heartbeat",
            allowed_tools=["echo"],
        ),
        1.0,
    )

    response = client.post("/api/v1/system/reload-agents", headers=_headers(token), json={})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert agent_loader._agent_ids_cache is None
    assert agent_loader._bundle_cache == {}
