# Local Development

## Services

`make dev` starts:

- Ollama: `11434`
- SearXNG: `8080`
- SGLang: `30000`

## Core Runtime Commands

```bash
make api
make web-dev
```

- API reloads with `uvicorn --reload`.
- Web UI reloads via Vite HMR.
- Periodic tasks run in-process inside the API lifespan.

## Common Workflows

### Add a tool

1. Add implementation under `src/jarvis/tools/`.
2. Register with `ToolRegistry`.
3. Add tool permission in agent `identity.md` if needed.
4. Add unit + integration coverage for deny and allow paths.

### Add an agent

1. Create `agents/<id>/identity.md`, `soul.md`, `heartbeat.md`.
2. Restart API so startup sync refreshes permissions.
3. Verify bundle load and permissions in logs/tests.

### Add a migration

1. Add next-numbered SQL file in `src/jarvis/db/migrations/`.
2. Run `make migrate`.
3. Add/update integration tests for schema behavior.

### Add a route

1. Add endpoint in `src/jarvis/routes/api/`.
2. Include it from `src/jarvis/routes/api/__init__.py`.
3. Enforce auth/ownership checks.
4. Add integration tests.

### Enable GitHub PR automation and PR chat (optional)

1. Set `GITHUB_PR_SUMMARY_ENABLED=1`, `GITHUB_WEBHOOK_SECRET`, and `GITHUB_TOKEN` in `.env`.
2. Point GitHub webhook to `/api/v1/webhooks/github`.
3. Keep PR base targeting `dev` to trigger Stage 1 summary comments.
4. Use `/jarvis ...` or `@jarvis` in PR comments to trigger Stage 2 chat replies.
5. Watch `/api/v1/bugs` for automation failures.

### Enable bug/feature request sync to GitHub Issues (optional)

1. Set these in `.env`:
   - `GITHUB_ISSUE_SYNC_ENABLED=1`
   - `GITHUB_ISSUE_SYNC_REPO=<owner>/<repo>`
   - optional label overrides: `GITHUB_ISSUE_LABELS_BUG`, `GITHUB_ISSUE_LABELS_FEATURE`
2. Restart API (`make api`).
3. Submit a bug with GitHub sync:
   - `POST /api/v1/bugs` with body field `"sync_to_github": true`
4. Submit a feature request with GitHub sync:
   - `POST /api/v1/feature-requests` with body field `"sync_to_github": true`
5. Confirm `github_issue_number`/`github_issue_url` are populated in `GET /api/v1/bugs`.

### Enable local maintenance loop (optional)

1. In `.env`, set `MAINTENANCE_ENABLED=1` and `MAINTENANCE_INTERVAL_SECONDS` (for example `3600`).
   - `MAINTENANCE_HEARTBEAT_INTERVAL_SECONDS` defaults to `300` for cron heartbeat.
2. Set `MAINTENANCE_COMMANDS` (newline-separated, `\n` works in `.env`).
3. Periodic maintenance runs in-process while API is running.
4. For one-off local run: `uv run jarvis maintenance run`.
5. Inspect failures in `/api/v1/bugs` if `MAINTENANCE_CREATE_BUGS=1`.
6. CLI equivalents:
   - `uv run jarvis maintenance status --json`
   - `uv run jarvis maintenance run`
   - `uv run jarvis maintenance enqueue`
   - `status` includes `last_heartbeat` so you can verify cron freshness.

## Troubleshooting

- Run diagnostics: `uv run jarvis doctor --fix`
- Check API health: `GET /readyz`, `GET /metrics`
- Validate compose services: `docker compose ps`

## Related Docs

- `docs/getting-started.md`
- `docs/testing.md`
- `docs/codebase-tour.md`
- `docs/configuration.md`
- `docs/github-pr-automation.md`
