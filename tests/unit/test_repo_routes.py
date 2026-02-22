from jarvis.routes.api.repo import validate_branch


def test_validate_branch():
    assert validate_branch("main")
    assert validate_branch("feature/123-foo")
    assert validate_branch("user_branch.1")
    assert validate_branch("fix_foo")
    
    # Path traversals or command injections
    assert not validate_branch("../main")
    assert not validate_branch("-main")  # Git option injection
    assert not validate_branch("main; echo 1")
    assert not validate_branch("foo bar")
    assert not validate_branch("`whoami`")
