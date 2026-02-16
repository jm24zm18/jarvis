import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, ensure_user, now_iso
from jarvis.main import app


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/login", json={"password": "secret"})
    assert response.status_code == 200
    return str(response.json()["token"])


def test_admin_endpoints_basic_coverage(tmp_path: Path) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    os.environ["SELFUPDATE_PATCH_DIR"] = str(tmp_path / "patches")
    get_settings.cache_clear()

    patch_base = Path(os.environ["SELFUPDATE_PATCH_DIR"])
    trace_id = "trc_demo"
    patch_dir = patch_base / trace_id
    patch_dir.mkdir(parents=True, exist_ok=True)
    (patch_dir / "state.json").write_text(json.dumps({"state": "tested", "detail": "ok"}))
    (patch_dir / "proposal.diff").write_text("diff --git a/x b/x\n")

    with get_conn() as conn:
        user_id = ensure_user(conn, "15555550001")
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "evt_test",
                "trc_test",
                "spn_test",
                None,
                thread_id,
                "agent.step.end",
                "orchestrator",
                "agent",
                "main",
                json.dumps({"ok": True}),
                json.dumps({"ok": True}),
                now_iso(),
            ),
        )
        conn.execute(
            (
                "INSERT INTO memory_items("
                "id, thread_id, text, metadata_json, created_at"
                ") VALUES(?,?,?,?,?)"
            ),
            ("mem_test", thread_id, "remember this", "{}", now_iso()),
        )
        conn.execute(
            (
                "INSERT INTO memory_embeddings("
                "memory_id, model, vector_json, created_at"
                ") VALUES(?,?,?,?)"
            ),
            ("mem_test", "test", "[0.1,0.2]", now_iso()),
        )
        conn.execute(
            (
                "INSERT INTO schedules("
                "id, thread_id, cron_expr, payload_json, enabled, last_run_at, "
                "created_at, max_catchup"
                ") VALUES(?,?,?,?,?,?,?,?)"
            ),
            ("sch_test", thread_id, "@every:60", '{"x":1}', 1, None, now_iso(), 3),
        )
        conn.execute(
            "INSERT INTO schedule_dispatches(schedule_id, due_at, dispatched_at) VALUES(?,?,?)",
            ("sch_test", now_iso(), now_iso()),
        )

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/system/status", headers=headers).status_code == 200
    assert (
        client.post("/api/v1/system/lockdown", json={"lockdown": True}, headers=headers).status_code
        == 200
    )

    assert client.get("/api/v1/threads?all=true", headers=headers).status_code == 200
    assert client.get(f"/api/v1/threads/{thread_id}", headers=headers).status_code == 200
    assert (
        client.patch(
            f"/api/v1/threads/{thread_id}",
            json={"status": "closed"},
            headers=headers,
        ).status_code
        == 200
    )

    assert client.get("/api/v1/agents", headers=headers).status_code == 200

    events = client.get("/api/v1/events", headers=headers)
    assert events.status_code == 200
    assert client.get("/api/v1/events/evt_test", headers=headers).status_code == 200
    assert client.get("/api/v1/traces/trc_test", headers=headers).status_code == 200

    assert client.get("/api/v1/memory", headers=headers).status_code == 200
    stats = client.get("/api/v1/memory/stats", headers=headers)
    assert stats.status_code == 200
    assert stats.json()["total_items"] >= 1

    assert client.get("/api/v1/schedules", headers=headers).status_code == 200
    assert (
        client.patch(
            "/api/v1/schedules/sch_test",
            json={"enabled": False},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.get("/api/v1/schedules/sch_test/dispatches", headers=headers).status_code == 200

    patches = client.get("/api/v1/selfupdate/patches", headers=headers)
    assert patches.status_code == 200
    assert client.get(f"/api/v1/selfupdate/patches/{trace_id}", headers=headers).status_code == 200
    assert (
        client.post(
            f"/api/v1/selfupdate/patches/{trace_id}/approve",
            json={},
            headers=headers,
        ).status_code
        == 200
    )

    perms = client.get("/api/v1/permissions", headers=headers)
    assert perms.status_code == 200
    assert client.put("/api/v1/permissions/main/echo", json={}, headers=headers).status_code == 200
    assert client.delete("/api/v1/permissions/main/echo", headers=headers).status_code == 200
