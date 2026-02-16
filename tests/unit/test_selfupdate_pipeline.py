from jarvis.selfupdate.pipeline import smoke_commands


def test_smoke_commands_dev_profile() -> None:
    cmds = smoke_commands(profile="dev", has_src=True, has_tests=True)
    assert cmds == [["ruff", "check", "src", "tests"], ["pytest", "tests", "-q"]]


def test_smoke_commands_prod_profile_adds_mypy() -> None:
    cmds = smoke_commands(profile="prod", has_src=True, has_tests=False)
    assert cmds == [["ruff", "check", "src"], ["mypy", "src"]]
