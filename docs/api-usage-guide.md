# API Usage Guide

Human-oriented guide for common API workflows. For complete endpoint inventory, use `docs/api-reference.md`.

## Auth and Session Flow

1. Login: `POST /api/v1/auth/login`
2. Read current user: `GET /api/v1/auth/me`
3. Logout: `POST /api/v1/auth/logout`

Web UI uses an HTTP-only `jarvis_session` cookie for authenticated requests.
Bearer headers remain supported for compatibility and CLI/test flows.

## Thread and Message Flow

1. List threads: `GET /api/v1/threads`
2. Create a web thread: `POST /api/v1/threads`
3. Post message: `POST /api/v1/messages/{thread_id}`
4. Read message history: `GET /api/v1/messages/{thread_id}`

Ownership is enforced for non-admin users across thread and message APIs.

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

## Self-Update Governance

Admin-only operations:

- List patches: `GET /api/v1/selfupdate/patches`
- Check one patch: `GET /api/v1/selfupdate/patches/{trace_id}`
- Approve apply: `POST /api/v1/selfupdate/patches/{trace_id}/approve`
- Timeline/checks: `GET /api/v1/selfupdate/patches/{trace_id}/timeline`, `GET /api/v1/selfupdate/patches/{trace_id}/checks`

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

## Related Docs

- `docs/api-reference.md`
- `docs/web-admin-guide.md`
- `docs/runbook.md`
