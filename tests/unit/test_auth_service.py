import sqlite3
from types import SimpleNamespace

import pytest

from jarvis.auth.service import create_session


def test_create_session_retries_on_transient_db_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConn:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, _query: str, _params: tuple[str, str, str, str, str, str]) -> None:
            self.calls += 1
            if self.calls < 3:
                raise sqlite3.OperationalError("database is locked")

    fake_conn = FakeConn()
    monkeypatch.setattr(
        "jarvis.auth.service.get_settings",
        lambda: SimpleNamespace(web_auth_token_ttl_hours=24),
    )
    monkeypatch.setattr("jarvis.auth.service.time.sleep", lambda _seconds: None)

    session_id, token = create_session(fake_conn, "usr_test", "user")

    assert session_id.startswith("wss_")
    assert token
    assert fake_conn.calls == 3


def test_create_session_re_raises_non_lock_operational_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConn:
        def execute(self, _query: str, _params: tuple[str, str, str, str, str, str]) -> None:
            raise sqlite3.OperationalError("disk I/O error")

    fake_conn = FakeConn()
    monkeypatch.setattr(
        "jarvis.auth.service.get_settings",
        lambda: SimpleNamespace(web_auth_token_ttl_hours=24),
    )
    monkeypatch.setattr("jarvis.auth.service.time.sleep", lambda _seconds: None)

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        create_session(fake_conn, "usr_test", "user")
