# Docs Drift Matrix

Current coverage map used during docs refresh.

| Area | Source of Truth | Canonical Docs |
| --- | --- | --- |
| API endpoints | `src/jarvis/routes/health.py`, `src/jarvis/routes/ws.py`, `src/jarvis/routes/api/*`, `src/jarvis/main.py` | `docs/api-reference.md`, `docs/api-usage-guide.md` |
| CLI commands | `src/jarvis/cli/main.py` | `docs/cli-reference.md`, `README.md` |
| Runtime/ops | `src/jarvis/main.py`, `src/jarvis/tasks/*`, `Makefile` | `docs/runbook.md`, `docs/local-development.md`, `docs/build-release.md` |
| Deploy/systemd | `deploy/*` | `docs/deploy-operations.md`, `docs/runbook.md` |
| Web/admin | `web/src/App.tsx`, `web/src/pages/admin/*`, `web/src/pages/chat/index.tsx`, `web/src/pages/login/index.tsx` | `docs/web-admin-guide.md` |
| Policy and safety | `src/jarvis/policy/engine.py`, `src/jarvis/tools/runtime.py` | `docs/architecture.md`, `docs/change-safety.md`, `AGENTS.md`, `CLAUDE.md` |

Known stale items resolved in this pass:

- Removed stale worker-target instructions from active docs.
- Clarified slash commands (`/restart`, `/unlock`, `/status`) vs HTTP API endpoints (`/api/v1/system/*`).
- Added docs generation/check automation with `make docs-generate` and `make docs-check`.
