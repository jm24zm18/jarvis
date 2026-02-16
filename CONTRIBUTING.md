# Contributing

## Setup

Use `docs/getting-started.md` for full bootstrap.

Quick path:

```bash
cp .env.example .env
uv sync
make migrate
make dev
make api
make worker
```

## Code Style

- Ruff rules: `E,F,I,UP,B`
- Line length: `100`
- Python target: `3.12`
- Type checking: `mypy` strict on `src/`

Commands:

```bash
make lint
make typecheck
```

## Testing Expectations

- Behavior changes should include tests.
- Prefer adding both unit and integration tests when crossing runtime boundaries.
- Run before PR:

```bash
make test-gates
```

## Where to Add Things

- Tools: `src/jarvis/tools/`
- Agents: `agents/<id>/`
- Channels: `src/jarvis/channels/`
- Migrations: `src/jarvis/db/migrations/NNN_name.sql`
- API routes: `src/jarvis/routes/api/`

## PR Guidance

- Keep changes scoped and reviewable.
- Include doc updates when behavior/config changes.
- Add operational notes for risky changes.

## Branching and Promotion Policy

- All implementation work is done on a dedicated branch (for example `agent/<topic>` or `feature/<topic>`).
- PRs for active development target `dev`.
- PRs into `master` are release promotions from `dev` only.
- `dev -> master` requires at least one non-author human approval.

## Related Docs

- `docs/local-development.md`
- `docs/git-workflow.md`
- `docs/testing.md`
- `docs/change-safety.md`
