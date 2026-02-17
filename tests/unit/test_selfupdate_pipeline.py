import subprocess
from pathlib import Path

from jarvis.selfupdate.pipeline import replay_patch_determinism_check, smoke_commands


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
