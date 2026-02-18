import os

from fastapi.testclient import TestClient

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, now_iso
from jarvis.main import app


def _login(client: TestClient, external_id: str | None = None) -> tuple[str, str]:
    payload: dict[str, str] = {"password": "secret"}
    if external_id is not None:
        payload["external_id"] = external_id
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    body = response.json()
    return str(body["token"]), str(body["user_id"])


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_state_item(conn, uid: str, thread_id: str, text: str, *, conflict: int = 0) -> None:
    now = now_iso()
    conn.execute(
        (
            "INSERT INTO state_items("
            "uid, thread_id, text, status, type_tag, topic_tags_json, refs_json, confidence, "
            "replaced_by, supersession_evidence, conflict, pinned, source, created_at, last_seen_at, "
            "updated_at, tier, importance_score, access_count, conflict_count, agent_id, last_accessed_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        ),
        (
            uid,
            thread_id,
            text,
            "active",
            "decision",
            "[]",
            "[]",
            "high",
            None,
            None,
            conflict,
            0,
            "extraction",
            now,
            now,
            now,
            "working",
            0.75,
            0,
            conflict,
            "main",
            now,
        ),
    )


def test_memory_state_search_and_export_are_owner_scoped() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)
    admin_token, _admin_id = _login(client)
    alice_token, alice_user_id = _login(client, "alice-mem")
    bob_token, bob_user_id = _login(client, "bob-mem")

    with get_conn() as conn:
        alice_channel = ensure_channel(conn, alice_user_id, "whatsapp")
        bob_channel = ensure_channel(conn, bob_user_id, "whatsapp")
        alice_thread = create_thread(conn, alice_user_id, alice_channel)
        bob_thread = create_thread(conn, bob_user_id, bob_channel)
        _seed_state_item(conn, "st_alice_1", alice_thread, "alice travel budget preference")
        _seed_state_item(conn, "st_bob_1", bob_thread, "bob confidential preference")

    own_search = client.get(
        "/api/v1/memory/state/search",
        params={"thread_id": alice_thread, "q": "travel", "k": 10, "min_score": 0.0},
        headers=_headers(alice_token),
    )
    assert own_search.status_code == 200
    own_items = own_search.json()["items"]
    assert any(str(item["uid"]) == "st_alice_1" for item in own_items)

    denied_search = client.get(
        "/api/v1/memory/state/search",
        params={"thread_id": bob_thread, "q": "confidential", "k": 10, "min_score": 0.0},
        headers=_headers(alice_token),
    )
    assert denied_search.status_code == 200
    assert denied_search.json()["items"] == []

    own_export = client.get(
        "/api/v1/memory/export",
        params={"thread_id": alice_thread, "limit": 50},
        headers=_headers(alice_token),
    )
    assert own_export.status_code == 200
    assert any("st_alice_1" in line for line in own_export.json()["items"])

    denied_export = client.get(
        "/api/v1/memory/export",
        params={"thread_id": bob_thread, "limit": 50},
        headers=_headers(alice_token),
    )
    assert denied_export.status_code == 200
    assert denied_export.json()["items"] == []

    # Admin can still access cross-thread state surfaces.
    admin_export = client.get(
        "/api/v1/memory/export",
        params={"thread_id": bob_thread, "limit": 50},
        headers=_headers(admin_token),
    )
    assert admin_export.status_code == 200
    assert any("st_bob_1" in line for line in admin_export.json()["items"])
    _ = bob_token


