# Architecture

## Runtime Topology

- API process: FastAPI app in `src/jarvis/main.py`.
- Task execution: in-process asyncio runner in `src/jarvis/tasks/runner.py`.
- State store: SQLite (`APP_DB`, default local file).
- Optional frontend: React/Vite web app under `web/`, served by Vite in dev and by FastAPI static mount when `web/dist` exists.

## Core Request Flow

1. Incoming webhook (WhatsApp or generic webhook) hits API route.
2. Request is validated, deduped, and persisted (`src/jarvis/db/queries.py`).
3. `channel.inbound` event is emitted.
4. In-process task runner dispatches `agent_step`.
5. Orchestrator builds prompt from agent bundle + thread context + memory.
6. Provider router executes primary/fallback model call.
7. Tool calls run through policy-gated runtime (`deny-by-default`).
8. Assistant response is persisted and outbound channel task is scheduled in-process.

## Scheduler Flow

1. `scheduler_tick` evaluates due windows from `schedules`.
2. Catch-up uses global `SCHEDULER_MAX_CATCHUP` with per-schedule override.
3. Idempotency is enforced by `schedule_dispatches(schedule_id, due_at)` uniqueness.
4. `schedule.trigger` and catch-up telemetry events are emitted.

## Self-Update Flow

1. Propose patch -> persist metadata.
2. Validate evidence contract (`file_refs`, `line_refs`, `policy_refs`, invariants).
3. Validate patch format + protected paths + `git apply --check`.
4. Deterministic replay check from recorded `baseline_ref`.
5. Test in temporary worktree (profile-dependent smoke suite).
6. Admin approval -> apply patch.
7. Readiness watchdog and rollback path enforce safety gates.

## Web UI Architecture

- Entry router: `web/src/App.tsx`.
- Auth gate: protected routes check `/api/v1/auth/me` via token.
- Primary pages:
  - Chat: `web/src/pages/chat/index.tsx`
  - Admin dashboard: `web/src/pages/admin/dashboard/index.tsx`
  - Admin domains: agents, events, memory, schedules, threads, selfupdate, permissions, providers, bugs
- Real-time updates: WebSocket hub route `/ws` (`src/jarvis/routes/ws.py`) backed by `web_notifications` polling.

## Package Map

- `src/jarvis/agents/*`: agent bundle load/registry/seed and permission sync.
- `src/jarvis/auth/*`: auth dependencies, token/session validation, onboarding auth helpers.
- `src/jarvis/channels/*`: channel abstractions + WhatsApp + generic webhook entrypoints.
- `src/jarvis/cli/*`: CLI commands (`ask`, `chat`, `doctor`, `setup`, `skill`).
- `src/jarvis/commands/*`: slash-command parsing and handlers.
- `src/jarvis/config.py`: typed env contract + production validation.
- `src/jarvis/db/*`: connection layer, query helpers, SQL migrations.
- `src/jarvis/events/*`: event models and writer.
- `src/jarvis/memory/*`: thread memory, skills memory, knowledge base.
- `src/jarvis/models/*`: shared typed models.
- `src/jarvis/onboarding/*`: onboarding service logic.
- `src/jarvis/orchestrator/*`: agent-step loop + prompt assembly.
- `src/jarvis/plugins/*`: plugin interfaces and built-ins.
- `src/jarvis/policy/*`: policy decision engine and lockdown handling.
- `src/jarvis/providers/*`: model adapters and fallback router.
- `src/jarvis/routes/*`: HTTP and WebSocket route handlers.
- `src/jarvis/scheduler/*`: schedule evaluation and task enqueue.
- `src/jarvis/selfupdate/*`: propose/validate/test/apply/rollback pipeline.
- `src/jarvis/tasks/*`: task handlers + in-process runner registration.
- `src/jarvis/tools/*`: tool registry/runtime/implementations.
- `src/jarvis/ids.py`: ID generation conventions.
- `src/jarvis/logging.py`: logging configuration.
- `src/jarvis/errors.py`: shared error types.

## Auth and Authorization

- Session tokens map to `UserContext(user_id, role, is_admin)`.
- Admin-only areas include lockdown controls, permissions, and self-update approvals.
- Non-admin users are ownership-scoped for thread-linked resources.
- WebSocket thread subscriptions enforce thread ownership for non-admin users.

## Migration Ledger

- `020_user_roles.sql`: role columns and role backfill for existing users/sessions.
- `021_skill_packages.sql`: skill package metadata and install log table.
- `022_thread_compaction_threshold.sql`: configurable per-thread compaction threshold.
- `023_webhook_triggers.sql`: webhook trigger tables/contracts.

## Invariants

- ID prefixes are stable contract.
- Event type naming stays dot-separated.
- Tool policy remains deny-by-default.
- Migrations are append-only and ordered.

## Related Docs

- `docs/codebase-tour.md`
- `docs/configuration.md`
- `docs/change-safety.md`
- `docs/runbook.md`
