# Web Admin Guide

UI route and RBAC behavior guide for `web/src`.

## Route Map

From `web/src/App.tsx`:

- `/login`
- `/chat`
- `/chat/:threadId`
- `/admin/dashboard`
- `/admin/agents`
- `/admin/events`
- `/admin/memory`
- `/admin/schedules`
- `/admin/threads`
- `/admin/selfupdate`
- `/admin/permissions`
- `/admin/providers`
- `/admin/bugs`
- `/admin/governance`
- `/admin/channels`

Unknown routes redirect to `/chat` after auth.

## Auth Model

- `Protected` wrapper requires token and validates session via `GET /api/v1/auth/me`.
- Missing/invalid token redirects to `/login`.
- Session role is `user` or `admin`.

## RBAC and Ownership

- Admin pages depend on admin-only API endpoints (`permissions`, `selfupdate`, `channels`, governance surfaces).
- Non-admin users are ownership-scoped for thread/message/event/memory reads.
- WebSocket subscriptions enforce thread ownership unless role is `admin`.

## WebSocket Model

Endpoint: `/ws?token=<token>`

Client actions:

- `subscribe` with `thread_id`
- `unsubscribe` with `thread_id`
- `subscribe_system`

Event envelope includes `type`, `thread_id`, `created_at`, plus payload fields.

## Common Validation Pass

1. Login on `/login`.
2. Open `/chat`; send and receive one message.
3. Open an admin page with admin token.
4. Verify non-admin token cannot access admin-only actions.
5. Subscribe to a thread over WS and confirm live updates.

## Related Docs

- `docs/api-usage-guide.md`
- `docs/api-reference.md`
- `docs/runbook.md`
