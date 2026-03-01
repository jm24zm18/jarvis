import json
from pathlib import Path

from jarvis.tools.feature_isolate import (
    WorkspaceContext,
    sanitize_feature_id,
    validate_workspace,
)


def test_sanitize_feature_id_rejects_traversal() -> None:
    invalid = "../../etc"
    try:
        sanitize_feature_id(invalid)
    except Exception as exc:
        assert "invalid feature id" in str(exc)
    else:
        raise AssertionError("expected invalid feature id rejection")


def test_validate_workspace_fails_on_dependency_snapshot_mismatch(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("lock-v1", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "FEATURE_LOCK").write_text(
        json.dumps(
            {
                "dependencies": {
                    "uv_lock_sha256": "different",
                    "pyproject_sha256": "different",
                }
            }
        ),
        encoding="utf-8",
    )
    ctx = WorkspaceContext(
        feature_id="bug_test",
        workspace_path=tmp_path,
        created_at="",
        expires_at="",
        dependency_snapshot={},
    )
    result = validate_workspace(ctx, min_free_gb=0)
    assert result.ok is False
    assert "snapshot mismatch" in result.error
