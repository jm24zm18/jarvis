"""Approval gate for outbound replies on non-web channels."""

from __future__ import annotations

import json
import sqlite3
from typing import Literal

from jarvis.config import get_settings
from jarvis.db.queries import (
    create_thread,
    ensure_channel,
    get_channel_outbound,
    insert_message,
    now_iso,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.tasks import get_task_runner

ApprovalMode = Literal["once", "always"]

_REQUEST_COLUMNS = (
    "id, source_thread_id, source_message_id, trace_id, channel_type, recipient, "
    "status, decision_mode, reason, admin_thread_id, decided_by, decided_at, "
    "created_at, updated_at"
)


def _emit(
    conn: sqlite3.Connection,
    *,
    trace_id: str,
    thread_id: str | None,
    event_type: str,
    payload: dict[str, object],
) -> None:
    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type=event_type,
            component="channel_reply_approval",
            actor_type="system",
            actor_id="channel_reply_approval",
            payload_json=json.dumps(payload),
            payload_redacted_json=json.dumps(redact_payload(payload)),
        ),
    )


def _resolve_admin_thread(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT t.id FROM threads t "
        "JOIN channels c ON c.id=t.channel_id "
        "JOIN users u ON u.id=t.user_id "
        "WHERE c.channel_type='web' AND t.status='open' AND u.role='admin' "
        "ORDER BY t.updated_at DESC LIMIT 1"
    ).fetchone()
    if row is not None:
        return str(row["id"])

    admin_row = conn.execute(
        "SELECT id FROM users WHERE role='admin' "
        "ORDER BY CASE WHEN external_id='system:root' THEN 1 ELSE 0 END, created_at ASC "
        "LIMIT 1"
    ).fetchone()
    if admin_row is None:
        return None
    admin_user_id = str(admin_row["id"])
    channel_id = ensure_channel(conn, admin_user_id, "web")
    return create_thread(conn, admin_user_id, channel_id)


def _has_active_permission(conn: sqlite3.Connection, *, channel_type: str, recipient: str) -> bool:
    row = conn.execute(
        "SELECT id FROM channel_reply_permissions "
        "WHERE channel_type=? AND recipient=? AND status='active' "
        "ORDER BY created_at DESC LIMIT 1",
        (channel_type, recipient),
    ).fetchone()
    return row is not None


def _ensure_pending_request(
    conn: sqlite3.Connection,
    *,
    source_thread_id: str,
    source_message_id: str,
    trace_id: str,
    channel_type: str,
    recipient: str,
) -> tuple[dict[str, object], bool]:
    existing = conn.execute(
        f"SELECT {_REQUEST_COLUMNS} FROM channel_reply_approval_requests "
        "WHERE source_message_id=? LIMIT 1",
        (source_message_id,),
    ).fetchone()
    if existing is not None:
        return dict(existing), False

    request_id = new_id("apr")
    admin_thread_id = _resolve_admin_thread(conn) or ""
    stamp = now_iso()
    conn.execute(
        "INSERT INTO channel_reply_approval_requests("
        "id, source_thread_id, source_message_id, trace_id, channel_type, recipient, status, "
        "decision_mode, reason, admin_thread_id, decided_by, decided_at, created_at, updated_at"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            request_id,
            source_thread_id,
            source_message_id,
            trace_id,
            channel_type,
            recipient,
            "pending",
            "",
            "",
            admin_thread_id,
            "",
            None,
            stamp,
            stamp,
        ),
    )
    row = conn.execute(
        f"SELECT {_REQUEST_COLUMNS} FROM channel_reply_approval_requests WHERE id=? LIMIT 1",
        (request_id,),
    ).fetchone()
    return (dict(row) if row is not None else {"id": request_id}), True


