# Architecture

## Runtime Topology

- API process: FastAPI app in `src/jarvis/main.py`.
- Task execution: in-process asyncio runner in `src/jarvis/tasks/runner.py`.
- State store: SQLite (`APP_DB`, default local file).
- Optional frontend: React/Vite web app under `web/`, served by Vite in dev and by FastAPI static mount when `web/dist` exists.

## Core Request Flow

1. Incoming webhook (WhatsApp or generic webhook) hits API route.
2. Request is validated, deduped, and persisted (`src/jarvis/db/queries.py`).
   - WhatsApp inbound path auto-heals stale `whatsapp_thread_map` rows (orphaned `thread_id`)
     before message insert, preventing webhook `500` from FK failures.
3. `channel.inbound` event is emitted.
4. In-process task runner dispatches `agent_step`.
5. Orchestrator builds prompt from agent bundle + thread context + memory.
6. Provider router executes primary/fallback model call.
7. Tool calls run through policy-gated runtime (`deny-by-default`).
8. Assistant response is persisted; state extraction is queued as a background task (`jarvis.tasks.memory.extract_thread_state`) and outbound channel task is scheduled in-process.
9. Final assistant output is guarded before persistence to block leaked internal planning/tool payload text; blocked output emits `agent.response.leak_blocked`.
10. Repeated failing tool calls are suppressed within a step (`tool.call.suppressed`) to reduce failure loops.
11. Roadmap-write success claims are blocked unless a verified write result exists in-step; blocked claims emit `agent.response.claim_blocked`.
12. Build-request terminal responses that remain progress-only emit `agent.response.incomplete` and are treated as retryable feature-build failures.

## Scheduler Flow

1. `scheduler_tick` evaluates due windows from `schedules`.
2. Catch-up uses global `SCHEDULER_MAX_CATCHUP` with per-schedule override.
3. Idempotency is enforced by `schedule_dispatches(schedule_id, due_at)` uniqueness.
4. `schedule.trigger` and catch-up telemetry events are emitted.

## Follow-Up Heartbeat Flow

1. Opt-in state is stored per thread in `thread_followups`.
2. Periodic task `jarvis.tasks.followups.followup_heartbeat_tick` scans enabled/open threads.
3. Threads with active attempts or recent activity are skipped (`followup.skipped`).
4. A compact evaluator produces strict JSON action (`reply` or `no_reply`).
5. `no_reply` updates state and emits `followup.no_reply` without outbound message.
6. `reply` persists an assistant message, enqueues channel send (non-web), and emits `followup.sent`.

## Human Escalation Flow

1. Agents request escalation via `request_human_escalation` (main-agent-only policy gate).
2. Request rows are persisted in `human_escalations` with status `queued` and event `human.escalation.requested`.
3. Dispatcher task resolves configured targets (`HUMAN_ESCALATION_CHANNEL_TYPE` + `HUMAN_ESCALATION_TARGETS`) into channel threads.
4. Dispatcher persists an escalation assistant message on the target thread and enqueues channel send.
5. Success/failure is recorded via `human.escalation.dispatch.end|failed` and persisted status updates.

## Orchestrator Reliability Hardening

1. Embedded tool payload parsing supports `tool_calls`, `tool+tool_input`, and `tool_name+arguments` JSON shapes in assistant text.
2. Provider router short-circuits to fallback when primary provider reports active quota cooldown.
3. Per-thread memory extraction uses task-level backoff after timeout/quota failures and emits `state.extraction.skipped` during active backoff windows.
4. Model run events annotate primary cooldown bypass with `primary_skipped_due_to_cooldown=true`.
5. Typed roadmap mutation tool (`create_feature_request`) returns verified write IDs and emits `roadmap.write.verified` / `roadmap.write.failed`.
6. Feature-build traces cap repeated identical tool-call signatures and emit `tool.call.loop_cap_reached` before terminal synthesis fallback.
7. Feature-build finalization emits `feature.build.terminal_synthesis` and enforces a deliverable gate (diff/no-op blockers + protected-path checks) before success.
8. Repeated consecutive `placeholder_response_after_tool_loop` outcomes fail fast via `feature.build.retry.denied` instead of consuming all retry slots.

## Agent Run Reliability Flow

