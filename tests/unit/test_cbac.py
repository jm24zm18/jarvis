"""Tests for CBAC (Capability-Based Access Control) implementation."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from jarvis.auth.dependencies import UserContext
from jarvis.auth.service import mint_restricted_token, validate_token
from jarvis.policy.engine import SCOPE_TOOL_MAP, decision

# ---------------------------------------------------------------------------
# UserContext.has_scope
# ---------------------------------------------------------------------------

def test_has_scope_wildcard_grants_any() -> None:
    ctx = UserContext(user_id="usr_1", role="admin", scopes=frozenset({"*"}))
    assert ctx.has_scope("memory:read") is True
    assert ctx.has_scope("media:write") is True
    assert ctx.has_scope("exec_host") is True


def test_has_scope_namespace_wildcard_grants_namespace() -> None:
    ctx = UserContext(user_id="usr_1", role="user", scopes=frozenset({"memory:*"}))
    assert ctx.has_scope("memory:read") is True
    assert ctx.has_scope("memory:write") is True
    assert ctx.has_scope("media:read") is False


def test_has_scope_exact_match_and_miss() -> None:
    ctx = UserContext(user_id="usr_1", role="user", scopes=frozenset({"memory:read"}))
    assert ctx.has_scope("memory:read") is True
    assert ctx.has_scope("memory:write") is False
    assert ctx.has_scope("media:read") is False


# ---------------------------------------------------------------------------
# mint_restricted_token + validate_token
# ---------------------------------------------------------------------------

def test_mint_restricted_token_inserts_correct_scopes(tmp_path) -> None:
    db_path = str(tmp_path / "test.db")
    os.environ["APP_DB"] = db_path
    from jarvis.config import get_settings
    get_settings.cache_clear()
    from jarvis.db.migrations.runner import run_migrations
    run_migrations()
    from jarvis.db.connection import get_conn

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users(id, external_id, role, scopes, created_at) VALUES(?,?,?,?,?)",
            ("usr_test", "ext_test", "user", '["memory:read"]', datetime.now(UTC).isoformat()),
        )
        raw_token = mint_restricted_token(conn, "usr_test", ["memory:read"], ttl_minutes=15)

    assert raw_token

    with get_conn() as conn:
        result = validate_token(conn, raw_token)

    assert result is not None
    user_id, role, scopes = result
    assert user_id == "usr_test"
    assert role == "user"
    assert "memory:read" in scopes
    assert "*" not in scopes

    get_settings.cache_clear()


def test_expired_restricted_token_returns_none(tmp_path) -> None:
    db_path = str(tmp_path / "test2.db")
    os.environ["APP_DB"] = db_path
    from jarvis.config import get_settings
    get_settings.cache_clear()
    from jarvis.db.migrations.runner import run_migrations
    run_migrations()
    from jarvis.db.connection import get_conn

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users(id, external_id, role, scopes, created_at) VALUES(?,?,?,?,?)",
            ("usr_exp", "ext_exp", "user", '["memory:read"]', datetime.now(UTC).isoformat()),
        )
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn.execute(
            (
                "INSERT INTO web_sessions("
                "id, user_id, role, token_hash, created_at, expires_at, scopes"
                ") VALUES(?,?,?,?,?,?,?)"
            ),
            (
                "wss_exp",
                "usr_exp",
                "user",
                token_hash,
                datetime.now(UTC).isoformat(),
                past,
                '["memory:read"]',
            ),
        )

    with get_conn() as conn:
        result = validate_token(conn, raw_token)

    assert result is None

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# policy.engine.decision with token_scopes (R9 gate)
# ---------------------------------------------------------------------------

def _make_policy_conn() -> sqlite3.Connection:
    """In-memory SQLite with required policy tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE system_state (id TEXT PRIMARY KEY, lockdown INTEGER, restarting INTEGER)"
    )
    conn.execute("INSERT INTO system_state VALUES('singleton', 0, 0)")
    conn.execute(
        "CREATE TABLE tool_permissions "
        "(principal_id TEXT, tool_name TEXT, effect TEXT)"
    )
    conn.execute(
        "INSERT INTO tool_permissions VALUES('agent_test', '*', 'allow')"
    )
    conn.execute(
        "CREATE TABLE agent_governance "
        "(principal_id TEXT, risk_tier TEXT, max_actions_per_step INTEGER, "
        "allowed_paths_json TEXT, can_request_privileged_change INTEGER)"
    )
    conn.commit()
    return conn


def test_decision_restricted_scope_denies_exec_host() -> None:
    conn = _make_policy_conn()
    allowed, reason = decision(
        conn,
        "agent_test",
        "exec_host",
        token_scopes=frozenset({"memory:read"}),
    )
    assert allowed is False
    assert "R9" in reason


def test_decision_restricted_scope_allows_memory_search() -> None:
    conn = _make_policy_conn()
    assert "memory_search" in SCOPE_TOOL_MAP["memory:read"]
    allowed, reason = decision(
        conn,
        "agent_test",
        "memory_search",
        token_scopes=frozenset({"memory:read"}),
    )
    assert allowed is True
    assert reason == "allow"
