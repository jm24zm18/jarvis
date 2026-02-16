import shutil
import subprocess
from pathlib import Path

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_system_state
from jarvis.tasks.selfupdate import (
    self_update_apply,
    self_update_propose,
    self_update_rollback,
    self_update_test,
    self_update_validate,
)


def _clean(trace_id: str) -> None:
    path = Path(get_settings().selfupdate_patch_dir) / trace_id
    if path.exists():
        shutil.rmtree(path)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "hello.txt").write_text("one\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def _make_python_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "python_repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_basic.py").write_text("def test_ok():\n    assert True\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def test_selfupdate_success_path(tmp_path: Path) -> None:
    trace_id = "trc_self_ok"
    _clean(trace_id)
    repo = _make_repo(tmp_path)
    patch = "\n".join(
        [
            "diff --git a/hello.txt b/hello.txt",
            "--- a/hello.txt",
            "+++ b/hello.txt",
            "@@ -1 +1 @@",
            "-one",
            "+two",
            "",
        ]
    )

    propose = self_update_propose(trace_id, str(repo), patch, "test")
    validate = self_update_validate(trace_id)
    test = self_update_test(trace_id)
    apply = self_update_apply(trace_id)

    assert propose["status"] == "proposed"
    assert validate["status"] == "validated"
    assert test["status"] == "passed"
    assert apply["status"] == "verified"
    assert (repo / "hello.txt").read_text() == "two\n"


def test_selfupdate_rejects_protected_path(tmp_path: Path) -> None:
    trace_id = "trc_self_bad_path"
    _clean(trace_id)
    repo = _make_repo(tmp_path)
    patch = "diff --git a/etc/systemd/system/x.service b/etc/systemd/system/x.service\n+bad\n"

    _ = self_update_propose(trace_id, str(repo), patch, "bad")
    validate = self_update_validate(trace_id)
    apply = self_update_apply(trace_id)

    assert validate["status"] == "rejected"
    assert apply["status"] == "rejected"


def test_selfupdate_test_failure_and_rollback(tmp_path: Path) -> None:
    trace_id = "trc_self_fail_test"
    _clean(trace_id)
    repo = _make_repo(tmp_path)
    patch = "\n".join(
        [
            "diff --git a/hello.txt b/hello.txt",
            "--- a/hello.txt",
            "+++ b/hello.txt",
            "@@ -1 +1 @@",
            "-one",
            "+FAIL_TEST",
            "",
        ]
    )

    _ = self_update_propose(trace_id, str(repo), patch, "bad test")
    validate = self_update_validate(trace_id)
    test = self_update_test(trace_id)
    rollback = self_update_rollback(trace_id, "readyz failed")

    assert validate["status"] == "validated"
    assert test["status"] == "failed"
    assert rollback["status"] == "rolled_back"


def test_selfupdate_smoke_gate_pytest_failure(tmp_path: Path) -> None:
    trace_id = "trc_self_smoke_fail"
    _clean(trace_id)
    repo = _make_python_repo(tmp_path)
    patch = "\n".join(
        [
            "diff --git a/tests/test_basic.py b/tests/test_basic.py",
            "--- a/tests/test_basic.py",
            "+++ b/tests/test_basic.py",
            "@@ -1,2 +1,2 @@",
            " def test_ok():",
            "-    assert True",
            "+    assert False",
            "",
        ]
    )

    _ = self_update_propose(trace_id, str(repo), patch, "smoke fail")
    validate = self_update_validate(trace_id)
    test = self_update_test(trace_id)

    assert validate["status"] == "validated"
    assert test["status"] == "failed"


def test_selfupdate_apply_blocked_during_lockdown(tmp_path: Path) -> None:
    trace_id = "trc_self_lockdown"
    _clean(trace_id)
    repo = _make_repo(tmp_path)
    patch = "\n".join(
        [
            "diff --git a/hello.txt b/hello.txt",
            "--- a/hello.txt",
            "+++ b/hello.txt",
            "@@ -1 +1 @@",
            "-one",
            "+two",
            "",
        ]
    )
    _ = self_update_propose(trace_id, str(repo), patch, "test")
    _ = self_update_validate(trace_id)
    _ = self_update_test(trace_id)
    with get_conn() as conn:
        ensure_system_state(conn)
        conn.execute("UPDATE system_state SET lockdown=1 WHERE id='singleton'")
    apply = self_update_apply(trace_id)
    assert apply["status"] == "rejected"
    assert "lockdown" in apply["reason"]


def test_selfupdate_rollback_burst_emits_lockdown_event(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    patch = "\n".join(
        [
            "diff --git a/hello.txt b/hello.txt",
            "--- a/hello.txt",
            "+++ b/hello.txt",
            "@@ -1 +1 @@",
            "-one",
            "+two",
            "",
        ]
    )
    first = "trc_self_rb_1"
    second = "trc_self_rb_2"
    _clean(first)
    _clean(second)
    _ = self_update_propose(first, str(repo), patch, "rollback one")
    _ = self_update_propose(second, str(repo), patch, "rollback two")
    _ = self_update_rollback(first, "forced rollback 1")
    _ = self_update_rollback(second, "forced rollback 2")

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT event_type, payload_redacted_json FROM events "
            "WHERE event_type='lockdown.triggered' ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    assert any("rollback_burst" in str(row["payload_redacted_json"]) for row in rows)