1. `agent_step` creates a durable attempt row in `agent_run_attempts` before orchestration starts.
2. The orchestrator reports phase transitions (`state.extract`, `model.run`, `tool.exec`, `finalize`) to keep attempt heartbeats current.
3. Retryable failures are recorded and retried with bounded exponential backoff.
4. A periodic reaper task scans stale `running` attempts and requeues recovery attempts when under the max-attempt budget.
5. Trace-scoped success dedupe is enforced so only one successful attempt publishes the final result for a given `trace_id`.

## Runtime Stall Detection and Recovery Flow

1. A periodic watchdog (`watchdog_stall_check`) compares the age of latest inbound events to any subsequent system progress (outgoing messages or intermediate non-system events).
2. If inbound traffic exists but the system stalls beyond a configured threshold (`stall_detect_threshold_seconds`, default 90s), a stall is declared.
3. The system emits an explicit `runtime.stall.detected` event.
4. The system self-heals by actively triggering an `enqueue_restart` with `runtime.recover.start` and `runtime.recover.end` emissions.
5. A cooldown period (`stall_recovery_cooldown_seconds`, default 600s) acts as a safety measure preventing runaway restart loops.

## Self-Update Flow

1. Propose patch -> persist metadata.
2. Validate evidence contract (`file_refs`, `line_refs`, `policy_refs`, invariants).
3. Validate patch format + protected paths + `git apply --check`.
4. Deterministic replay check from recorded `baseline_ref`.
5. Test in temporary worktree (profile-dependent smoke suite).
   - Optional sandbox mode (`SELFUPDATE_SANDBOX_ENABLED=1`) runs smoke commands in Docker (`--read-only`, `--network=none`, constrained CPU/memory).
   - Sandbox diff metadata is persisted under `artifact.json["sandbox"]` and exposed via `GET /api/v1/selfupdate/patches/{trace_id}/sandbox`.
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

- Session tokens map to `UserContext(user_id, role, scopes, is_admin)`.
- CBAC scope model:
  - `*` grants all scopes.
  - Exact match grants one capability (for example `media:read`).
  - Namespace wildcard grants a family (`memory:*` -> `memory:read`, `memory:write`, etc.).
- Restricted delegation tokens are minted via `mint_restricted_token(...)` and carry a short TTL plus explicit scope set.
- Admin-only areas include lockdown controls, permissions, and self-update approvals.
- Non-admin users are ownership-scoped for thread-linked resources.
- WebSocket thread subscriptions enforce thread ownership for non-admin users.
- Tool runtime policy includes scope gate `R9` (`cbac.scope_denied`) that intersects token scopes with allowed tool mappings before execution.

## Media Attachment Architecture

- Unified attachment table: `media_attachments` (`062_media_attachments.sql`) with `mda_` IDs.
- Inbound channel media (WhatsApp/Telegram) writes to both channel-specific paths and unified attachment storage.
- Message-list API enriches each message with a `media` array (`id`, `url`, `mime_type`, `thumbnail_url`, `size_bytes`) using a batched attachment lookup by `message_id`.

## Memory Vector Runtime

- `MemoryService` maintains runtime vector virtual tables (`memory_vec_index`, `event_vec_index`) plus mapping tables (`memory_vec_index_map`, `event_vec_index_map`) for rowid joins to durable IDs.
- Map row creation is concurrency-safe by design:
  - memory map upsert uses `INSERT OR IGNORE` + subsequent rowid lookup.
  - event map upsert uses `ON CONFLICT(event_id) DO UPDATE` to keep `thread_id` current.
- Vector backfill is best-effort and non-fatal: per-row map integrity conflicts are logged and skipped so background indexing continues under concurrent writes.
- Background task `proactive_reflection` runs every 6 hours (configurable) to synthesize `worldview` and `insight` state items from recent activity, prune low-importance state rows, and emit `memory.reflection.run` events that record how many insights/prunes happened per thread.
- `state_items` now includes `insight`/`worldview` type tags so the renderer and orchestrator prompts can surface higher-level context updates supplied by reflection runs.

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

- `docs/README.md`
- `docs/codebase-tour.md`
- `docs/configuration.md`
- `docs/change-safety.md`
- `docs/runbook.md`
- `docs/api-reference.md`
