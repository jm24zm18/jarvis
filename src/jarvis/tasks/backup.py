"""Backup and retention Celery tasks."""

import gzip
import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jarvis.celery_app import celery_app
from jarvis.config import get_settings
from jarvis.db.connection import connect, get_conn
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id

_NAME_FORMAT = "backup_%Y%m%dT%H%M%SZ.db"
_STATE_FILE = ".remote_state.json"


@dataclass(slots=True)
class Snapshot:
    path: Path
    created_at: datetime


def _emit(trace_id: str, event_type: str, payload: dict[str, object]) -> None:
    with get_conn() as conn:
        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=None,
                event_type=event_type,
                component="backup",
                actor_type="system",
                actor_id="backup",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )


def _snapshot_name(stamp: datetime) -> str:
    return stamp.strftime(_NAME_FORMAT)


def _parse_snapshot_name(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.name, _NAME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _list_snapshots(directory: Path) -> list[Snapshot]:
    snapshots: list[Snapshot] = []
    for candidate in directory.glob("backup_*.db"):
        parsed = _parse_snapshot_name(candidate)
        if parsed is None:
            continue
        snapshots.append(Snapshot(path=candidate, created_at=parsed))
    snapshots.sort(key=lambda item: item.created_at, reverse=True)
    return snapshots


def _bucket_id(stamp: datetime, mode: str) -> str:
    if mode == "hour":
        return stamp.strftime("%Y%m%d%H")
    if mode == "day":
        return stamp.strftime("%Y%m%d")
    return f"{stamp.isocalendar().year:04d}-W{stamp.isocalendar().week:02d}"


def _keep_by_bucket(
    snapshots: list[Snapshot],
    *,
    start: datetime,
    end: datetime | None,
    mode: str,
    limit: int,
    keep: set[Path],
) -> None:
    if limit <= 0:
        return
    selected_buckets = 0
    seen_buckets: set[str] = set()
    for item in snapshots:
        if end is None:
            if item.created_at >= start:
                continue
        else:
            if item.created_at < start or item.created_at >= end:
                continue
        bucket = _bucket_id(item.created_at, mode)
        if bucket in seen_buckets:
            continue
        seen_buckets.add(bucket)
        keep.add(item.path)
        selected_buckets += 1
        if selected_buckets >= limit:
            break


def _prune_retention(
    directory: Path,
    *,
    keep_hourly: int,
    keep_daily: int,
    keep_weekly: int,
) -> tuple[int, int]:
    snapshots = _list_snapshots(directory)
    if not snapshots:
        return 0, 0
    now = datetime.now(UTC)
    keep: set[Path] = {snapshots[0].path}

    hourly_start = now - timedelta(hours=max(0, keep_hourly))
    _keep_by_bucket(
        snapshots,
        start=hourly_start,
        end=now + timedelta(seconds=1),
        mode="hour",
        limit=keep_hourly,
        keep=keep,
    )
    daily_start = now - timedelta(days=max(0, keep_daily))
    _keep_by_bucket(
        snapshots,
        start=daily_start,
        end=hourly_start,
        mode="day",
        limit=keep_daily,
        keep=keep,
    )
    weekly_start = now - timedelta(weeks=max(0, keep_weekly))
    _keep_by_bucket(
        snapshots,
        start=weekly_start,
        end=daily_start,
        mode="week",
        limit=keep_weekly,
        keep=keep,
    )

    deleted = 0
    for item in snapshots:
        if item.path in keep:
            continue
        item.path.unlink(missing_ok=True)
        gz = item.path.with_suffix(".db.gz")
        gz.unlink(missing_ok=True)
        deleted += 1
    return len(keep), deleted


def _compress(snapshot_path: Path) -> Path:
    gz_path = snapshot_path.with_suffix(".db.gz")
    with snapshot_path.open("rb") as source, gzip.open(gz_path, "wb") as target:
        shutil.copyfileobj(source, target)
    return gz_path


def _load_state(directory: Path) -> dict[str, str]:
    state_path = directory / _STATE_FILE
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text())
    except json.JSONDecodeError:
        return {}


def _save_state(directory: Path, state: dict[str, str]) -> None:
    state_path = directory / _STATE_FILE
    state_path.write_text(json.dumps(state))


def _upload_remote(gz_path: Path) -> tuple[bool, str]:
    settings = get_settings()
    if (
        not settings.backup_s3_endpoint.strip()
        or not settings.backup_s3_bucket.strip()
        or not settings.backup_s3_access_key_id.strip()
        or not settings.backup_s3_secret_access_key.strip()
    ):
        return False, "remote backup not configured"
    destination = f"s3://{settings.backup_s3_bucket}/snapshots/{gz_path.name}"
    cmd = [
        "aws",
        "--endpoint-url",
        settings.backup_s3_endpoint,
        "s3",
        "cp",
        str(gz_path),
        destination,
    ]
    if settings.backup_encrypt_remote == 1:
        cmd.extend(["--sse", "AES256"])
    env = os.environ.copy()
    env.update(
        {
        "AWS_ACCESS_KEY_ID": settings.backup_s3_access_key_id,
        "AWS_SECRET_ACCESS_KEY": settings.backup_s3_secret_access_key,
        "AWS_DEFAULT_REGION": settings.backup_s3_region,
        }
    )
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        return False, proc.stderr.strip() or "remote upload failed"
    return True, destination


@celery_app.task(name="jarvis.tasks.backup.create_backup")
def create_backup() -> dict[str, object]:
    settings = get_settings()
    trace_id = new_id("trc")
    backup_dir = Path(settings.backup_local_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC)
    snapshot_path = backup_dir / _snapshot_name(stamp)

    source_conn = connect()
    target_conn = sqlite3.connect(snapshot_path)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()

    gz_path = _compress(snapshot_path)
    keep_count, deleted_count = _prune_retention(
        backup_dir,
        keep_hourly=settings.backup_retention_hourly,
        keep_daily=settings.backup_retention_daily,
        keep_weekly=settings.backup_retention_weekly,
    )

    _emit(
        trace_id,
        "backup.snapshot",
        {
            "snapshot": str(snapshot_path),
            "compressed": str(gz_path),
            "retained": keep_count,
            "deleted": deleted_count,
        },
    )

    state = _load_state(backup_dir)
    current_hour = stamp.strftime("%Y%m%d%H")
    last_uploaded_hour = state.get("last_uploaded_hour", "")
    remote_uploaded = False
    remote_detail = "not_due"
    if current_hour != last_uploaded_hour:
        remote_uploaded, remote_detail = _upload_remote(gz_path)
        if remote_uploaded:
            state["last_uploaded_hour"] = current_hour
            _save_state(backup_dir, state)
    _emit(
        trace_id,
        "backup.remote_upload",
        {"uploaded": remote_uploaded, "detail": remote_detail, "snapshot": gz_path.name},
    )
    return {
        "ok": True,
        "snapshot": str(snapshot_path),
        "compressed": str(gz_path),
        "remote_uploaded": remote_uploaded,
        "remote_detail": remote_detail,
        "retained": keep_count,
        "deleted": deleted_count,
    }
