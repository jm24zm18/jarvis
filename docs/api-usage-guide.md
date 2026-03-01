# API Usage Guide

Human-oriented guide for common API workflows. For complete endpoint inventory, use `docs/api-reference.md`.

## Auth and Session Flow

1. Login: `POST /api/v1/auth/login`
2. Read current user: `GET /api/v1/auth/me`
3. Logout: `POST /api/v1/auth/logout`

Web UI uses an HTTP-only `jarvis_session` cookie for authenticated requests.
Bearer headers remain supported for compatibility and CLI/test flows.
`external_id` in login payload is no longer supported and returns `422`.

## Provider Config Flow (Admin)

- Read config: `GET /api/v1/auth/providers/config`
- Update config: `POST /api/v1/auth/providers/config`
- Read provider model catalogs: `GET /api/v1/auth/providers/models`

Provider config response includes:
- `primary_provider`, `fallback_provider`, `openrouter_model`, `sglang_model`, `lmstudio_model`, `lmstudio_base_url`
- `openrouter_api_key_set` (boolean)
- `openrouter_api_key_masked` (masked preview only; raw key is never returned)
- `lmstudio_api_key_set` (boolean)
- `lmstudio_api_key_masked` (masked preview only; raw key is never returned)

Provider update payload supports:
- `primary_provider` (`openrouter`, `sglang`, or `lmstudio`)
- `fallback_provider` (`openrouter`, `sglang`, or `lmstudio`, must differ from primary)
- `openrouter_model`
- `sglang_model`
- `lmstudio_model`
- `lmstudio_base_url`
- `openrouter_api_key` (set/replace when non-empty)
- `clear_openrouter_api_key` (explicit clear)
- `lmstudio_api_key` (set/replace when non-empty)
- `clear_lmstudio_api_key` (explicit clear)

Validation and constraints:
- `primary_provider` and `fallback_provider` must each be one of `openrouter|sglang|lmstudio`.
- `fallback_provider` must differ from `primary_provider`.
- If only `primary_provider` is updated and existing fallback is invalid/equal, fallback is auto-resolved.
- Invalid provider choices return `400`.

Runtime behavior:
- Provider saves apply to live API runtime immediately for provider env keys.
- Assistant output is sanitized to remove model control wrappers (for example `<|analysis|>` and leaked `<think>...</think>` blocks) before user-facing delivery.

## Thread and Message Flow

1. List threads: `GET /api/v1/threads`
2. Create a web thread: `POST /api/v1/threads`
3. Post message: `POST /api/v1/threads/{thread_id}/messages`
4. Read message history: `GET /api/v1/threads/{thread_id}/messages`

All authenticated sessions are treated as the root admin identity.

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

## DevSwarm Tasks

- List tasks: `GET /api/v1/swarm/tasks`
- Create task: `POST /api/v1/swarm/tasks`
- Nudge worker: `POST /api/v1/swarm/tasks/{task_id}/nudge`
- Cleanup task: `POST /api/v1/swarm/tasks/{task_id}/cleanup`

Create payload:
- `description` (required)
- `task_type` (`feature|bugfix|refactor`)
- `model` (optional)

Cleanup payload:
- `remove_worktrees` (optional, default `false` in API/UI)

Notes:
- Task creation always uses the current Jarvis workspace repository path.
- Task rows include deterministic gate/check payload under `checks`.
- System WebSocket subscribers receive `system.swarm.*` events for create/update/nudge/cleanup/tick updates.

## Follow-Up Heartbeats

- Enable thread follow-ups: `POST /api/v1/followups/threads/{thread_id}/enable`
- Disable thread follow-ups: `POST /api/v1/followups/threads/{thread_id}/disable`
- Read thread follow-up status: `GET /api/v1/followups/threads/{thread_id}`

Follow-up management is available to authenticated root-admin sessions.

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

`GET /api/v1/system/status` includes:
- `system`: persisted system state (including lockdown status/reason).
- `providers`: provider health payload plus `primary_name` and `fallback_name`.
- `provider_errors.last_primary_failure`: latest fallback reason from `model.fallback` events, when present.
- `queue_depths.in_flight`: in-process task runner in-flight count.
- `scheduler`: schedule backlog estimate.
- `stale_periodic_jobs`: stale periodic job list.

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
  Returns: { run_id, trace_id, feature_id, status, execution_mode, target_thread_id }

GET   /api/v1/feature-requests/{id}/build-runs  # admin only
  Returns: { items: [...], feature_id }

POST  /api/v1/feature-requests/{id}/build-runs/{run_id}/recover-children  # admin only
  Re-enqueues eligible failed child runs for a decomposed parent run.

GET   /api/v1/feature-requests?approval_status=pending|approved|rejected  # filter by approval
```

Build-runs payload fields include:
- `thread_id`: chat thread attached to the run (empty until assigned)
- `source_thread_id`: original feature-request thread that build routing prefers when configured
- `execution_mode`: `direct`, `decomposed`, or `fallback_split`
- `updated_at`: run row freshness timestamp (used by roadmap live monitor)

Child recovery endpoint response includes:
- `attempted`, `queued`, `skipped`, `errors`: aggregate recovery results.
- `items[]`: per-child action details (`queued`, `skipped`, `error`) with reasons/run IDs.

Idempotent create behavior:
- `POST /api/v1/feature-requests` dedupes retries when `trace_id` is provided and
  `title` + `trace_id` + `thread_id` + reporter match an existing feature row.
- Response includes `created` and `idempotent_hit` flags to indicate whether a new row was inserted.

## Approvals Center

```
GET  /api/v1/approvals              # admin only, filterable by action/status/target_ref
POST /api/v1/approvals              # admin only
  Body: { "action": "selfupdate.apply", "target_ref": "trc_...", "ttl_minutes": 30 }
  Allowed actions: selfupdate.apply, host.exec.shell, host.exec.script

POST /api/v1/approvals/{id}/revoke  # admin only
```

Active approval tokens consumed by `self_update_apply` are surfaced in the approvals center.

## Non-Web Reply Approval Gate

When `NON_WEB_REPLY_APPROVAL_REQUIRED=1`, assistant replies for non-web channels (for example WhatsApp/Telegram) are held pending until approved, unless an active sender+channel allow rule exists.

```
GET  /api/v1/channel-reply-approvals
POST /api/v1/channel-reply-approvals/{id}/approve   # Body: { "mode": "once"|"always" }
POST /api/v1/channel-reply-approvals/{id}/reject    # Body: { "reason": "..." }

GET  /api/v1/channel-reply-permissions
POST /api/v1/channel-reply-permissions/revoke       # Body: { "channel_type": "...", "recipient": "...", "reason": "..." }
```

Important behavior:
- There is currently no per-request fetch endpoint (`GET /api/v1/channel-reply-approvals/{id}` does not exist).
- Approval states include `pending`, `approved_once`, `approved_always`, `sent`, and `rejected`.
- `reject` is only valid while request status is `pending`.
- `approve` with `mode=always` creates an active sender+channel permission record.
- Invalid approve mode returns `{ "ok": false, "error": "mode must be 'once' or 'always'" }`.

Operational command shortcuts in chat:
- `/channel-approve-list [pending|sent|rejected|approved_once|approved_always]`
- `/channel-approve <request_id> once|always`
- `/channel-deny <request_id> [reason]`
- `/channel-allow-list [active|revoked]`
- `/channel-allow-revoke <channel_type> <recipient> [reason]`

Detailed workflow and payload examples: `docs/channel-reply-approvals.md`

## Related Docs

- `docs/api-reference.md`
- `docs/web-admin-guide.md`
- `docs/runbook.md`