def test_memory_state_graph_is_owner_scoped() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)
    _admin_token, _admin_user_id = _login(client)
    alice_token, alice_user_id = _login(client, "alice-graph")
    bob_token, bob_user_id = _login(client, "bob-graph")

    with get_conn() as conn:
        alice_channel = ensure_channel(conn, alice_user_id, "whatsapp")
        bob_channel = ensure_channel(conn, bob_user_id, "whatsapp")
        alice_thread = create_thread(conn, alice_user_id, alice_channel)
        bob_thread = create_thread(conn, bob_user_id, bob_channel)
        _seed_state_item(conn, "st_alice_root", alice_thread, "alice root")
        _seed_state_item(conn, "st_alice_leaf", alice_thread, "alice leaf")
        _seed_state_item(conn, "st_bob_root", bob_thread, "bob root")
        now = now_iso()
        conn.execute(
            (
                "INSERT INTO state_relations("
                "id, source_uid, target_uid, thread_id, agent_id, relation_type, confidence, "
                "evidence_json, created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "rel_alice_1",
                "st_alice_root",
                "st_alice_leaf",
                alice_thread,
                "main",
                "supports",
                0.91,
                "{}",
                now,
                now,
            ),
        )

    allowed = client.get(
        "/api/v1/memory/state/graph/st_alice_root",
        params={"depth": 2},
        headers=_headers(alice_token),
    )
    assert allowed.status_code == 200
    payload = allowed.json()
    assert "st_alice_root" in payload["nodes"]
    assert "st_alice_leaf" in payload["nodes"]
    assert any(edge["source_uid"] == "st_alice_root" for edge in payload["edges"])

    denied = client.get(
        "/api/v1/memory/state/graph/st_bob_root",
        params={"depth": 2},
        headers=_headers(alice_token),
    )
    assert denied.status_code == 200
    denied_payload = denied.json()
    assert denied_payload["nodes"] == []
    assert denied_payload["edges"] == []
    _ = bob_token


def test_non_admin_cannot_access_admin_memory_state_surfaces() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)
    _admin_token, _admin_user_id = _login(client)
    alice_token, _alice_user_id = _login(client, "alice-admin-routes")

    assert (
        client.get("/api/v1/memory/state/failures", headers=_headers(alice_token)).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/memory/state/review/conflicts", headers=_headers(alice_token)
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/memory/state/review/st_demo/resolve",
            headers=_headers(alice_token),
            json={"resolution": "approve"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/memory/state/consistency/report", headers=_headers(alice_token)
        ).status_code
        == 403
    )


def test_admin_memory_state_review_and_failures_routes() -> None:
    os.environ["WEB_AUTH_SETUP_PASSWORD"] = "secret"
    get_settings.cache_clear()
    client = TestClient(app)
    admin_token, admin_user_id = _login(client)

    with get_conn() as conn:
        channel_id = ensure_channel(conn, admin_user_id, "whatsapp")
        thread_id = create_thread(conn, admin_user_id, channel_id)
        _seed_state_item(conn, "st_conflict_1", thread_id, "conflicted item", conflict=1)
        now = now_iso()
        conn.execute(
            (
                "INSERT INTO memory_review_queue("
                "id, uid, thread_id, agent_id, reason, status, reviewer_id, resolution_json, "
                "created_at, updated_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "rvw_1",
                "st_conflict_1",
                thread_id,
                "main",
                "conflict_detected",
                "open",
                None,
                None,
                now,
                now,
            ),
        )
        conn.execute(
            (
                "INSERT INTO failure_capsules("
                "id, trace_id, phase, error_summary, error_details_json, attempt, created_at"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                "flc_1",
                "trc_demo_1",
                "memory",
                "simulated failure",
                "{}",
                1,
                now,
            ),
        )
        conn.execute(
            (
                "INSERT INTO memory_consistency_reports("
                "id, thread_id, sample_size, total_items, conflicted_items, consistency_score, "
                "details_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?)"
            ),
            ("mcr_1", thread_id, 10, 10, 1, 0.9, "{}", now),
        )

    failures = client.get("/api/v1/memory/state/failures", headers=_headers(admin_token))
    assert failures.status_code == 200
    assert any(item["id"] == "flc_1" for item in failures.json()["items"])

    conflicts = client.get(
        "/api/v1/memory/state/review/conflicts",
        headers=_headers(admin_token),
    )
    assert conflicts.status_code == 200
    assert any(item["uid"] == "st_conflict_1" for item in conflicts.json()["items"])

    resolve = client.post(
        "/api/v1/memory/state/review/st_conflict_1/resolve",
        headers=_headers(admin_token),
        json={"resolution": "approved"},
    )
    assert resolve.status_code == 200
    assert resolve.json()["ok"] is True

    consistency = client.get(
        "/api/v1/memory/state/consistency/report",
        headers=_headers(admin_token),
    )
    assert consistency.status_code == 200
    assert any(item["id"] == "mcr_1" for item in consistency.json()["items"])
