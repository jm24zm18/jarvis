import subprocess
from pathlib import Path

from jarvis.selfupdate.pipeline import (
    execute_test_plan,
    governance_identity_edits_from_patch,
    replay_patch_determinism_check,
    smoke_commands,
    validate_evidence_refs_in_repo,
)


def test_smoke_commands_dev_profile() -> None:
    cmds = smoke_commands(profile="dev", has_src=True, has_tests=True)
    assert cmds == [["ruff", "check", "src", "tests"], ["pytest", "tests", "-q"]]


def test_smoke_commands_prod_profile_adds_mypy() -> None:
    cmds = smoke_commands(profile="prod", has_src=True, has_tests=False)
    assert cmds == [["ruff", "check", "src"], ["mypy", "src"]]


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


def test_replay_patch_determinism_check_passes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    baseline = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    patch_path = tmp_path / "proposal.diff"
    patch_path.write_text(
        "\n".join(
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
    )
    result = replay_patch_determinism_check(
        repo_path=str(repo),
        baseline_ref=baseline,
        patch_path=patch_path,
        work_dir=tmp_path / "work",
    )
    assert result.ok is True
    assert result.tree_hash
    assert result.changed_files == ["hello.txt"]


def test_replay_patch_determinism_check_requires_baseline() -> None:
    result = replay_patch_determinism_check(
        repo_path=".",
        baseline_ref="",
        patch_path=Path("proposal.diff"),
        work_dir=Path("/tmp/replay"),
    )
    assert result.ok is False
    assert "baseline_ref" in result.reason


def test_validate_evidence_refs_in_repo_passes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    baseline = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result = validate_evidence_refs_in_repo(
        repo_path=str(repo),
        baseline_ref=baseline,
        file_refs=["hello.txt:1"],
        line_refs=["hello.txt:1"],
        changed_files=["hello.txt"],
    )
    assert result.ok is True


def test_execute_test_plan_reports_command_failure(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    patch_path = tmp_path / "proposal.diff"
    patch_path.write_text(
        "\n".join(
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
    )
    result, command_results = execute_test_plan(
        repo_path=str(repo),
        patch_path=patch_path,
        work_dir=tmp_path / "work",
        commands=["echo ok", "false"],
    )
    assert result.ok is False
    assert len(command_results) == 2


def test_governance_identity_edits_from_patch_detects_field_changes() -> None:
    patch = "\n".join(
        [
            "diff --git a/agents/main/identity.md b/agents/main/identity.md",
            "--- a/agents/main/identity.md",
            "+++ b/agents/main/identity.md",
            "@@ -1,7 +1,7 @@",
            " ---",
            "-risk_tier: medium",
            "+risk_tier: high",
            " allowed_tools:",
            "   - web_search",
            " ---",
            "",
        ]
    )
    assert governance_identity_edits_from_patch(patch) == ["agents/main/identity.md"]


def test_governance_identity_edits_from_patch_detects_allowed_tools_list_changes() -> None:
    patch = "\n".join(
        [
            "diff --git a/agents/main/identity.md b/agents/main/identity.md",
            "--- a/agents/main/identity.md",
            "+++ b/agents/main/identity.md",
            "@@ -4,3 +4,4 @@",
            " allowed_tools:",
            "   - web_search",
            "+  - exec_host",
            " ---",
            "",
        ]
    )
    assert governance_identity_edits_from_patch(patch) == ["agents/main/identity.md"]