def _notify_admin_thread(
    conn: sqlite3.Connection,
    *,
    admin_thread_id: str,
    request_id: str,
    source_thread_id: str,
    source_message_id: str,
    channel_type: str,
    recipient: str,
) -> None:
    preview = ""
    outbound = get_channel_outbound(conn, source_thread_id, source_message_id, channel_type)
    if outbound is not None:
        preview = str(outbound.get("text") or "")
    preview = " ".join(preview.split())
    if len(preview) > 220:
        preview = f"{preview[:217]}..."

    body = (
        "[Reply Approval Required]\n"
        f"Request: {request_id}\n"
        f"Channel: {channel_type}\n"
        f"Recipient: {recipient}\n"
        f"Source thread: {source_thread_id}\n"
        f"Source message: {source_message_id}\n"
    )
    if preview:
        body = f"{body}Preview: {preview}\n"
    body = (
        f"{body}\n"
        "Commands:\n"
        f"- /channel-approve {request_id} once\n"
        f"- /channel-approve {request_id} always\n"
        f"- /channel-deny {request_id} optional reason"
    )
    message_id = insert_message(conn, admin_thread_id, "assistant", body)
    conn.execute(
        "INSERT INTO web_notifications(thread_id, event_type, payload_json, created_at) "
        "VALUES(?,?,?,?)",
        (
            admin_thread_id,
            "message.new",
            json.dumps({"message_id": message_id, "role": "assistant"}),
            now_iso(),
        ),
    )


def check_or_request_approval(
    conn: sqlite3.Connection,
    *,
    source_thread_id: str,
    source_message_id: str,
    trace_id: str,
    channel_type: str,
    recipient: str,
) -> tuple[bool, str | None]:
    if channel_type == "web":
        return True, None
    settings = get_settings()
    if int(settings.non_web_reply_approval_required) != 1:
        return True, None
    if _has_active_permission(conn, channel_type=channel_type, recipient=recipient):
        return True, None

    req, created = _ensure_pending_request(
        conn,
        source_thread_id=source_thread_id,
        source_message_id=source_message_id,
        trace_id=trace_id,
        channel_type=channel_type,
        recipient=recipient,
    )
    request_id = str(req.get("id") or "")
    admin_thread_id = str(req.get("admin_thread_id") or "")
    if created and admin_thread_id:
        _notify_admin_thread(
            conn,
            admin_thread_id=admin_thread_id,
            request_id=request_id,
            source_thread_id=source_thread_id,
            source_message_id=source_message_id,
            channel_type=channel_type,
            recipient=recipient,
        )

    _emit(
        conn,
        trace_id=trace_id,
        thread_id=source_thread_id,
        event_type="channel.reply.approval.requested",
        payload={
            "request_id": request_id,
            "channel_type": channel_type,
            "recipient": recipient,
            "source_message_id": source_message_id,
            "source_thread_id": source_thread_id,
            "admin_thread_id": admin_thread_id or None,
        },
    )
    return False, request_id or None


def list_approval_requests(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, object]]:
    filters: list[str] = []
    params: list[object] = []
    if status:
        filters.append("status=?")
        params.append(status)
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        f"SELECT {_REQUEST_COLUMNS} FROM channel_reply_approval_requests{where} "
        "ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


def _dispatch_source_message(request: dict[str, object]) -> bool:
    source_thread_id = str(request.get("source_thread_id") or "")
    source_message_id = str(request.get("source_message_id") or "")
    channel_type = str(request.get("channel_type") or "")
    if not source_thread_id or not source_message_id or not channel_type:
        return False
    return get_task_runner().send_task(
        "jarvis.tasks.channel.send_channel_message",
        kwargs={
            "thread_id": source_thread_id,
            "message_id": source_message_id,
            "channel_type": channel_type,
        },
        queue="tools_io",
    )


