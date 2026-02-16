# Jarvis Plan V3 (Current-State Execution Plan)

Date: February 16, 2026
Replaces: `planv2.md` as active planning artifact

## 1) Purpose

`planv2.md` captured MVP intent. The codebase has since moved beyond it in several areas (web API, RBAC, CI, doctor auto-fix, skill packages), while some release gates and hardening items are still incomplete.

This document defines:
- the actual baseline currently in repo
- the remaining gap-to-production work
- phased execution order with Definition of Done (DoD)

## 2) Current Baseline (Implemented)

### Runtime and platform
- FastAPI API + Celery worker/scheduler architecture is in place.
- SQLite with WAL is in use; migrations are forward-applied via runner.
- Migrations now extend through `021_*` (not `005_*`).

### Channels and APIs
- WhatsApp webhook ingest/outbound path implemented.
- Web API + WebSocket UI APIs implemented (`/api/v1/*`, `/ws`).

### Security and authorization
- Token-based web auth implemented with role-aware session context.
- RBAC implemented: `user` and `admin` role model.
- Ownership enforcement implemented for non-admin users across thread/message/memory/schedule/bug/event surfaces.
- Admin-only enforcement implemented for:
  - system lockdown mutation
  - permissions mutation/read APIs
  - self-update approval endpoints

### Observability and operations
- Event model, trace propagation, and queue depth telemetry implemented.
- Lockdown triggers implemented for readyz failure streak, rollback bursts, and host-exec failure rate.
- Backup and restore scripts/tasks exist.

### Self-update
- Propose/validate/test/apply/rollback state flow implemented with patch safety checks and smoke gates.

### CI and diagnostics
- GitHub Actions CI workflow exists with lint/type/unit/integration/coverage jobs.
- `jarvis doctor --fix` implemented for common remediation paths.

### Skills
- Skills persistence and FTS search implemented.
- Managed skill package metadata + install log model implemented.
- CLI commands for package install/list/info implemented.

## 3) Known Gaps (As Of Today)

1. Quality gate instability
- `make test-gates` is not clean due existing repo-wide Ruff/Mypy issues outside recent feature work.

2. Documentation and plan drift
- `planv2.md` no longer reflects architecture reality (web APIs, RBAC, migrations, CI, doctor fixes, skill package lifecycle).

3. RBAC hardening follow-ups
- Admin/non-admin behavior is implemented but requires broader endpoint-by-endpoint regression tests and review for least privilege.

4. SQLite scale ceiling
- Current tuning helps, but sustained multi-process write concurrency remains a medium-term risk.

5. Skills package policy depth
- Required-tool checks currently warn; no policy-level enforcement workflow beyond warning.

6. Release evidence rigor
- 24h readiness soak, backup/restore drill evidence, and rollout sign-off process should be run as an explicit release cadence.

## 4) Plan V3 Principles

- Security before convenience: deny by default, explicit elevation only.
- Stabilize gates before feature growth.
- Keep migrations forward-only and auditable.
- Treat docs and runbooks as release artifacts, not optional follow-up.
- Ensure every phase ends with executable validation commands.

## 5) Workstreams

## A. Quality Gate Stabilization (Top Priority)

Goal:
- Make `make test-gates` reliably green.

Scope:
- Resolve repo-wide Ruff violations blocking gate runs.
- Resolve repo-wide Mypy violations blocking gate runs.
- Keep strict lint/type configuration; do not weaken standards.

DoD:
- `make test-gates` passes in local and CI on main branch.
- No temporary skips added without owner + expiry.

Validation:
- `make test-gates`
- CI jobs all green on PR and push.

## B. Authorization and RBAC Verification

Goal:
- Confirm no cross-user data access regressions and correct admin boundaries.

Scope:
- Expand/maintain integration tests around:
  - thread/message ownership
  - websocket subscribe ownership
  - event/memory/schedule scoping
  - admin-only control APIs

DoD:
- Authorization integration suite passes consistently.
- Spot review of all `Depends(require_auth)`/`Depends(require_admin)` routes complete.

Validation:
- `uv run pytest tests/integration/test_authorization.py -v`
- targeted API integration runs.

## C. SQLite and Persistence Hardening

Goal:
- Improve resilience while staying on SQLite in near term.

Scope:
- Keep current PRAGMA tuning.
- Benchmark hot write paths under realistic task/API concurrency.
- Define explicit migration trigger thresholds for PostgreSQL transition.

DoD:
- Measured baseline published.
- Trigger thresholds documented and approved.

Validation:
- repeatable benchmark script output recorded in repo docs.

## D. Self-Update Governance Hardening

Goal:
- Ensure safe operation in production mode.

Scope:
- Validate prod approval-only apply path end-to-end.
- Confirm rollback signaling and lockdown behavior under induced failures.
- Confirm restart + readyz watchdog behavior in staging.

DoD:
- Self-update failure drill executed and documented.
- No path allows apply in prod without approval.

Validation:
- integration tests + staging runbook evidence.

## E. Skill Package Maturity

Goal:
- Make package lifecycle safe and operationally clear.

Scope:
- Add tests for malformed manifests and path traversal protection.
- Add update-check semantics beyond placeholder false state.
- Optionally add policy mode:
  - warn-only (current)
  - enforce-required-tools (future toggle)

DoD:
- install/list/info/history flows covered by tests.
- permission expectation clearly documented.

Validation:
- skills unit/integration tests + CLI smoke.

## F. Release Operations Discipline

Goal:
- Convert release checklist from documentation to routine practice.

Scope:
- Run:
  - 24h readiness soak
  - backup and restore drill
  - authorization boundary regression before release

DoD:
- Evidence logged per release candidate using `docs/release-checklist.md`.

Validation:
- checklist artifacts attached to release PR/tag.

## 6) Recommended Sequence

1. A - Quality Gate Stabilization
2. B - Authorization and RBAC Verification
3. F - Release Operations Discipline (staging evidence)
4. D - Self-Update Governance Hardening
5. E - Skill Package Maturity
6. C - SQLite Hardening and Postgres trigger criteria

Rationale:
- Gate stability is a prerequisite for safe iteration.
- Security verification should remain ahead of feature growth.
- Operational release evidence should run before declaring production-readiness.

## 7) Milestones and Exit Criteria

### M1: Gate-Stable Main
- Exit when lint/type/unit/integration/coverage gates are green.

### M2: Security-Verified Surface
- Exit when authorization suite passes and route audit is complete.

### M3: Release-Ready Staging
- Exit when 24h soak + restore drill + self-update failure drill are documented.

### M4: Skills + Persistence Hardening
- Exit when skills lifecycle tests and SQLite benchmarks are complete with agreed next-step thresholds.

## 8) Ownership Template (Per Milestone)

For each milestone track:
- Owner:
- Start date:
- Target date:
- Risks:
- Commands used for validation:
- Artifact links:

## 9) Immediate Next Tasks

1. Create a dedicated PR to make `make test-gates` green.
2. Run authorization suite and attach results to security sign-off issue.
3. Execute staging 24h readiness soak and backup/restore drill with evidence.
4. Add missing skill-package negative tests (manifest/path/tool requirements).

