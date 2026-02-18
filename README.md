# Jarvis Agent Framework MVP

Implementation scaffold for `planv2.md` (SPEC-001).

## What is implemented

- FastAPI app with `/healthz`, `/readyz`, WhatsApp webhook verification + ingestion.
- In-process asyncio task runner and task routing.
- SQLite DB connection + ordered SQL migrations.
- Event system with trace-aware event emission.
- Provider interface with Gemini + SGLang adapters and fallback routing.
- Tool registry/runtime with deny-by-default policy hooks and audit events.
- Memory service with embeddings, semantic retrieval, FTS fallback, and thread compaction.
- Agent orchestrator loop with bounded tool-call iterations.
- Scheduler dispatch loop and self-update pipeline with validate/test/apply/rollback gates.
- Agent bundle loader (`agents/*`) with startup validation and tool-permission seeding.
- Role-aware web auth (`user` / `admin`) with ownership-scoped APIs and WebSocket checks.
- Managed skill package support with install metadata and CLI management.

## Quick start

```bash
cp .env.example .env
uv sync
make migrate
make dev
make api
```

## Web UI

- One-time dependency bootstrap: `make web-install`
- Dev server: `make web-dev` (Vite, default `http://localhost:5173`)
- Build static assets: `make web-build`
- Built assets in `web/dist` are served by FastAPI when present.

## CLI chat with main agent

- `uv run jarvis ask "summarize this repo"`
- `uv run jarvis chat`
- `uv run jarvis ask "/status" --enqueue` (chat slash command status)
- `uv run jarvis ask "hello" --json`

## Test and quality

- `make test`
- `make lint`
- `make typecheck`
- `make test-gates`

CI (`.github/workflows/ci.yml`) runs lint, typecheck, unit, integration, and coverage jobs.

## Documentation Index

- `docs/README.md`
- `docs/getting-started.md`
- `docs/local-development.md`
- `docs/git-workflow.md`
- `docs/configuration.md`
- `docs/cli-reference.md`
- `docs/api-reference.md`
- `docs/api-usage-guide.md`
- `docs/web-admin-guide.md`
- `docs/deploy-operations.md`
- `docs/github-pr-automation.md`
- `docs/architecture.md`
- `docs/codebase-tour.md`
- `docs/testing.md`
- `docs/change-safety.md`
- `docs/build-release.md`
- `docs/runbook.md`
- `docs/release-checklist.md`
- `docs/skill-manifest.md`
- `docs/postgres-migration.md`
- `docs/DOCS_AGENT_PROMPT.md`
- `docs/FEATURE_BUILDER_PROMPT.md`

## Agent Prompts

- Prompt library index: `docs/prompts/README.md`
- Includes 10 reusable prompts for bugfix, refactor, release, security, migration, incident, and review workflows.

## Agent bundles

Each directory under `agents/` must contain:

- `identity.md`
- `soul.md`
- `heartbeat.md`

`identity.md` may declare `allowed_tools` frontmatter. Permissions are synced at startup.
