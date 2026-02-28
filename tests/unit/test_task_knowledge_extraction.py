import json

import jarvis.tasks.memory as memory_tasks
from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, ensure_user, insert_message, now_iso


def _seed_thread(external_id: str = "15558880001") -> tuple[str, str]:
    with get_conn() as conn:
        user_id = ensure_user(conn, external_id)
        channel_id = ensure_channel(conn, user_id, "whatsapp")
        thread_id = create_thread(conn, user_id, channel_id)
        insert_message(conn, thread_id, "user", "Please debug this Next.js issue.")
        insert_message(conn, thread_id, "assistant", "I found root cause and mitigation.")
    return user_id, thread_id


def test_disabled_returns_skipped(monkeypatch) -> None:
    _, thread_id = _seed_thread("15558880101")
    monkeypatch.setenv("AUTO_KNOWLEDGE_EXTRACTION_ENABLED", "0")
    monkeypatch.setenv("MEMORY_GRAPH_ENABLED", "1")
    memory_tasks.get_settings.cache_clear()

    result = memory_tasks.post_task_knowledge_extraction(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_task_lessons_disabled",
        total_tool_calls=6,
        step_idx=2,
    )
    assert result["skipped_reason"] == "disabled"


def test_graph_disabled_skips(monkeypatch) -> None:
    _, thread_id = _seed_thread("15558880102")
    monkeypatch.setenv("AUTO_KNOWLEDGE_EXTRACTION_ENABLED", "1")
    monkeypatch.setenv("MEMORY_GRAPH_ENABLED", "0")
    memory_tasks.get_settings.cache_clear()

    result = memory_tasks.post_task_knowledge_extraction(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_task_lessons_graph_disabled",
        total_tool_calls=6,
        step_idx=2,
    )
    assert result["skipped_reason"] == "memory_graph_disabled"


def test_happy_path_upserts_triples(monkeypatch) -> None:
    _user_id, thread_id = _seed_thread("15558880103")

    def _fake_extract(*_args, **_kwargs):
        return {
            "lessons": [
                {
                    "subject": "Next.js App Router",
                    "predicate": "best_practice_for",
                    "object": "wrap all Server Action mutations in try/catch",
                    "confidence": 0.92,
                    "importance": 8,
                },
                {
                    "subject": "debugging workflow",
                    "predicate": "skill_for",
                    "object": "parallelize verification commands when safe",
                    "confidence": 0.88,
                    "importance": 7,
                },
            ],
            "profile_updates": {"prefers": ["concise root-cause summaries"]},
        }

    monkeypatch.setattr(memory_tasks, "_extract_task_lessons", _fake_extract)
    monkeypatch.setenv("AUTO_KNOWLEDGE_EXTRACTION_ENABLED", "1")
    monkeypatch.setenv("MEMORY_GRAPH_ENABLED", "1")
    memory_tasks.get_settings.cache_clear()

    result = memory_tasks.post_task_knowledge_extraction(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_task_lessons_happy",
        total_tool_calls=7,
        step_idx=3,
    )
    assert result["ok"] is True
    assert result["triples_upserted"] == 2

    with get_conn() as conn:
        rows = conn.execute(
            (
                "SELECT extraction_type, extracted_at, source_trace_id FROM knowledge_graph "
                "WHERE source_thread_id=? AND extraction_type='task_lesson'"
            ),
            (thread_id,),
        ).fetchall()
    assert len(rows) == 2
    assert all(str(row["extraction_type"]) == "task_lesson" for row in rows)
    assert all(row["extracted_at"] is not None for row in rows)
    assert all(str(row["source_trace_id"]) == "trc_task_lessons_happy" for row in rows)


def test_rejects_low_confidence(monkeypatch) -> None:
    _user_id, thread_id = _seed_thread("15558880104")

    def _fake_extract(*_args, **_kwargs):
        return {
            "lessons": [
                {
                    "subject": "Next.js App Router",
                    "predicate": "best_practice_for",
                    "object": "always write tests",
                    "confidence": 0.60,
                    "importance": 8,
                }
            ]
        }

    monkeypatch.setattr(memory_tasks, "_extract_task_lessons", _fake_extract)
    monkeypatch.setenv("AUTO_KNOWLEDGE_EXTRACTION_ENABLED", "1")
    monkeypatch.setenv("MEMORY_GRAPH_ENABLED", "1")
    memory_tasks.get_settings.cache_clear()

    result = memory_tasks.post_task_knowledge_extraction(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_task_lessons_low_conf",
        total_tool_calls=6,
        step_idx=2,
    )
    assert result["triples_upserted"] == 0
    assert result["triples_skipped"] == 1


