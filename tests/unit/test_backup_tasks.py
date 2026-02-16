from datetime import UTC, datetime, timedelta
from pathlib import Path

from jarvis.tasks.backup import _prune_retention


def _create_snapshot(path: Path, stamp: datetime) -> None:
    filename = stamp.strftime("backup_%Y%m%dT%H%M%SZ.db")
    (path / filename).write_text("x")


def test_prune_retention_keeps_recent_hourly_daily_weekly(tmp_path: Path) -> None:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    for hour in range(0, 72):
        _create_snapshot(tmp_path, now - timedelta(hours=hour))

    kept, deleted = _prune_retention(
        tmp_path,
        keep_hourly=24,
        keep_daily=14,
        keep_weekly=8,
    )
    assert kept >= 24
    assert deleted >= 1
