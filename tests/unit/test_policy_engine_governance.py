import json

from jarvis.db.connection import get_conn
from jarvis.policy.engine import decision


def _seed_permission(conn, principal_id: str, tool_name: str) -> None:
    conn.execute(
        (
            "INSERT OR REPLACE INTO principals("
            "id, principal_type, created_at"
            ") VALUES(?,?,datetime('now'))"
        ),
        (principal_id, "agent"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO tool_permissions(principal_id, tool_name, effect) VALUES(?,?,?)",
        (principal_id, tool_name, "allow"),
    )


def _seed_governance(
    conn,
    principal_id: str,
    *,
    risk_tier: str,
    allowed_paths: list[str],
    can_request_privileged_change: bool = False,
) -> None:
    conn.execute(
        (
            "INSERT OR REPLACE INTO agent_governance("
            "principal_id, risk_tier, max_actions_per_step, allowed_paths_json, "
            "can_request_privileged_change, updated_at"
            ") VALUES(?,?,?,?,?,datetime('now'))"
        ),
        (
            principal_id,
            risk_tier,
            6,
            json.dumps(allowed_paths),
            1 if can_request_privileged_change else 0,
        ),
    )


def test_decision_denies_outside_allowed_paths() -> None:
    with get_conn() as conn:
        _seed_permission(conn, "coder", "echo")
        _seed_governance(conn, "coder", risk_tier="medium", allowed_paths=["/tmp/allowed"])
        allowed, reason = decision(
            conn,
            "coder",
            "echo",
            arguments={"path": "/tmp/other/file.txt"},
        )
        assert allowed is False
        assert reason == "R7: governance.allowed_paths"


def test_decision_allows_inside_allowed_paths() -> None:
    with get_conn() as conn:
        _seed_permission(conn, "coder", "echo")
        _seed_governance(conn, "coder", risk_tier="medium", allowed_paths=["/tmp/allowed"])
        allowed, reason = decision(
            conn,
            "coder",
            "echo",
            arguments={"path": "/tmp/allowed/file.txt"},
        )
        assert allowed is True
        assert reason == "allow"


def test_decision_denies_high_risk_for_low_tier() -> None:
    with get_conn() as conn:
        _seed_permission(conn, "coder", "exec_host")
        _seed_governance(conn, "coder", risk_tier="low", allowed_paths=["/tmp"])
        allowed, reason = decision(
            conn,
            "coder",
            "exec_host",
            arguments={"cwd": "/tmp", "command": "echo ok"},
        )
        assert allowed is False
        assert reason == "R6: governance.risk_tier"
