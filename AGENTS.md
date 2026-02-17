# AGENTS.md

Primary AI-agent operating guide for this repository.

## Quick Facts

- Stack: FastAPI + in-process asyncio task runner + SQLite + React/Vite web UI.
- Runtime: API (`make api`) + Docker services (`make dev`).
- DB migrations: `src/jarvis/db/migrations/001..023` auto-run at startup and via `make migrate`.
- Tool runtime is deny-by-default (`src/jarvis/tools/runtime.py`, `src/jarvis/policy/engine.py`).
- Auth/RBAC: bearer session tokens with `user`/`admin` roles and ownership scoping.

## Commands

```bash
# setup
cp .env.example .env
uv sync
make migrate

# run
make dev
make api
make web-dev

# quality gates
make lint
make typecheck
make test
make test-gates

# targeted tests
uv run pytest tests/unit -v
uv run pytest tests/integration -v
uv run pytest tests/unit/test_foo.py::test_bar -v

# CLI
uv run jarvis ask "hello"
uv run jarvis chat
uv run jarvis doctor --fix
uv run jarvis skill list
```

## Architecture Invariants

- IDs are type-prefixed (`usr_`, `thr_`, `msg_`, `trc_`, `spn_`, `sch_`).
- Event names are dot-separated (`channel.inbound`, `agent.step.end`, `tool.call.start`).
- Agent bundle contract in `agents/<id>/` is mandatory:
  - `identity.md` (frontmatter includes `allowed_tools`)
  - `soul.md`
  - `heartbeat.md`
- Migrations are append-only; never modify historical migration semantics in-place.
- Policy is restrictive by default:
  - Unknown tool: deny
  - During lockdown: deny all but safe tools
  - Session tools: `main` agent only
- Self-update evidence is mandatory and must include path+line references.
- Ownership boundaries must hold for non-admin users across API and WebSocket subscriptions.

## Decision Trees

### Should I add a migration?
1. Does the change alter schema or persisted behavior?
2. If yes, add next-numbered file in `src/jarvis/db/migrations/`.
3. Run `make migrate` and relevant tests.
4. Document operational impact in `docs/architecture.md` and `docs/change-safety.md` if high-risk.

### Should I expose a new tool?
1. Register tool in `src/jarvis/tools/`.
2. Keep default deny behavior.
3. Explicitly allow in agent `identity.md` when needed.
4. Add tests for deny path and allow path.

### Should I add a new route?
1. Add route under `src/jarvis/routes/api/`.
2. Enforce `require_auth` and ownership checks where applicable.
3. Add integration tests for admin and non-admin behavior.
4. Update `docs/codebase-tour.md` and API-related docs.

## File Map

- Runtime/bootstrap: `src/jarvis/main.py`, `src/jarvis/tasks/runner.py`
- Configuration/env contract: `src/jarvis/config.py`, `.env.example`, `docs/configuration.md`
- Data model/query invariants: `src/jarvis/db/queries.py`, `src/jarvis/db/migrations/`
- Orchestration/tool policies: `src/jarvis/orchestrator/step.py`, `src/jarvis/tools/runtime.py`, `src/jarvis/policy/engine.py`
- Auth and RBAC: `src/jarvis/auth/`, `src/jarvis/routes/api/auth.py`
- Web UI: `web/src/App.tsx`, `web/src/pages/admin/*`, `web/src/pages/chat/*`
- Operations: `docs/runbook.md`, `docs/build-release.md`, `deploy/*`

## Safety Rules

- Do not bypass policy checks in runtime or route handlers.
- Do not relax ownership checks for non-admin users.
- Do not introduce non-additive migration rollouts without explicit rollback strategy.
- Do not commit real credentials into docs or `.env.example`.
- Keep `AGENTS.md` and `CLAUDE.md` operationally consistent.
- Git flow policy:
  - Agent changes must be done on a dedicated work branch.
  - Agent PRs target `dev` (never `master` directly).
  - `dev -> master` promotion requires human approval.

## Verification Commands

```bash
make lint
make typecheck
make test-gates
uv run jarvis doctor
```

If `make test-gates` is too slow during iteration, run targeted tests and then full gates before handoff.

## Agent Prompt Index

- Prompt library: `docs/prompts/README.md`
- Feature build workflow: `docs/FEATURE_BUILDER_PROMPT.md`
- Docs maintenance workflow: `docs/DOCS_AGENT_PROMPT.md`

## Related Docs

- `README.md`
- `docs/getting-started.md`
- `docs/local-development.md`
- `docs/git-workflow.md`
- `docs/architecture.md`
- `docs/testing.md`
- `docs/change-safety.md`
- `docs/runbook.md`
