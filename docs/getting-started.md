# Getting Started

## Prerequisites

- Python `3.12.x`
- `uv`
- Docker + Docker Compose
- Node.js + npm (for web UI development)

## 1. Clone and Bootstrap

```bash
cp .env.example .env
uv sync
make migrate
```

Verify:

```bash
uv run python --version
make migrate
```

Expected: Python 3.12 and successful migration run.

## 2. Start Dependencies

```bash
make dev
```

This starts Ollama, SearXNG, and SGLang from `docker-compose.yml`.

## 3. Start API

In terminal A:

```bash
make api
```

Verify:

```bash
curl -s http://127.0.0.1:8000/healthz
curl -s http://127.0.0.1:8000/readyz
```

Expected: `/healthz` returns `{"ok":true}` and `/readyz` returns 200 when dependencies are healthy.

## 4. First Interaction (CLI)

```bash
uv run jarvis ask "summarize this repo"
uv run jarvis chat
```

## 5. Optional Web UI

```bash
make web-dev
```

Open `http://localhost:5173`.

## 6. Optional GitHub Integration

For PR summaries/chat and bug/feature issue sync:

```bash
# in .env
GITHUB_PR_SUMMARY_ENABLED=1
GITHUB_WEBHOOK_SECRET=<secret>
GITHUB_TOKEN=<token>
GITHUB_ISSUE_SYNC_ENABLED=1
GITHUB_ISSUE_SYNC_REPO=<owner>/<repo>
```

Then restart API and configure repository webhook to:
`POST /api/v1/webhooks/github`

## Agent Notes

- If `/readyz` fails locally, run `uv run jarvis doctor --fix` and re-check.
- Keep `.env` aligned with `docs/configuration.md`.

## Next Docs

- `docs/local-development.md`
- `docs/configuration.md`
- `docs/github-pr-automation.md`
- `docs/testing.md`
