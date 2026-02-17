# Codebase Tour

## Entry Points

- API bootstrap: `src/jarvis/main.py`
- Task runtime: `src/jarvis/tasks/runner.py`
- CLI entry: `src/jarvis/cli/main.py`

## Package Walkthrough

### `agents/`

- Purpose: load/validate/sync agent bundles and tool permissions.
- Key files: `src/jarvis/agents/loader.py`, `src/jarvis/agents/registry.py`, `src/jarvis/agents/seed.py`.

### `auth/`

- Purpose: token validation, auth dependencies, OAuth onboarding hooks.
- Key files: `src/jarvis/auth/service.py`, `src/jarvis/auth/dependencies.py`.

### `channels/`

- Purpose: inbound/outbound messaging adapters.
- Key files: `src/jarvis/channels/base.py`, `src/jarvis/channels/whatsapp/*`, `src/jarvis/channels/generic_webhook.py`.

### `db/`

- Purpose: SQLite connection, migration runner, query contracts.
- Key files: `src/jarvis/db/connection.py`, `src/jarvis/db/queries.py`, `src/jarvis/db/migrations/`.

### `events/`

- Purpose: event model contract + trace-aware writes.
- Key files: `src/jarvis/events/models.py`, `src/jarvis/events/writer.py`.

### `memory/`

- Purpose: semantic memory, knowledge base, skill memory.
- Key files: `src/jarvis/memory/service.py`, `src/jarvis/memory/knowledge.py`, `src/jarvis/memory/skills.py`.

### `orchestrator/`

- Purpose: prompt assembly + provider/tool loop.
- Key files: `src/jarvis/orchestrator/step.py`, `src/jarvis/orchestrator/prompt_builder.py`.

### `policy/`

- Purpose: lockdown and tool permission decisions.
- Key file: `src/jarvis/policy/engine.py`.

### `providers/`

- Purpose: model provider adapters + fallback routing.
- Key files: `src/jarvis/providers/router.py`, `src/jarvis/providers/factory.py`.

### `routes/`

- Purpose: API surfaces and WebSocket server.
- Key files: `src/jarvis/routes/api/*`, `src/jarvis/routes/health.py`, `src/jarvis/routes/ws.py`.

### `scheduler/`

- Purpose: cron dispatch logic and bounded catch-up.
- Key file: `src/jarvis/scheduler/service.py`.

### `selfupdate/`

- Purpose: patch propose/validate/test/apply pipeline.
- Key file: `src/jarvis/selfupdate/pipeline.py`.

### `tasks/`

- Purpose: in-process task handlers and registration for agent/scheduler/channels/system.
- Key files: `src/jarvis/tasks/runner.py`, `src/jarvis/tasks/periodic.py`, `src/jarvis/tasks/agent.py`, `src/jarvis/tasks/channel.py`, `src/jarvis/tasks/scheduler.py`, `src/jarvis/tasks/github.py`, `src/jarvis/tasks/maintenance.py`.

### `tools/`

- Purpose: tool registry and policy-gated runtime execution.
- Key files: `src/jarvis/tools/registry.py`, `src/jarvis/tools/runtime.py`.

### `web/`

- Purpose: operator/admin web interface + chat UX.
- Key files: `web/src/App.tsx`, `web/src/pages/admin/*`, `web/src/pages/chat/index.tsx`.

## Request Flow Trace

1. `POST /webhooks/whatsapp` -> channel adapter/router.
2. Event + message persistence in DB.
3. `agent_step` dispatched via in-process task runner.
4. Orchestrator resolves agent + memory + prompt budget.
5. Provider router executes model call.
6. Tool runtime executes permitted tool calls.
7. Assistant message stored, emitted, and pushed to websocket notification queue.

## Related Docs

- `docs/architecture.md`
- `docs/configuration.md`
- `docs/change-safety.md`
