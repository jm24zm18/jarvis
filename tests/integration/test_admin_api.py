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
        conn.execute(
            (
                "INSERT INTO failure_patterns("
                "id, signature, phase, count, latest_reason, latest_trace_id, "
                "first_seen_at, last_seen_at"
                ") VALUES(?,?,?,?,?,?,?,?)"
            ),
            (
                "flp_test",
                "test:failure",
                "test",
                2,
                "pytest failed",
                "trc_test",
                now_iso(),
                now_iso(),
            ),
        )
        conn.execute(
            (
                "INSERT INTO failure_pattern_remediations("
                "id, pattern_id, remediation, verification_test, confidence, created_at"
                ") VALUES(?,?,?,?,?,?)"
            ),
            ("frm_test", "flp_test", "rerun pytest", "pytest -q", "medium", now_iso()),
        )

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/system/status", headers=headers).status_code == 200
    assert client.get("/api/v1/system/repo-index", headers=headers).status_code == 200
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
    assert (
        client.get("/api/v1/memory/state/consistency/report", headers=headers).status_code
        == 200
    )

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
        client.get(
            f"/api/v1/selfupdate/patches/{trace_id}/checks",
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/selfupdate/patches/{trace_id}/timeline",
            headers=headers,
        ).status_code
        == 200
    )
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

    assert client.get("/api/v1/governance/fitness/latest", headers=headers).status_code == 200
    assert client.get("/api/v1/governance/fitness/history", headers=headers).status_code == 200
    assert client.get("/api/v1/governance/slo", headers=headers).status_code == 200
    assert client.get("/api/v1/governance/slo/history", headers=headers).status_code == 200
    assert client.get("/api/v1/governance/dependency-steward", headers=headers).status_code == 200
    assert client.get("/api/v1/governance/release-candidate", headers=headers).status_code == 200
    assert client.get("/api/v1/governance/decision-timeline", headers=headers).status_code == 200
    assert (
        client.get(f"/api/v1/governance/patch-lifecycle/{trace_id}", headers=headers).status_code
        == 200
    )
    assert client.get("/api/v1/governance/learning-loop", headers=headers).status_code == 200
    assert (
        client.post(
            "/api/v1/governance/remediations/frm_test/feedback",
            headers=headers,
            json={"feedback": "accepted"},
        ).status_code
        == 200
    )
    assert (
        client.post("/api/v1/memory/maintenance/run", headers=headers, json={}).status_code == 200
    )
    assert client.get("/api/v1/channels/whatsapp/status", headers=headers).status_code == 200
    assert (
        client.post("/api/v1/channels/whatsapp/create", headers=headers, json={}).status_code
        == 200
    )
    assert client.get("/api/v1/channels/whatsapp/qrcode", headers=headers).status_code == 200
    assert (
        client.post(
            "/api/v1/channels/whatsapp/pairing-code",
            headers=headers,
            json={"number": "15555550123"},
        ).status_code
        == 200
    )
    assert (
        client.post("/api/v1/channels/whatsapp/disconnect", headers=headers, json={}).status_code
        == 200
    )


def test_whatsapp_status_reports_callback_health(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    class _FakeEvolutionClient:
        enabled = True
        instance = "personal"
        webhook_enabled = True
        webhook_url = "http://localhost:8000/webhooks/whatsapp"
        webhook_by_events = True
        webhook_events = ["messages.upsert"]

        async def status(self) -> tuple[int, dict[str, object]]:
            return 200, {"state": "open"}

        async def configure_webhook(self) -> tuple[int, dict[str, object]]:
            return 200, {"configured": True}

    monkeypatch.setattr("jarvis.routes.api.channels.BaileysClient", _FakeEvolutionClient)

    response = client.get("/api/v1/channels/whatsapp/status", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["callback"]["enabled"] is True
    assert payload["callback"]["configured"] is True
    assert payload["callback"]["events"] == ["messages.upsert"]


def test_whatsapp_create_includes_callback_result(monkeypatch) -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    class _FakeEvolutionClient:
        enabled = True
        instance = "personal"
        webhook_enabled = True
        webhook_url = "http://localhost:8000/webhooks/whatsapp"
        webhook_by_events = True
        webhook_events = ["messages.upsert"]

        async def create_instance(self) -> tuple[int, dict[str, object]]:
            return 201, {"state": "created"}

        async def configure_webhook(self) -> tuple[int, dict[str, object]]:
            return 200, {"configured": True}

    monkeypatch.setattr("jarvis.routes.api.channels.BaileysClient", _FakeEvolutionClient)

    response = client.post("/api/v1/channels/whatsapp/create", headers=headers, json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["callback"]["enabled"] is True
    assert payload["callback"]["configured"] is True


def test_whatsapp_pairing_code_rejects_non_numeric_input() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/channels/whatsapp/pairing-code",
        headers=headers,
        json={"number": "abc-not-a-phone"},
    )
    assert response.status_code == 422


def test_whatsapp_review_queue_list_and_resolve() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT OR REPLACE INTO whatsapp_sender_review_queue("
                "id, instance, sender_jid, remote_jid, participant_jid, "
                "thread_id, external_msg_id, "
                "reason, status, reviewer_id, resolution_note, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "sch_review_admin_1",
                "personal",
                "15555559003",
                "15555559003",
                "",
                "",
                "wamid.TEST.ADMIN.REVIEW.1",
                "unknown_sender",
                "open",
                None,
                None,
                now_iso(),
                now_iso(),
            ),
        )

    client = TestClient(app)
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    listing = client.get("/api/v1/channels/whatsapp/review-queue", headers=headers)
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["status"] == "open"
    assert any(item["id"] == "sch_review_admin_1" for item in payload["items"])

    resolve = client.post(
        "/api/v1/channels/whatsapp/review-queue/sch_review_admin_1/resolve",
        headers=headers,
        json={"decision": "allow", "reason": "trusted sender"},
    )
    assert resolve.status_code == 200
    assert resolve.json()["ok"] is True
    assert resolve.json()["item"]["status"] == "allowed"
