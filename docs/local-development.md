# Local Development

## Services

`make dev` starts:

- RabbitMQ: `5672`, mgmt UI `15672`
- Ollama: `11434`
- SearXNG: `8080`
- SGLang: `30000`

## Core Runtime Commands

```bash
make api
make worker
make web-dev
```

- API reloads with `uvicorn --reload`.
- Web UI reloads via Vite HMR.
- Worker restart is manual.

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

### Enable GitHub PR summary automation (optional)

1. Set `GITHUB_PR_SUMMARY_ENABLED=1`, `GITHUB_WEBHOOK_SECRET`, and `GITHUB_TOKEN` in `.env`.
2. Point GitHub webhook to `/api/v1/webhooks/github`.
3. Keep PR base targeting `dev` to trigger Stage 1 summary comments.
4. Use `/jarvis ...` or `@jarvis` in PR comments to trigger Stage 2 chat replies.
5. Watch `/api/v1/bugs` for automation failures.

## Troubleshooting

- Run diagnostics: `uv run jarvis doctor --fix`
- Check worker queue/health: `GET /readyz`, `GET /metrics`
- Validate compose services: `docker compose ps`

## Related Docs

- `docs/getting-started.md`
- `docs/testing.md`
- `docs/codebase-tour.md`
- `docs/configuration.md`
- `docs/github-pr-automation.md`
