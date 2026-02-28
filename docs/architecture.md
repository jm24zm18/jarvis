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
5. Orchestrator builds prompt from agent bundle + a unified context builder (`orchestrator/context_builder.py`) that assembles summaries, structured state, semantic hits, KB snippets, skills, and optional user profile/KG facts.
   - Context assembly now resolves explicit `mem_*` references (ownership-scoped) and can add user-scoped cross-thread memory fallback hits when thread-local retrieval is sparse.
6. Provider router executes primary/fallback model call.
7. Tool calls run through policy-gated runtime (`deny-by-default`).
8. Assistant response is persisted; state extraction is queued as a background task (`jarvis.tasks.memory.extract_thread_state`) and outbound channel task is scheduled in-process.
9. When enabled and complexity threshold is met (tool-call count), orchestrator queues event-driven task lesson extraction (`jarvis.tasks.memory.post_task_knowledge_extraction`) and emits `knowledge.extraction.queued`.
9. For non-web channels, outbound assistant replies are approval-gated by default:
   - if sender+channel permission exists, dispatch proceeds;
   - otherwise a pending approval request is created and notification is posted to an admin web thread.
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
6. `reply` persists an assistant message, then applies the same non-web approval gate before any channel enqueue.

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
9. `memory_search` is available to `main` for explicit memory-ID/user-memory retrieval, aligned with CBAC `memory:read` tool mappings.

## Feature-build decomposition pipeline

- When `RLM_ENABLED` and `FEATURE_BUILD_USE_RLM` are both true, feature-build dispatch runs `_decompose_and_split` before starting implementation execution. The RLM service reads the feature spec, injects the most relevant context files (anchors + explicitly referenced paths), and calls the provider via `ProviderRouter` to produce a JSON plan with 3-6 atomic subtasks. Each subtask is validated against the injected context, allowed_paths, and acceptance-criteria heuristics; failures trigger a repair prompt up to the configured attempt limit.
- When RLM is disabled but `FEATURE_BUILD_AUTO_DECOMPOSE=1`, broad-scope features auto-trigger decomposition in forced mode instead of immediately returning `NEEDS_USER_GUIDANCE`.
- If decomposition still fails and `FEATURE_BUILD_DECOMPOSE_FALLBACK=1`, Jarvis uses deterministic layer-based fallback splitting (`web`, `api`, `db`, `skills`, `docs`, `tests`) and keeps subtasks one-layer-per-child when `FEATURE_BUILD_SUBTASK_LAYER_STRICT=1`.
- Successful decomposition or fallback-split inserts/updates `rlm_trajectories`, marks parent build run `decomposed`, and records `execution_mode` (`decomposed` or `fallback_split`) before enqueueing child feature builds. Duplicate decompositions remain guarded by `(feature_id, run_hash)`.
- The admin route `POST /api/v1/feature-requests/{id}/split` (admin-only + dry-run capable) remains available for manual recovery and operator-driven slicing.

## Isolated Feature Workspaces

- Feature builds create ephemeral workspaces under `FEATURE_ISOLATION_TMP_PREFIX` (default `/tmp/jarvis-feature-*`) and persist workspace metadata on each `feature_request_build_runs` row.
- Validation runs inside the clean clone before implementation (`uv sync --frozen`) and blocks execution if dependency snapshots drift.
- Build execution is dispatched as `feature_builder`, and isolated workspace write access is reserved for `feature_builder` only.
- Validation evidence (`validation_status`, log path, error summary, dependency snapshot digest) is persisted and optionally posted to synced GitHub feature issues.
- Build-run routing records both `source_thread_id` (request origin thread) and resolved `thread_id` (active build thread). `FEATURE_BUILD_THREAD_TARGET` controls whether run updates prefer reporter thread context (`reporter`, default) or admin web thread (`admin`).

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

## Provider Compatibility Layer

OSS models served via SGLang (e.g. `openai/gpt-oss-120b`) require the OpenAI-standard conversation format with:

1. `role: "assistant"` messages including a `tool_calls: [...]` array when tool calls were made.
2. Tool results delivered as `role: "tool"` messages with a matching `tool_call_id`, **not** as `role: "user"` with a `[tool_result]` prefix.

