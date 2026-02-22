# API Usage Guide

Human-oriented guide for common API workflows. For complete endpoint inventory, use `docs/api-reference.md`.

## Auth and Session Flow

1. Login: `POST /api/v1/auth/login`
2. Read current user: `GET /api/v1/auth/me`
3. Logout: `POST /api/v1/auth/logout`

Web UI uses an HTTP-only `jarvis_session` cookie for authenticated requests.
Bearer headers remain supported for compatibility and CLI/test flows.
`external_id` in login payload is bounded to 256 characters; oversized values are rejected.

## Thread and Message Flow

1. List threads: `GET /api/v1/threads`
2. Create a web thread: `POST /api/v1/threads`
3. Post message: `POST /api/v1/threads/{thread_id}/messages`
4. Read message history: `GET /api/v1/threads/{thread_id}/messages`

Ownership is enforced for non-admin users across thread and message APIs.

## Media Flow

- Upload attachment: `POST /api/v1/media/upload` (multipart `file`, optional `thread_id`)
- Download attachment: `GET /api/v1/media/{attachment_id}`
- Download image thumbnail: `GET /api/v1/media/{attachment_id}/thumb`

Scope enforcement:
- Upload requires `media:write`.
- Download/thumbnail requires `media:read`.
- Non-admin callers can only fetch attachments they own.

## Memory Flow

- List/query memory: `GET /api/v1/memory`
- Stats: `GET /api/v1/memory/stats`
- Export: `GET /api/v1/memory/export`
- Knowledge base: `GET/POST /api/v1/memory/kb`
- Conflict review (admin): `GET /api/v1/memory/state/review/conflicts`

## Schedules

- List/create: `GET/POST /api/v1/schedules`
- Update: `PATCH /api/v1/schedules/{schedule_id}`
- Dispatch history: `GET /api/v1/schedules/{schedule_id}/dispatches`

## Follow-Up Heartbeats

- Enable thread follow-ups: `POST /api/v1/followups/threads/{thread_id}/enable`
- Disable thread follow-ups: `POST /api/v1/followups/threads/{thread_id}/disable`
- Read thread follow-up status: `GET /api/v1/followups/threads/{thread_id}`

Ownership boundaries apply for non-admin users; only thread owners can manage follow-ups.

## Self-Update Governance

Admin-only operations:

- List patches: `GET /api/v1/selfupdate/patches`
- Check one patch: `GET /api/v1/selfupdate/patches/{trace_id}`
- Approve apply: `POST /api/v1/selfupdate/patches/{trace_id}/approve`
- Timeline/checks: `GET /api/v1/selfupdate/patches/{trace_id}/timeline`, `GET /api/v1/selfupdate/patches/{trace_id}/checks`
- Sandbox summary: `GET /api/v1/selfupdate/patches/{trace_id}/sandbox`

Governance evolution visibility:

- Evolution items: `GET /api/v1/governance/evolution/items`
- Decision timeline: `GET /api/v1/governance/decision-timeline`

Web admin trace drill-down uses `trace_id` and optional `thread_id` query parameters to pivot into `/admin/events`.

## Local Git Interface

Admin-only operations for interacting with the local repository:

- View Status: `GET /api/v1/repo/status`
- View Commit Log: `GET /api/v1/repo/log`
- View Branches: `GET /api/v1/repo/branches`
- View File Diff: `GET /api/v1/repo/diff` (`mode` queries either `working` or `staged`)
- Checkout Branch: `POST /api/v1/repo/checkout`
- Stage Files: `POST /api/v1/repo/stage`
- Unstage Files: `POST /api/v1/repo/unstage`
- Commit: `POST /api/v1/repo/commit`
- Push: `POST /api/v1/repo/push`

## System and Lockdown

- Runtime status: `GET /api/v1/system/status`
- Lockdown toggle (admin): `POST /api/v1/system/lockdown`
- Reload agents (admin): `POST /api/v1/system/reload-agents`

Note the distinction:
- `/status`, `/restart`, `/unlock` are chat slash commands handled by `src/jarvis/commands/service.py`.
- `/api/v1/system/*` are HTTP endpoints.

## WebSockets

Endpoint: `GET /ws` (WebSocket upgrade)

- Cookie session auth is the default for browser clients.
- Bearer `Authorization` header is accepted for compatibility paths.
- Query-string token auth is rejected.
- Client actions: `subscribe`, `unsubscribe`, `subscribe_system` (admin-only)
- Ownership checks are applied on thread subscriptions.
- Non-admin `subscribe_system` requests return `{"type":"error","detail":"forbidden"}`.

GitHub webhook replay behavior:
- Endpoint: `POST /api/v1/webhooks/github`
- Required headers include `X-Hub-Signature-256`, `X-GitHub-Event`, and `X-GitHub-Delivery`.
- Missing `X-GitHub-Delivery` returns `400`.
- Replayed delivery IDs inside the replay window return `409`.

## Feature Request Approval and Build Runs

Feature requests require explicit approval before triggering a build:

```
PATCH /api/v1/feature-requests/{id}/approval   # admin only
  Body: { "decision": "approved"|"rejected", "note": "..." }

POST  /api/v1/feature-requests/{id}/build      # admin only, requires approval_status=approved
  Returns: { run_id, trace_id, feature_id, status }

GET   /api/v1/feature-requests/{id}/build-runs  # admin only
  Returns: { items: [...], feature_id }

GET   /api/v1/feature-requests?approval_status=pending|approved|rejected  # filter by approval
```

## Approvals Center

```
GET  /api/v1/approvals              # admin only, filterable by action/status/target_ref
POST /api/v1/approvals              # admin only
  Body: { "action": "selfupdate.apply", "target_ref": "trc_...", "ttl_minutes": 30 }
  Allowed actions: selfupdate.apply, host.exec.shell, host.exec.script

POST /api/v1/approvals/{id}/revoke  # admin only
```

Active approval tokens consumed by `self_update_apply` are surfaced in the approvals center.

## Related Docs

- `docs/api-reference.md`
- `docs/web-admin-guide.md`
- `docs/runbook.md`
