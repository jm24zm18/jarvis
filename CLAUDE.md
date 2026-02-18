# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

Jarvis Agent Framework: multi-agent async framework with WhatsApp integration, event-sourced observability, semantic memory, scheduler, and controlled self-update.

Primary plan: `planv2.md`.

## Commands

```bash
# setup
cp .env.example .env
uv sync
make migrate

# services
make dev        # docker services: ollama, searxng, sglang
make api        # fastapi server (default 127.0.0.1:8000)
make web-dev    # vite dev server (default 5173)

# checks
make test
make lint
make typecheck
make test-gates
make docs-generate
make docs-check

# targeted tests
uv run pytest tests/unit -v
uv run pytest tests/integration -v
uv run pytest tests/unit/test_foo.py -v
uv run pytest tests/unit/test_foo.py::test_bar -v

# migrations
make migrate

# cli
uv run jarvis ask "hello"
uv run jarvis ask "hello" --enqueue
uv run jarvis chat
uv run jarvis doctor --fix
uv run jarvis skill install <path>
```

## Architecture Facts

- Runtime process: API (`src/jarvis/main.py`) with in-process asyncio task runner.
- Database: SQLite with ordered SQL migrations under `src/jarvis/db/migrations` (currently `001..023`).
- Core request path: webhook -> DB dedup/persist -> `channel.inbound` event -> `agent_step` task -> orchestrator/provider/tools -> outbound.
- Tool execution is deny-by-default and gated by policy + agent permissions.
- Lockdown and restart state are enforced via `system_state`.
- Web auth sessions carry `user`/`admin` role and routes enforce ownership scoping.

## Invariants

- ID prefixes: `usr_`, `thr_`, `msg_`, `trc_`, `spn_`, `sch_`.
- Event types use dot notation (`agent.step.end`, `tool.call.start`, `channel.inbound`).
- Every agent bundle in `agents/<id>/` must include `identity.md`, `soul.md`, `heartbeat.md`.
- New DB migration files must be additive, ordered, and never renumber existing migrations.
- Do not widen tool permissions by default; explicit allow is required.
- Self-update evidence must include concrete file and line references.

## Project Structure

```text
src/jarvis/
  main.py, config.py, tasks/runner.py
  agents/, auth/, channels/, cli/, commands/
  db/ (connection.py, queries.py, migrations/001..023)
  events/, memory/, models/, onboarding/
  orchestrator/, plugins/, policy/, providers/
  routes/, scheduler/, selfupdate/, tasks/, tools/
  ids.py, logging.py, errors.py
agents/                # bundled agents
skills/                # skill package docs/artifacts
docs/                  # architecture + runbook + prompts + maintenance docs
docs/prompts/          # 10 reusable agent prompts + README
web/                   # React + Vite admin/chat UI
tests/unit/            # ~30 test files
tests/integration/     # ~13 test files
deploy/                # systemd + healthcheck/rollback/restore scripts
```

## Read First

- `README.md`
- `docs/README.md`
- `docs/getting-started.md`
- `docs/architecture.md`
- `docs/api-usage-guide.md`
- `docs/cli-reference.md`
- `docs/change-safety.md`
- `docs/testing.md`

## Safety

- Prefer additive changes to schema and API.
- For behavior changes, update tests in both unit/integration scopes where relevant.
- Run at least `make lint`, `make typecheck`, and focused tests before finalizing.
- Run docs drift checks (`make docs-generate`, `make docs-check`) when changing docs or public interfaces.
- Documentation updates are mandatory: any behavior, API, schema, config, tooling, or operational workflow change MUST update corresponding docs in the same PR before handoff.
- Keep `AGENTS.md` and this file aligned on operational facts.
- Git flow policy:
  - Use a dedicated branch for implementation work.
  - Open implementation PRs to `dev`.
  - Do not open implementation PRs directly to `master`.
  - `dev -> master` requires human approval.
