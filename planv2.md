# SPEC-001 Agent Framework MVP - Plan V2

## 1) Scope and Non-Goals

### In Scope (MVP)
- Multi-agent runtime with a single user-facing Main Agent.
- WhatsApp Cloud API as the first channel.
- Worker agents: `researcher`, `planner`, `coder`.
- Async orchestration via FastAPI + Celery + RabbitMQ.
- Event-sourced observability with trace propagation.
- Memory retrieval using SQLite + Ollama embeddings with sqlite-vec runtime indexing.
- Cron scheduling for one-off and recurring tasks.
- Controlled self-update pipeline with safety gates and auto-rollback.

### Out of Scope (MVP)
- Human approval UI/workflow engine (command-line/admin table only).
- Additional channels (Slack/Telegram/Web/Email).
- Streaming responses to WhatsApp.
- Full browser automation.

## 2) Architecture Decisions (Final)

- Build scope: Full MVP in one pass.
- Python runtime: 3.12.x.
- Tooling: `uv` + `pyproject.toml`.
- Package root: `src/jarvis/`.
- Primary LLM provider: Google Gemini API with OAuth and token refresh.
- Fallback LLM provider: local SGLang (OpenAI-compatible API) using `openai/gpt-oss-120b`.
- Tool calling: native function-calling/tool schema for both providers.
- Embeddings: Ollama `nomic-embed-text` (768 dimensions).
- Data store: single SQLite file `app.db` with JSON vector storage plus sqlite-vec runtime indexes.
- Dev infra: Docker Compose for RabbitMQ, Ollama, SearXNG, SGLang.
- Delegation: model-directed via tool-based routing.
- Agent communication: asynchronous, fire-and-forget with completion notification to Main Agent.
- Self-update policy:
  - Dev: auto-apply allowed when gates pass.
  - Prod: requires explicit admin approval record before apply.
- Deployment targets:
  - Dev: `~/jarvis`
  - Prod: `/srv/agent-framework` with systemd.

## 3) Repository Layout

```
~/jarvis/
├── pyproject.toml
├── docker-compose.yml
├── Makefile
├── .env.example
├── planv2.md
├── src/jarvis/
│   ├── __init__.py
│   ├── main.py
│   ├── celery_app.py
│   ├── config.py
│   ├── ids.py
│   ├── logging.py
│   ├── db/
│   │   ├── connection.py
│   │   ├── queries.py
│   │   └── migrations/
│   │       ├── runner.py
│   │       ├── 001_initial.sql
│   │       ├── 002_memory.sql
│   │       ├── 003_sessions.sql
│   │       ├── 004_policy.sql
│   │       └── 005_scheduler.sql
│   ├── models/
│   ├── routes/
│   ├── agents/
│   ├── orchestrator/
│   ├── providers/
│   ├── tools/
│   ├── memory/
│   ├── scheduler/
│   ├── events/
│   ├── channels/
│   ├── policy/
│   ├── selfupdate/
│   ├── tasks/
│   └── commands/
├── agents/
├── deploy/
└── tests/
```

## 4) Version and Compatibility Matrix

### Runtime and Libraries
- Python: `>=3.12,<3.13`
- fastapi: `0.116.1`
- uvicorn[standard]: `0.35.0`
- celery: `5.5.3`
- pydantic: `2.11.7`
- pydantic-settings: `2.11.0`
- httpx: `0.28.1`
- python-dotenv: `1.1.1`
- pytest: `8.4.2`, pytest-asyncio: `1.2.0`, ruff: `0.12.12`, mypy: `1.17.1`
- sqlite-vec: loaded as SQLite extension from `SQLITE_VEC_EXTENSION_PATH`, pinned by deployed binary artifact.

### Infrastructure Images
- `rabbitmq:4-management-alpine`
- `ollama/ollama:0.11.4`
- `searxng/searxng:2026.1.10-a0`
- `lmsysorg/sglang:v0.6.5.post3-cu126`

### Platform Compatibility
- Linux x86_64 required for prod.
- GPU required for SGLang and recommended for Ollama in dev/prod.
- If GPU unavailable, SGLang lane is disabled and router uses Gemini-only mode.
- SGLang production sizing decision: require `>=2x 80GB NVIDIA GPUs` (e.g., A100/H100 class) for `openai/gpt-oss-120b` lane with queue concurrency `1`.