The compat layer is implemented across three modules:

- **`src/jarvis/providers/compat.py`**: `ProviderCompat` frozen dataclass holding per-provider behavioural flags (`tool_choice`, `parallel_tool_calls`, `strict_tool_schema`). Compat flags are wired per provider in the factory for OpenRouter, SGLang, and LM Studio.
- **`src/jarvis/providers/message_builder.py`**: Four helpers consumed by the orchestrator:
  - `build_assistant_message(text, tool_calls)` — builds an assistant dict with `tool_calls` array.
  - `build_tool_result_message(tool_call_id, content)` — builds a `role: "tool"` result dict.
  - `ensure_tool_ids(tool_calls)` — synthesises `spn_<uuid>` IDs for tool calls that omit them.
  - `inject_synthetic_errors_for_orphaned_calls(messages)` — two-pass scan that appends synthetic `role: "tool"` error entries for any assistant `tool_calls` entries that were never answered, preventing OSS models from looping on unacknowledged calls during terminal synthesis.
- **`src/jarvis/providers/factory.py`**: `_build_openrouter_compat` / `_build_sglang_compat` / `_build_lmstudio_compat` build `ProviderCompat` from settings (`SGLANG_PARALLEL_TOOL_CALLS`, `SGLANG_TOOL_CHOICE`, `OPENROUTER_TOOL_CHOICE`, `OPENROUTER_PARALLEL_TOOL_CALLS`, `LMSTUDIO_TOOL_CHOICE`, `LMSTUDIO_PARALLEL_TOOL_CALLS`) and pass them to provider constructors.

The orchestrator (`src/jarvis/orchestrator/step.py`) uses `ensure_tool_ids` + `build_assistant_message` before each tool-execution loop, and `build_tool_result_message` for all three tool-result append sites (suppressed duplicates, exception path, and normal success/error path).

## Package Map

- `src/jarvis/agents/*`: agent bundle load/registry/seed and permission sync.
- `src/jarvis/auth/*`: auth dependencies, token/session validation, onboarding auth helpers.
- `src/jarvis/channels/*`: channel abstractions + WhatsApp + generic webhook entrypoints.
- `src/jarvis/cli/*`: CLI commands (`ask`, `chat`, `doctor`, `setup`, `skill`).
- `src/jarvis/commands/*`: slash-command parsing and handlers.
- `src/jarvis/config.py`: typed env contract + production validation.
- `src/jarvis/db/*`: connection layer, query helpers, SQL migrations.
- `src/jarvis/events/*`: event models and writer.
- `src/jarvis/formatting/*`: shared human-display formatting helpers for CLI output.
- `src/jarvis/memory/*`: thread memory, skills memory, knowledge base.
- `src/jarvis/models/*`: shared typed models.
- `src/jarvis/onboarding/*`: onboarding service logic.
- `src/jarvis/orchestrator/*`: agent-step loop + prompt assembly.
- `src/jarvis/plugins/*`: plugin interfaces and built-ins.
- `src/jarvis/policy/*`: policy decision engine and lockdown handling.
- `src/jarvis/providers/*`: model adapters, fallback router, compat layer, and message builders.
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
- Reflection now also performs user-level cross-thread synthesis:
  - persists durable profile summaries in `user_profiles` (+ history in `user_profile_history`);
  - rate-limits profile synthesis via `user_reflection_watermarks` (max once per 24h/user);
  - optionally extracts user-scoped KG triples into `knowledge_graph` when `MEMORY_GRAPH_ENABLED=1`.
- Event-driven task lesson extraction writes operational facts to `knowledge_graph` with `extraction_type='task_lesson'` (distinct from periodic `profile` synthesis), tracks `source_trace_id`, and emits `knowledge.extraction.complete`.
- Task lesson extraction is best-effort and rate-limited via per-user daily cap + per-thread cooldown to prevent extraction churn on marathon sessions.
- State extraction watermark rows now carry lifecycle status (`idle|running|failed|skipped`) and status timestamps/error metadata for operational observability.
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
