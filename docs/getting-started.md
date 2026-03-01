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
make setup-smoke
```

Verify:

```bash
uv run python --version
make migrate
```

Expected: Python 3.12 and successful migration run.
`make setup-smoke` should pass for a deterministic API + web bootstrap baseline.
If dependency services are already running and occupying `11434`/`30000`/`8080`,
use `make setup-smoke-running` to skip the dev-port preflight step.

## 2. Start Dependencies

```bash
make dev
```

This starts Ollama, SearXNG, and SGLang from `docker-compose.yml`.

If you want one command that starts dependencies and launches API + web dev servers:

```bash
./start-dev.sh
```

`start-dev.sh` defaults to host-Ollama mode (`DEV_USE_HOST_OLLAMA=1`), so local
`ollama serve` on `11434` is reused while Docker starts SearXNG + SGLang.
Before dependency startup, it verifies OpenCode + LM Studio, discovers LM Studio
models, and writes valid JSON `opencode.json` (or `OPENCODE_CONFIG_PATH`).
To force Docker-managed Ollama instead:

```bash
DEV_USE_HOST_OLLAMA=0 ./start-dev.sh
```

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
make web-install
make web-dev
```

Open `http://localhost:5173`.
Run `make web-install` once before the first `make web-dev`, `make web-build`,
`make web-typecheck`, or `make web-lint`.

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

- `docs/README.md`
- `docs/local-development.md`
- `docs/configuration.md`
- `docs/cli-reference.md`
- `docs/api-usage-guide.md`
- `docs/github-pr-automation.md`
- `docs/testing.md`
