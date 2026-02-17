import shutil
import subprocess
from pathlib import Path

from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_system_state
from jarvis.selfupdate.pipeline import write_context
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


def _evidence() -> dict[str, object]:
    return {
        "intent": "apply patch safely",
        "file_refs": ["hello.txt:1"],
        "line_refs": ["hello.txt:1"],
        "policy_refs": ["deny-by-default tool access"],
        "invariant_checks": ["append-only database migrations"],
        "test_plan": ["pytest tests -q"],
        "risk_notes": ["low-risk text replacement"],
    }


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

    propose = self_update_propose(trace_id, str(repo), patch, "test", evidence=_evidence())
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

    _ = self_update_propose(trace_id, str(repo), patch, "bad", evidence=_evidence())
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

    _ = self_update_propose(trace_id, str(repo), patch, "bad test", evidence=_evidence())
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

    _ = self_update_propose(trace_id, str(repo), patch, "smoke fail", evidence=_evidence())
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
    _ = self_update_propose(trace_id, str(repo), patch, "test", evidence=_evidence())
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
    _ = self_update_propose(first, str(repo), patch, "rollback one", evidence=_evidence())
    _ = self_update_propose(second, str(repo), patch, "rollback two", evidence=_evidence())
    _ = self_update_rollback(first, "forced rollback 1")
    _ = self_update_rollback(second, "forced rollback 2")

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT event_type, payload_redacted_json FROM events "
            "WHERE event_type='lockdown.triggered' ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    assert any("rollback_burst" in str(row["payload_redacted_json"]) for row in rows)


def test_selfupdate_requires_evidence_packet(tmp_path: Path) -> None:
    trace_id = "trc_self_missing_evidence"
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
    propose = self_update_propose(trace_id, str(repo), patch, "missing evidence", evidence=None)
    assert propose["status"] == "rejected"


def test_selfupdate_requires_line_refs(tmp_path: Path) -> None:
    trace_id = "trc_self_missing_line_refs"
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
    evidence = _evidence()
    del evidence["line_refs"]
    propose = self_update_propose(
        trace_id,
        str(repo),
        patch,
        "missing line refs",
        evidence=evidence,
    )
    assert propose["status"] == "rejected"


def test_selfupdate_rejects_malformed_line_refs(tmp_path: Path) -> None:
    trace_id = "trc_self_bad_line_refs"
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
    evidence = _evidence()
    evidence["line_refs"] = ["hello.txt:0"]
    propose = self_update_propose(trace_id, str(repo), patch, "bad line refs", evidence=evidence)
    assert propose["status"] == "rejected"


def test_selfupdate_critical_path_requires_test_changes(tmp_path: Path) -> None:
    trace_id = "trc_self_critical_no_tests"
    _clean(trace_id)
    repo = _make_repo(tmp_path)
    critical_path = repo / "src" / "jarvis" / "tools"
    critical_path.mkdir(parents=True, exist_ok=True)
    runtime_file = critical_path / "runtime.py"
    runtime_file.write_text("x = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "add runtime file"],
        check=True,
        capture_output=True,
        text=True,
    )
    patch = "\n".join(
        [
            "diff --git a/src/jarvis/tools/runtime.py b/src/jarvis/tools/runtime.py",
            "--- a/src/jarvis/tools/runtime.py",
            "+++ b/src/jarvis/tools/runtime.py",
            "@@ -1 +1 @@",
            "-x = 1",
            "+x = 2",
            "",
        ]
    )
    _ = self_update_propose(trace_id, str(repo), patch, "critical change", evidence=_evidence())
    _ = self_update_validate(trace_id)
    result = self_update_test(trace_id)
    assert result["status"] == "failed"
    assert "requires tests" in result["reason"]


def test_selfupdate_validate_requires_baseline_for_replay(tmp_path: Path) -> None:
    trace_id = "trc_self_missing_baseline"
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
    _ = self_update_propose(trace_id, str(repo), patch, "test", evidence=_evidence())
    write_context(
        trace_id,
        Path(get_settings().selfupdate_patch_dir),
        str(repo),
        "test",
        baseline_ref="",
    )
    result = self_update_validate(trace_id)
    assert result["status"] == "rejected"
    assert "baseline_ref" in result["reason"]
