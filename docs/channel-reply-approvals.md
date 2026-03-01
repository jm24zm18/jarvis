# Channel Reply Approvals

Operator guide for non-web outbound reply approvals (WhatsApp/Telegram and other non-web channels).

## Purpose

When `NON_WEB_REPLY_APPROVAL_REQUIRED=1`, assistant outbound replies on non-web channels are gated until an admin approves or rejects them.

This guard does not apply to `web` channel replies.

## API Surface (Admin-only)

- `GET /api/v1/channel-reply-approvals`
- `POST /api/v1/channel-reply-approvals/{request_id}/approve`
- `POST /api/v1/channel-reply-approvals/{request_id}/reject`
- `GET /api/v1/channel-reply-permissions`
- `POST /api/v1/channel-reply-permissions/revoke`

Notes:
- Route paths are hyphenated (`channel-reply-*`), not underscore forms.
- There is currently no `GET /api/v1/channel-reply-approvals/{id}` endpoint.

## Data Model Summary

Migration: `src/jarvis/db/migrations/081_channel_reply_approvals.sql`

- `channel_reply_approval_requests`
  - One row per source outbound message (`source_message_id` unique).
  - Stores status, decision mode, approver, recipient, and timestamps.
- `channel_reply_permissions`
  - Persistent allow rules keyed by `channel_type + recipient`.
  - Active rule bypasses future approval prompts for that sender/channel.

## Lifecycle and Status Transitions

1. Assistant prepares outbound non-web reply.
2. Runtime checks active permission for `(channel_type, recipient)`.
3. If none, creates (or reuses) pending request and emits `channel.reply.approval.requested`.
4. Admin decides:
   - Approve once -> dispatch one message.
   - Approve always -> dispatch one message and create active permission.
   - Reject -> mark rejected with optional reason.

Current statuses used by service logic:
- `pending`
- `approved_once`
- `approved_always`
- `sent`
- `rejected`

Transition behavior:
- `pending` -> `approved_once` or `approved_always` during decision.
- If dispatch succeeds, status is finalized to `sent`.
- `pending` -> `rejected` on reject.
- Reject endpoint only accepts `pending`.

## Request/Response Contracts

### List approval requests

`GET /api/v1/channel-reply-approvals?status=<optional>&limit=50&offset=0`

Response shape:

```json
{
  "items": [
    {
      "id": "apr_...",
      "source_thread_id": "thr_...",
      "source_message_id": "msg_...",
      "trace_id": "trc_...",
      "channel_type": "whatsapp",
      "recipient": "15551234567",
      "status": "pending",
      "decision_mode": "",
      "reason": "",
      "admin_thread_id": "thr_...",
      "decided_by": "",
      "decided_at": null,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

### Approve request

`POST /api/v1/channel-reply-approvals/{request_id}/approve`

Body:

```json
{ "mode": "once" }
```

or

```json
{ "mode": "always" }
```

Validation:
- `mode` must be `once` or `always`.

Response:

```json
{
  "ok": true,
  "request_id": "apr_...",
  "mode": "once",
  "status": "sent",
  "dispatched": true
}
```

Error examples:
- `{ "ok": false, "error": "request not found" }`
- `{ "ok": false, "error": "mode must be 'once' or 'always'" }`
- `{ "ok": false, "error": "request in status rejected" }`

### Reject request

`POST /api/v1/channel-reply-approvals/{request_id}/reject`

Body:

```json
{ "reason": "manual deny from admin console" }
```

Response:

```json
{ "ok": true, "request_id": "apr_...", "status": "rejected" }
```

Reject is only valid while request status is `pending`.

### List permissions

`GET /api/v1/channel-reply-permissions?status=active`

Response:

```json
{
  "items": [
    {
      "id": "apr_...",
      "channel_type": "whatsapp",
      "recipient": "15551234567",
      "status": "active",
      "granted_by": "usr_...",
      "revoked_by": "",
      "revoked_reason": "",
      "created_at": "...",
      "updated_at": "...",
      "revoked_at": null
    }
  ]
}
```

### Revoke permission

`POST /api/v1/channel-reply-permissions/revoke`

Body:

```json
{
  "channel_type": "whatsapp",
  "recipient": "15551234567",
  "reason": "manual_revoke"
}
```

Response:

```json
{ "ok": true, "permission_id": "apr_...", "status": "revoked" }
```

## Admin Chat Command Shortcuts

In an admin web thread, these commands are available:

- `/channel-approve-list [pending|sent|rejected|approved_once|approved_always]`
- `/channel-approve <request_id> once|always`
- `/channel-deny <request_id> [reason]`
- `/channel-allow-list [active|revoked]`
- `/channel-allow-revoke <channel_type> <recipient> [reason]`

## Observability

Approval workflow emits trace events:

- `channel.reply.approval.requested`
- `channel.reply.approval.approved`
- `channel.reply.approval.rejected`
- `channel.reply.permission.revoked`

Use `trace_id` from request rows or related thread events to investigate in `/api/v1/events` or web admin events UI.

## Related Docs

- `docs/api-reference.md`
- `docs/api-usage-guide.md`
- `docs/web-admin-guide.md`
- `docs/configuration.md`
