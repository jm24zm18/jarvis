from jarvis.db.connection import get_conn
from jarvis.db.queries import clear_stale_restarting_flag, ensure_system_state


def _restarting_value(conn):
    row = conn.execute(
        "SELECT restarting FROM system_state WHERE id='singleton'"
    ).fetchone()
    assert row is not None
    return int(row["restarting"])


def test_clear_stale_restarting_flag_resets_flag():
    with get_conn() as conn:
        ensure_system_state(conn)
        conn.execute(
            "UPDATE system_state SET restarting=1 WHERE id='singleton'"
        )
        conn.commit()
        assert clear_stale_restarting_flag(conn)
        assert _restarting_value(conn) == 0
        assert not clear_stale_restarting_flag(conn)
        assert _restarting_value(conn) == 0


def test_clear_stale_restarting_flag_noop_when_zero():
    with get_conn() as conn:
        ensure_system_state(conn)
        conn.execute(
            "UPDATE system_state SET restarting=0 WHERE id='singleton'"
        )
        conn.commit()
        assert not clear_stale_restarting_flag(conn)
        assert _restarting_value(conn) == 0