## 5) Configuration Contract

All config is loaded via `pydantic-settings` from env.

### Required (Prod)
- `APP_ENV` (`dev|prod`)
- `APP_DB` (absolute path)
- `BROKER_URL`
- `RESULT_BACKEND`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REFRESH_TOKEN`
- `GEMINI_MODEL`
- `SGLANG_BASE_URL`
- `SGLANG_MODEL`
- `OLLAMA_BASE_URL`
- `OLLAMA_EMBED_MODEL`
- `SEARXNG_BASE_URL`
- `ADMIN_WHATSAPP_IDS` (comma-separated)
- `RABBITMQ_MGMT_URL`
- `RABBITMQ_MGMT_USER`
- `RABBITMQ_MGMT_PASSWORD`
- `BACKUP_S3_ENDPOINT`
- `BACKUP_S3_BUCKET`
- `BACKUP_S3_REGION`
- `BACKUP_S3_ACCESS_KEY_ID`
- `BACKUP_S3_SECRET_ACCESS_KEY`
- `PAGERDUTY_ROUTING_KEY`

### Required (Dev)
- Same as prod except prod-only secrets may be mocked for local integration tests.

### Optional with Defaults
- `LOG_LEVEL=INFO`
- `TRACE_SAMPLE_RATE=1.0`
- `COMPACTION_EVERY_N_EVENTS=25`
- `COMPACTION_INTERVAL_SECONDS=600`
- `PROMPT_BUDGET_GEMINI_TOKENS=200000`
- `PROMPT_BUDGET_SGLANG_TOKENS=110000`
- `LOCKDOWN_DEFAULT=0`
- `SELFUPDATE_AUTO_APPLY_DEV=1`
- `SELFUPDATE_AUTO_APPLY_PROD=0`
- `RESTART_COMMAND=systemctl restart jarvis-api jarvis-worker jarvis-scheduler`
- `ALERT_SLACK_WEBHOOK_URL=` (optional mirror notifications)

## 6) Data Model and Retention

### Core Tables
- `system_state`, `users`, `channels`, `threads`, `thread_settings`
- `messages`, `external_messages`
- `events`, `event_text`, `thread_summaries`
- `memory_items`, `memory_embeddings`, `memory_vec`
- `sessions`, `session_participants`, `v_session_timeline`
- `principals`, `tool_permissions`, `approvals`
- `schedules`

### Vector Tables
- `memory_vec(memory_id, vector_json)` for persisted vectors.
- `event_vec(id, thread_id, vector_json)` for persisted event vectors.
- sqlite-vec runtime index tables (`memory_vec_index*`, `event_vec_index*`) are created lazily when the extension is available.

### Retention Policy (MVP)
- Raw events/messages: retained indefinitely.
- Embeddings: retained indefinitely, re-indexed on model version change.
- Logs to stdout: external retention controlled by host log policy.

### DB Maintenance
- WAL mode enabled.
- `PRAGMA optimize` daily.
- `VACUUM` scheduled monthly during low traffic.
- Integrity check weekly (`PRAGMA integrity_check`).

## 7) Security and Secrets

### Secrets Management
- Dev: `.env` local only, never committed.
- Prod: systemd environment file owned by root with `0600` permissions.
- Token redaction at ingestion/log boundary.

### AuthN/AuthZ
- WhatsApp webhook verification enforced.
- Admin identity from `ADMIN_WHATSAPP_IDS` allowlist.
- Policy rules R1-R5 enforced in tool runtime and orchestrator.

### Protected Paths
- Deny writes to system/service directories by default.
- Allowlist application repo paths only.
- Self-update apply path constrained to repository root.

**Default allowlist** (agent can modify without admin approval):
- `/srv/agent-framework/**`
- `/srv/agent-state/**`
- `/srv/projects/**`
- `/etc/<app>/**` (via release directories and symlink swaps only)
- `/var/lib/agent/**`

**Protected paths** (admin approval required; MVP: disallow):
- `/etc/systemd/system/**`
- `/etc/sudoers`, `/etc/sudoers.d/**`
- `/etc/ssh/**`
- `/etc/*iptables*`, `/etc/nftables*`, firewall configs
- `/root/**`

### Lockdown Mode
- `system_state.lockdown=1` blocks:
  - `exec_host`
  - apply/restart actions
  - non-essential outbound integrations

**Automatic lockdown triggers:**
- 3 consecutive `/readyz` failures.
- 2 rollbacks within 30 minutes.
- Protected-file modification attempt.
- High `exec_host` failure rate.

When triggered: set `system_state.lockdown=1`, block `exec_host`, self-update apply, and config apply. Still allow `/status`, `/logs search ...`, and outbound alerts. Emits `lockdown.triggered` event.

**Admin override / recovery:**
- `/unlock <one-time-code>` clears lockdown.
- One-time code rotates every 10 minutes, written to `/var/lib/agent/admin_unlock_code`.
- Successful unlock emits `lockdown.cleared` event.

## 8) Observability, Traceability, and SLOs

### Trace Contract
Every ingress creates `trace_id`; each operation creates `span_id` and optional `parent_span_id`.

Required on all events:
- `id`, `trace_id`, `event_type`, `component`, `actor_type`, `actor_id`, `created_at`

### SLOs (MVP)
- Webhook ACK p95: `< 1.0s`
- End-to-end response p95 (normal load): `< 20s`
- `/healthz` uptime: `>= 99.0%` monthly
- `/readyz` false-negative rate: `< 1%`

### Capacity Targets (Initial)
- 10 concurrent active threads.
- 1000 events/hour sustained.
- SGLang queue concurrency: 1.

### Queue Limits and Backpressure
- Per-queue max length thresholds with alerts.
- If `local_llm` backlog exceeds threshold, router shifts low-priority tasks to Gemini.
- Alerting destination decision: PagerDuty (Events API v2) is primary; optional Slack webhook mirror for non-paging notifications.

## 9) API and Tool Contracts

### HTTP Endpoints
- `GET /healthz` -> `200 {"ok": true}` when process alive.
- `GET /readyz` -> `200` only if DB, broker, provider lane checks pass.
- `GET /webhooks/whatsapp` -> verification handshake.
- `POST /webhooks/whatsapp` -> accepts inbound event, dedupes, enqueues work, returns `200/202` quickly.

### Provider Contract
```python
class ModelProvider(Protocol):
    async def generate(self, messages, tools=None, temperature=0.7, max_tokens=4096): ...
    async def health_check(self) -> bool: ...
```

### Tool Contract
```python
class ToolRuntime:
    async def execute(self, tool_name, arguments, caller_id, trace_id, thread_id=None): ...
```

### Session Tools

Agent-to-agent session tools available to the Main Agent (and optionally Admin). Worker agents route through Main Agent.

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'thread',
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_participants (
  session_id TEXT NOT NULL,
  actor_type TEXT NOT NULL,   -- user|agent
  actor_id TEXT NOT NULL,
  role TEXT NOT NULL,         -- main|worker|user
  PRIMARY KEY(session_id, actor_type, actor_id),
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_session_participants_actor
  ON session_participants(actor_type, actor_id);

CREATE VIEW IF NOT EXISTS v_session_timeline AS
SELECT
  t.id            AS session_id,
  m.created_at    AS created_at,
  m.role          AS role,
  NULL            AS event_type,
  NULL            AS component,
  NULL            AS actor_type,
  NULL            AS actor_id,
  m.id            AS message_id,
  NULL            AS event_id,
  m.content       AS content
FROM threads t
JOIN messages m ON m.thread_id = t.id
UNION ALL
SELECT
  e.thread_id     AS session_id,
  e.created_at    AS created_at,
  'event'         AS role,
  e.event_type    AS event_type,
  e.component     AS component,
  e.actor_type    AS actor_type,
  e.actor_id      AS actor_id,
  NULL            AS message_id,
  e.id            AS event_id,
  json_extract(e.payload_redacted_json, '$.text') AS content
FROM events e
WHERE e.thread_id IS NOT NULL;
```

**Tool contracts:**

- `session_list(agent_id=None, status=None) -> [{session_id, participants, status, updated_at}]`
  - SQL: join `sessions` + `session_participants`, filter by agent/status.
- `session_history(session_id, limit=200, before=None) -> [{role, actor_id, content, created_at, event_id}]`
  - SQL: `SELECT * FROM v_session_timeline WHERE session_id=? ORDER BY created_at DESC LIMIT ?`
- `session_send(session_id, to_agent_id, message, priority='default') -> {event_id}`
  - Emits `agent.message` event, indexes it, enqueues `agent_step` for target agent.

### Prompt Builder and Context Budgeting

**Three-layer memory architecture** per `thread_id`:
1. **Raw log** (infinite): all messages/events stored forever in `events`.
2. **Chunked memory**: messages/events chunked into retrievable units (vector indexed via `event_vec`).
3. **Rolling summaries**: `thread_summary_short` (~2-4k tokens), `thread_summary_long` (~20-40k tokens), optional per-topic summaries.

**Budget profiles per provider:**
- `gemini`: large budget — include more retrieved raw chunks.
- `sglang`: tight budget — rely more on summaries + top-k retrieval.

**Assembly order:**
1. Agent system context (identity/soul).
2. Thread summaries (short always, long if budget allows).
3. Top-k retrieved chunks from `event_vec` (scoped + time-aware).
4. Recent conversation tail (last M turns).

**Retrieval blending:**
- 70% semantic top-k.
- 30% recent-time decay.
- Always scope by `thread_id` and `user_id` unless querying shared KB.

**Compaction trigger conditions:**
- Every N messages/events (e.g., 25).
- When `prompt_builder` estimates context pressure for target model.
- On schedule (e.g., every 10 minutes).
- `/compact` triggers `compact_thread(thread_id)` immediately.

### WhatsApp Channel: Ingestion and Outbound Flow

**Webhook verification:**
```python
@router.get("/webhooks/whatsapp")
async def whatsapp_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="verification failed")
```

**Webhook ingestion flow:**
1. Early exit if `system_state.restarting`.
2. Emit `channel.inbound.batch` event.
3. For each message: dedupe by `external_messages(channel_type, external_msg_id)`.
4. Ensure user/channel/thread via `ensure_user()`, `ensure_channel()`, `ensure_open_thread()`.
5. Persist `messages` row + `channel.inbound` event.
6. Enqueue `index_event` on `tools_io` and `agent_step` on `agent_priority`.

**Dedupe table:**
```sql
CREATE TABLE IF NOT EXISTS external_messages (
  id TEXT PRIMARY KEY,
  channel_type TEXT NOT NULL,
  external_msg_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(channel_type, external_msg_id)
);
CREATE INDEX IF NOT EXISTS idx_external_messages_trace
  ON external_messages(trace_id);
```

**Outbound flow:**
- Main Agent's final response persisted as `messages` row (role=assistant).
- `channel.outbound` event emitted.
- Celery task `send_whatsapp_message(thread_id, message_id)` enqueued on `tools_io`.
- Task calls WhatsApp Cloud API: `POST https://graph.facebook.com/v21.0/{phone_number_id}/messages`.
- Retries: 3 attempts with exponential backoff + jitter on 5xx/429.

### Orchestrator Step Loop and Delegation

**Pseudocode for `agent_step` task:**
```
1. Load agent settings (thread_settings, active agents)
2. Check for command prefix → execute command, skip LLM
3. Build prompt:
   - identity/soul context
   - thread summaries
   - top-k retrieval (budget-aware)
   - conversation tail
4. Call model router → provider.generate()
5. Process tool calls in loop (capped iterations):
   - Execute tool via ToolRuntime
   - Append result to messages
   - Re-call model if more tool calls
6. If delegation needed: call session_send(session_id, to_agent_id, message)
7. Emit agent.step.end event
```

**Worker completion flow:**
- Worker emits `agent.step.end` event.
- Worker calls `session_send(session_id, to_agent_id="main", message=result)` which emits `agent.message` event and enqueues `agent_step` for main agent.
- Main agent sees the worker's response in its next step via session history.
- Fire-and-forget with notification — not synchronous.

### Host Execution Tool

**Contract:**
```
exec_host(command: str, cwd: str|None = None, env: dict|None = None, timeout_s: int = 120)
  -> {exit_code: int, stdout: str, stderr: str}
```

**Rules:**
- Blocked when `system_state.lockdown=1` or `system_state.restarting=1`.
- Every call emits `host.exec.start` (command verbatim + redacted) and `host.exec.end` (exit code + truncated output).
- Output truncation: max 32KB each for stdout/stderr; full output stored at `/var/lib/agent/exec/<event_id>.log`.
- Environment sanitation: default env is empty + allowlisted variables; never pass secrets unless explicitly required.

**Constraint examples:**
- Max timeout enforced.
- Deny patterns (e.g., `rm -rf /`).
- Require admin approval for `sudo` operations.

### Event Naming Contract
Mandatory event families:
- `channel.inbound`, `channel.outbound`
- `agent.step.start`, `agent.step.end`, `agent.delegate`
- `tool.call.start`, `tool.call.end`
- `model.run.start`, `model.run.end`, `model.fallback`
- `schedule.trigger`
- `self_update.propose`, `self_update.validate`, `self_update.test`, `self_update.apply`, `self_update.rollback`
- `command.executed`

## 10) Failure-Mode Playbooks

### Provider Failures
- Gemini down/auth error: emit `model.fallback`, route to SGLang if healthy.
- SGLang down: route to Gemini and throttle tasks tagged local-only.
- Both down: return graceful failure to user, keep task state retryable.

### RabbitMQ Unavailable
- `/readyz` fails.
- Ingress returns `202` with degraded status event.
- Retry connection with exponential backoff.

### Ollama/Embedding Unavailable
- Continue primary chat path.
- Mark retrieval degraded and skip semantic retrieval.
- Queue re-index jobs for later replay.

### WhatsApp API Errors
- Retry transient 5xx/429 with jitter.
- Record dead-letter event after max retries.

### DB Lock/Corruption
- Lock contention: bounded retries and write queueing.
- Corruption: switch to read-only safe mode, alert, restore from latest backup.

## 11) Migration and Schema Governance

### Migration Rules
- Migrations are strictly ordered and immutable once applied.
- Forward-only in prod.
- Down migrations optional and dev-only.

### Release Rules
- New code must run against current and next schema during rollout window.
- Migration runner acquires global lock table row before applying.
- Failed migration aborts startup and leaves previous schema intact.

## 12) Self-Update Governance

### State Machine
`proposed -> validated -> tested -> approved (prod only) -> applied -> verified`

### Safety Gates
- Unit tests pass.
- Integration smoke subset passes.
- `ruff` and `mypy` pass.
- `/readyz` healthy after restart.

### Rollback Rules
- If post-apply `/readyz` fails N checks in window, auto-rollback to last-known-good tag.
- Rollback emits `self_update.rollback` and re-enables previous systemd units.

## 13) Phase Plan with Definition of Done

### Phase 0: Scaffolding
Deliver:
- project files, package structure, FastAPI app, Celery app, config, logging, db connection, migration runner, SQL migrations.
DoD:
- `uv sync` succeeds.
- `uv run uvicorn jarvis.main:app --reload` boots.
- `GET /healthz` returns 200.

### Phase 1: Event System + DB Core
Deliver:
- `emit_event`, event models, core query functions.
DoD:
- one integration test verifies event write with trace propagation.

### Phase 2: Agent Loader + Registry
Deliver:
- loader, registry, base protocol, 4 agent bundles.
DoD:
- startup discovers all agents; missing required markdown fails fast with clear error.

### Phase 3: Providers + Router
Deliver:
- provider interfaces and router fallback logic.
DoD:
- tests validate primary success, fallback on failure, both-fail behavior.

### Phase 4: Tool System
Deliver:
- tool decorator, registry, runtime, permission enforcement, audit events.
DoD:
- tests validate allowed, denied, malformed args, timeout handling.

### Phase 5: Memory + Embeddings
Deliver:
- embedder and memory service write/search.
DoD:
- round-trip semantic search test with sqlite-vec.

### Phase 6: Orchestrator + Prompt Builder
Deliver:
- agent-step loop, context budgeting, compaction triggers.
DoD:
- tests validate tool-call loop cap, delegation path, budget clipping.

### Phase 7: Celery Tasks
Deliver:
- all task modules wired to queues.
DoD:
- integration test enqueues and processes `agent_step` and `scheduler_tick`.

### Phase 8: WhatsApp Channel + Routes
Deliver:
- webhook verification, ingest, outbound sender.
DoD:
- mocked webhook end-to-end test from inbound to outbound event emission.

### Phase 9: Commands + Policy Engine
Deliver:
- parser, handlers, R1-R5 enforcement.

**Command implementation details:**
- `/status`: provider health (Gemini auth, SGLang reachable) + RabbitMQ mgmt API queue depths (`messages_ready`, `messages_unacknowledged`) + active agents for thread.
- `/new`: close current thread, create new `threads` row.
- `/compact`: enqueue `compact_thread(thread_id)`.
- `/verbose on|off`: update `thread_settings.verbose`.
- `/group on|off <agent_id>`: update `thread_settings.active_agent_ids_json`.
- `/restart`: admin-only, set `system_state.restarting=1`, execute drain protocol (wait for priority tasks, revoke remaining, flush DB, systemctl restart).
- `/unlock <code>`: admin override for lockdown. One-time codes rotate every 10 min, stored at `/var/lib/agent/admin_unlock_code`.
- `/logs search <query>`: semantic search over `event_vec` embeddings (sqlite-vec index when available, cosine fallback otherwise), returns top-k events with timestamps.
- `/logs trace <trace_id>`: SQL filter `SELECT * FROM events WHERE trace_id=? ORDER BY created_at ASC`.

DoD:
- tests for `/status /new /compact /verbose /restart /group /logs` and admin gating.

### Phase 10: Scheduler
Deliver:
- cron evaluation and scheduled trigger execution.
DoD:
- time-frozen tests validate due job dispatch and idempotency.

### Phase 11: Self-Update Pipeline
Deliver:
- propose/validate/test/apply/restart/rollback pipeline.

**Celery task contracts:**
- `self_update_propose(trace_id, repo_path, patch_text, rationale)`:
  - Emits `self_update.proposed`.
  - Writes patch to `/var/lib/agent/patches/<trace_id>.diff`.
- `self_update_validate(trace_id)`:
  - Parses patch, checks allowed paths, ensures clean apply (dry-run).
  - Emits `self_update.validated` or `self_update.rejected`.
- `self_update_test(trace_id)`:
  - Runs `ruff` + `pytest` in repo working tree.
  - Emits `self_update.test.passed` or `self_update.test.failed`.
- `self_update_apply(trace_id)`:
  - Creates branch `auto/<timestamp>`, applies patch, commits.
  - Triggers `system_restart(trace_id)`.
  - Emits `self_update.applied` or `self_update.apply_failed`.

**Queue routing:** all self-update tasks → `agent_default`; any local model use → `local_llm`.

DoD:
- simulated bad deploy triggers automatic rollback and recovery.

### Phase 12: Deploy Artifacts
Deliver:
- systemd units, healthcheck, rollback scripts, deploy docs.
DoD:
- production-like VM can install, start, and pass `/readyz` with one command sequence.

## 14) Test Strategy and Quality Gates

### Required Test Suites
- Unit: core logic and pure services.
- Integration: DB + Celery + mocked externals.
- Contract tests: webhook payload parsing, provider response normalization.

### Minimum Quality Gates (merge to main)
- `uv run ruff check src/ tests/`
- `uv run mypy src/`
- `uv run pytest tests/unit/ -q`
- `uv run pytest tests/integration/ -q`
- Coverage: `>=80%` for `src/jarvis/orchestrator`, `src/jarvis/policy`, `src/jarvis/tools/runtime`.

## 15) Backup, Restore, and DR

### Backup Plan
- SQLite hot backup every 15 minutes to local snapshot.
- Hourly encrypted copy to remote S3-compatible object storage.
- Remote backup target decision: Cloudflare R2 (`jarvis-prod-backups` bucket, region `auto`, endpoint from `BACKUP_S3_ENDPOINT`).
- Keep: 24 hourly, 14 daily, 8 weekly.

### Restore Plan
- `restore_db.sh <snapshot>` script restores to staging path.
- Run integrity check.
- Promote restored DB after `/readyz` and smoke tests pass.

### DR Target
- RPO: 15 minutes.
- RTO: 60 minutes.

## 16) Operational Runbooks

### Runbook: Normal Start (Dev)
1. `make dev`
2. `make api`
3. `make worker`
4. verify `/healthz` and `/readyz`.

### Runbook: Controlled Restart
1. admin issues `/restart`
2. set `system_state.restarting=1`
3. drain queues up to timeout
4. restart workers and API
5. clear restart flag and verify readiness

### Runbook: Lockdown
1. set `system_state.lockdown=1`
2. verify risky tools blocked
3. investigate and clear flag when safe

## 17) Milestones and Exit Criteria

- M1 Scaffolding complete
- M2 Event + DB core complete
- M3 Worker runtime complete
- M4 Provider router complete
- M5 Memory complete
- M6 Orchestrator complete
- M7 WhatsApp channel complete
- M8 Commands + policy complete
- M9 Scheduler complete
- M10 Self-update complete
- M11 Deploy complete

Release exit criteria:
- All DoD items met.
- Quality gates green.
- `/readyz` stable for 24h soak in staging.
- Backup/restore drill executed successfully.

## 18) Implementation Details: Previously Unspecified Areas

### Tool Permission Defaults
- Default policy: **deny all** (zero-trust).
- Each agent's `identity.md` declares allowed tools → loaded into `tool_permissions` at startup.
- Unknown tools are denied with `policy.decision` event logged.

### Redaction Rules
- Sensitive fields: OAuth tokens, WhatsApp access tokens, phone numbers (last 4 digits preserved), API keys, passwords.
- Algorithm: regex-based pattern matching at ingestion boundary + explicit field tags in event schema.
- `payload_json` stored verbatim; `payload_redacted_json` stored alongside with patterns replaced by `[REDACTED]`.

### Dead-Letter Handling
- Max retries: 3 (configurable per task).
- Backoff: exponential with jitter (2s, 8s, 32s base).
- After max retries: emit `task.dead_letter` event, persist to `events` table, no further automatic retry.
- Dead letters surfaced via `/logs search` and `/status`.

### Heartbeat Update Semantics
- File-based: `agents/<agent_id>/heartbeat.md` on disk.
- Updated at end of each `agent_step`: current goals, last action summary, timestamp.
- Concurrency: agents run one step at a time per thread (Celery task serialization), no concurrent writes.
- Format: markdown with YAML frontmatter for machine-readable fields.

## 19) Open Decisions (Must Resolve Before Production)

- None. All previously open decisions are resolved in this revision:
  - Runtime/library and image pins: Section 4.
  - SGLang GPU sizing: Section 4 (Platform Compatibility).
  - Backup target: Section 15 (Backup Plan).
  - Alerting destination: Section 8 (Queue Limits and Backpressure).

## 20) Changelog from Plan V1

- Removed duplicated sections and numbering inconsistencies.
- Unified provider terminology to Gemini API (not Gemini CLI).
- Resolved self-update policy contradiction (dev auto-apply vs prod approval).
- Standardized code paths to `src/jarvis/*`.
- Added explicit config contract and required env vars.
- Added SLO/capacity targets and queue backpressure behavior.
- Added failure playbooks, migration governance, and DR policy.
- Added phase-by-phase Definition of Done and quality gates.
- Merged implementation details from plan v1: session tools (SQL schema + tool contracts), prompt builder & context budgeting, WhatsApp ingestion/outbound flow, orchestrator step loop & delegation, `exec_host` tool contract, command implementation details, lockdown triggers & recovery, self-update Celery task contracts, protected path allowlist/denylist.
- Resolved 6 previously unspecified areas: worker agent completion flow, tool permission defaults, redaction rules, WhatsApp outbound implementation, dead-letter handling, heartbeat update semantics.
- Retired legacy `plan.md` from active development docs.