def approve_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    approver_id: str,
    mode: ApprovalMode,
    trace_id: str,
) -> dict[str, object]:
    row = conn.execute(
        "SELECT id, source_thread_id, source_message_id, trace_id, channel_type, recipient, status "
        "FROM channel_reply_approval_requests WHERE id=? LIMIT 1",
        (request_id,),
    ).fetchone()
    if row is None:
        return {"ok": False, "error": "request not found"}
    request = dict(row)
    current_status = str(request.get("status") or "")
    if current_status not in {"pending", "approved_once", "approved_always"}:
        return {"ok": False, "error": f"request in status {current_status}"}

    recipient = str(request.get("recipient") or "")
    channel_type = str(request.get("channel_type") or "")
    stamp = now_iso()
    decision_status = "approved_always" if mode == "always" else "approved_once"

    if mode == "always" and recipient and channel_type:
        existing = conn.execute(
            "SELECT id FROM channel_reply_permissions "
            "WHERE channel_type=? AND recipient=? AND status='active' LIMIT 1",
            (channel_type, recipient),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO channel_reply_permissions("
                "id, channel_type, recipient, status, granted_by, revoked_by, "
                "revoked_reason, created_at, updated_at, revoked_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id("apr"),
                    channel_type,
                    recipient,
                    "active",
                    approver_id,
                    "",
                    "",
                    stamp,
                    stamp,
                    None,
                ),
            )

    conn.execute(
        "UPDATE channel_reply_approval_requests "
        "SET status=?, decision_mode=?, decided_by=?, decided_at=?, updated_at=? "
        "WHERE id=?",
        (decision_status, mode, approver_id, stamp, stamp, request_id),
    )

    dispatched = _dispatch_source_message(request)
    final_status = "sent" if dispatched else decision_status
    conn.execute(
        "UPDATE channel_reply_approval_requests SET status=?, updated_at=? WHERE id=?",
        (final_status, now_iso(), request_id),
    )

    _emit(
        conn,
        trace_id=trace_id,
        thread_id=str(request.get("source_thread_id") or ""),
        event_type="channel.reply.approval.approved",
        payload={
            "request_id": request_id,
            "mode": mode,
            "status": final_status,
            "dispatched": dispatched,
            "channel_type": channel_type,
            "recipient": recipient,
            "source_message_id": str(request.get("source_message_id") or ""),
            "approver_id": approver_id,
        },
    )
    return {
        "ok": True,
        "request_id": request_id,
        "mode": mode,
        "status": final_status,
        "dispatched": dispatched,
    }


def reject_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    approver_id: str,
    reason: str,
    trace_id: str,
) -> dict[str, object]:
    row = conn.execute(
        "SELECT id, source_thread_id, source_message_id, channel_type, recipient, status "
        "FROM channel_reply_approval_requests WHERE id=? LIMIT 1",
        (request_id,),
    ).fetchone()
    if row is None:
        return {"ok": False, "error": "request not found"}
    current_status = str(row["status"] or "")
    if current_status != "pending":
        return {"ok": False, "error": f"request in status {current_status}"}
    stamp = now_iso()
    conn.execute(
        "UPDATE channel_reply_approval_requests "
        "SET status='rejected', reason=?, decision_mode='reject', decided_by=?, "
        "decided_at=?, updated_at=? WHERE id=?",
        (reason[:500], approver_id, stamp, stamp, request_id),
    )
    _emit(
        conn,
        trace_id=trace_id,
        thread_id=str(row["source_thread_id"]),
        event_type="channel.reply.approval.rejected",
        payload={
            "request_id": request_id,
            "channel_type": str(row["channel_type"]),
            "recipient": str(row["recipient"]),
            "source_message_id": str(row["source_message_id"]),
            "approver_id": approver_id,
            "reason": reason[:500],
        },
    )
    return {"ok": True, "request_id": request_id, "status": "rejected"}


def list_permissions(
    conn: sqlite3.Connection,
    *,
    status: str | None = "active",
) -> list[dict[str, object]]:
    filters: list[str] = []
    params: list[object] = []
    if status:
        filters.append("status=?")
        params.append(status)
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    rows = conn.execute(
        "SELECT id, channel_type, recipient, status, granted_by, revoked_by, revoked_reason, "
        "created_at, updated_at, revoked_at "
        f"FROM channel_reply_permissions{where} ORDER BY created_at DESC",
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def revoke_permission(
    conn: sqlite3.Connection,
    *,
    channel_type: str,
    recipient: str,
    actor_id: str,
    reason: str = "manual_revoke",
    trace_id: str,
) -> dict[str, object]:
    row = conn.execute(
        "SELECT id FROM channel_reply_permissions "
        "WHERE channel_type=? AND recipient=? AND status='active' "
        "ORDER BY created_at DESC LIMIT 1",
        (channel_type, recipient),
    ).fetchone()
    if row is None:
        return {"ok": False, "error": "active permission not found"}
    perm_id = str(row["id"])
    stamp = now_iso()
    conn.execute(
        "UPDATE channel_reply_permissions "
        "SET status='revoked', revoked_by=?, revoked_reason=?, revoked_at=?, updated_at=? "
        "WHERE id=?",
        (actor_id, reason[:500], stamp, stamp, perm_id),
    )
    _emit(
        conn,
        trace_id=trace_id,
        thread_id=None,
        event_type="channel.reply.permission.revoked",
        payload={
            "permission_id": perm_id,
            "channel_type": channel_type,
            "recipient": recipient,
            "actor_id": actor_id,
            "reason": reason[:500],
        },
    )
    return {"ok": True, "permission_id": perm_id, "status": "revoked"}
