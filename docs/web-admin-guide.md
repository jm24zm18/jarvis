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
- `/admin/repo`
- `/admin/roadmap`

Unknown routes redirect to `/chat` after auth.

## Auth Model

- `Protected` wrapper validates session via `GET /api/v1/auth/me` using an HTTP-only session cookie.
- Missing/invalid session redirects to `/login`.
- Session role is `user` or `admin`.

## RBAC and Ownership

- Admin pages depend on admin-only API endpoints (`permissions`, `selfupdate`, `channels`, governance surfaces).
- Non-admin users are ownership-scoped for thread/message/event/memory reads.
- WebSocket subscriptions enforce thread ownership unless role is `admin`.

## WebSocket Model

Endpoint: `/ws`

- Auth is cookie-backed (`jarvis_session`) or bearer header for compatibility paths.
- Query-string token auth (`/ws?token=...`) is rejected.

Client actions:

- `subscribe` with `thread_id`
- `unsubscribe` with `thread_id`
- `subscribe_system` (admin only)

Event envelope includes `type`, `thread_id`, `created_at`, plus payload fields.

## Common Validation Pass

1. Login on `/login`.
2. Open `/chat`; send and receive one message.
3. Open an admin page with admin token.
4. Verify non-admin token cannot access admin-only actions.
5. Subscribe to a thread over WS and confirm live updates.

## Trace Drill-Down Workflow

For governance and self-update investigations:

1. Open `/admin/governance` and use `Open Trace` on `Decision Timeline` or `Evolution Items`.
2. Open `/admin/selfupdate` and use `View In Events` from a selected patch.
3. Land on `/admin/events` with query parameters (`trace_id`, optional `thread_id`).
4. Verify the events table and trace viewer load the selected trace context.

## Roadmap Build Chat Monitor

Roadmap Build Runs modal (`/admin/roadmap`) includes a live chat-like monitor for feature builds:

1. Open a feature card with `approval_status=approved`.
2. Click `Build`, then select a run from the run list.
3. Build Chat pane polls thread messages every ~2.5 seconds while modal is open.
4. Status bar shows run status, trace, and created/updated timestamps.
5. Quick links:
   - `Open full Events trace` -> `/admin/events?trace_id=...`
   - `Open Chat thread` -> `/chat/:threadId`

Run status expectations:
- `running`: active execution only.
- `succeeded`: terminal assistant response completed without degraded/leak-blocked outcome.
- `failed`: immediate terminal failure (including degraded response, leak-guard block, queue/enqueue failure, or task exception).
- `failed` with stale-timeout summary remains as a safety fallback if a run never reaches terminal reconciliation.

Retry metadata (feature builds with auto-retry enabled):
- Build run records include retry context: `attempt_count`, `max_attempts`, `retry_state`, `next_retry_at`, `last_failure_reason`.
- `running` + `retry_state=scheduled` means a retry is queued for `next_retry_at`.
- `retry_state=exhausted` means retry budget was consumed and the run is terminally failed.

Empty/error states:
- `No thread attached yet` when run has no `thread_id` yet.
- `Build has not produced messages yet` when thread history is still empty.
- Retry action on message fetch error.

## Related Docs

- `docs/api-usage-guide.md`
- `docs/api-reference.md`
- `docs/runbook.md`
