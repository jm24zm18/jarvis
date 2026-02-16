# Agent Team Roster

Use this as the routing map for specialized work in this repository.

## Core Coordinator

- `main`: User-facing coordinator, handles simple tasks directly, delegates specialist work.

## Specialists

- `lintfixer`: Ruff/mypy remediation, `make lint` and `make typecheck` stabilization.
- `tester`: Unit/integration test failures, flaky tests, coverage hardening.
- `api_guardian`: FastAPI routes, auth/RBAC ownership boundaries, API contracts.
- `data_migrator`: SQL migrations, schema compatibility, data safety.
- `web_builder`: React/Vite UI implementation under `web/`.
- `security_reviewer`: Security review, least-privilege checks, policy hardening.
- `docs_keeper`: Documentation drift fixes, cross-linking, doc operability.
- `release_ops`: Build/release gates, deploy/rollback/runbook validation.

## Existing Generalists

- `coder`: General code implementation specialist.
- `researcher`: External research specialist.
- `planner`: Project planning specialist.

## Delegation Notes

- Delegation is initiated by `main` via `session_send`.
- Session tools are restricted to `main` by policy engine.
- Specialists return results back to `main` for final user response.
- Branch policy for agent-generated changes:
  - Work on a dedicated branch.
  - Open PRs into `dev`.
  - Promote `dev -> master` only with human approval in the PR.