def test_rejects_profile_predicates(monkeypatch) -> None:
    _user_id, thread_id = _seed_thread("15558880105")

    def _fake_extract(*_args, **_kwargs):
        return {
            "lessons": [
                {
                    "subject": "user",
                    "predicate": "prefers",
                    "object": "Python",
                    "confidence": 0.95,
                    "importance": 6,
                },
                {
                    "subject": "deploy workflow",
                    "predicate": "should_avoid",
                    "object": "skipping smoke tests before release",
                    "confidence": 0.9,
                    "importance": 8,
                },
            ]
        }

    monkeypatch.setattr(memory_tasks, "_extract_task_lessons", _fake_extract)
    monkeypatch.setenv("AUTO_KNOWLEDGE_EXTRACTION_ENABLED", "1")
    monkeypatch.setenv("MEMORY_GRAPH_ENABLED", "1")
    memory_tasks.get_settings.cache_clear()

    result = memory_tasks.post_task_knowledge_extraction(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_task_lessons_predicates",
        total_tool_calls=6,
        step_idx=2,
    )
    assert result["triples_upserted"] == 1
    assert result["triples_skipped"] == 1


def test_notification_emitted(monkeypatch) -> None:
    _user_id, thread_id = _seed_thread("15558880106")

    def _fake_extract(*_args, **_kwargs):
        return {
            "lessons": [
                {
                    "subject": "api retries",
                    "predicate": "lesson_learned",
                    "object": "cap retries and include jitter",
                    "confidence": 0.9,
                    "importance": 7,
                }
            ]
        }

    monkeypatch.setattr(memory_tasks, "_extract_task_lessons", _fake_extract)
    monkeypatch.setenv("AUTO_KNOWLEDGE_EXTRACTION_ENABLED", "1")
    monkeypatch.setenv("AUTO_KNOWLEDGE_EXTRACTION_NOTIFY", "1")
    monkeypatch.setenv("MEMORY_GRAPH_ENABLED", "1")
    memory_tasks.get_settings.cache_clear()

    _ = memory_tasks.post_task_knowledge_extraction(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_task_lessons_notify",
        total_tool_calls=6,
        step_idx=2,
    )
    with get_conn() as conn:
        row = conn.execute(
            (
                "SELECT payload_json FROM web_notifications WHERE thread_id=? "
                "AND event_type='knowledge.extraction.complete' ORDER BY created_at DESC LIMIT 1"
            ),
            (thread_id,),
        ).fetchone()
    assert row is not None
    payload = json.loads(str(row["payload_json"]))
    assert int(payload["triples_upserted"]) == 1


def test_llm_error_returns_gracefully(monkeypatch) -> None:
    _user_id, thread_id = _seed_thread("15558880107")

    def _raise_extract(*_args, **_kwargs):
        raise TimeoutError("router timeout")

    monkeypatch.setattr(memory_tasks, "_extract_task_lessons", _raise_extract)
    monkeypatch.setenv("AUTO_KNOWLEDGE_EXTRACTION_ENABLED", "1")
    monkeypatch.setenv("MEMORY_GRAPH_ENABLED", "1")
    memory_tasks.get_settings.cache_clear()

    result = memory_tasks.post_task_knowledge_extraction(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_task_lessons_error",
        total_tool_calls=6,
        step_idx=2,
    )
    assert "error" in result


def test_cooldown_skips(monkeypatch) -> None:
    _user_id, thread_id = _seed_thread("15558880108")
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO events("
                "id, trace_id, span_id, parent_span_id, thread_id, event_type, component, "
                "actor_type, actor_id, "
                "payload_json, payload_redacted_json, created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                "evt_task_lessons_cooldown",
                "trc_task_lessons_prev",
                "spn_task_lessons_prev",
                None,
                thread_id,
                "knowledge.extraction.complete",
                "memory",
                "agent",
                "main",
                "{}",
                "{}",
                now_iso(),
            ),
        )
    monkeypatch.setenv("AUTO_KNOWLEDGE_EXTRACTION_ENABLED", "1")
    monkeypatch.setenv("MEMORY_GRAPH_ENABLED", "1")
    monkeypatch.setenv("AUTO_KNOWLEDGE_EXTRACTION_COOLDOWN_MINUTES", "60")
    memory_tasks.get_settings.cache_clear()

    result = memory_tasks.post_task_knowledge_extraction(
        thread_id=thread_id,
        actor_id="main",
        trace_id="trc_task_lessons_cooldown",
        total_tool_calls=6,
        step_idx=2,
    )
    assert result["skipped_reason"] == "cooldown"
