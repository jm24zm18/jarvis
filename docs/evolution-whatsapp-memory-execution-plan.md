# Evolution WhatsApp + Memory Hardening Execution Plan

## Objective
Complete the remaining work after the initial Evolution WhatsApp migration and memory hardening pass, with clear deliverables, tests, and rollout controls.

## Scope
- In scope:
  - Prometheus metrics wiring for memory lifecycle KPIs.
  - Failure bridge mapping hardening and dedupe semantics.
  - Memory admin UI expansion (conflicts/tier/archive/failures/graph preview).
  - Consistency evaluator operationalization and governance visibility.
  - Additional WhatsApp reliability and security test coverage.
- Out of scope:
  - Replacing current orchestrator architecture.
  - Non-WhatsApp channel redesign.

## Workstreams

### 1. Metrics and Observability
- Add explicit metrics:
  - `memory_items_count`
  - `memory_avg_tokens_saved`
  - `memory_reconciliation_rate`
  - `memory_hallucination_incidents`
- Emit/update metrics from:
  - `src/jarvis/memory/service.py`
  - `src/jarvis/tasks/memory.py`
  - policy denial/redaction paths in `src/jarvis/memory/policy.py`
- Expose in existing metrics surface and document metric meanings.

### 2. Failure Bridge Hardening
- Improve `sync_failure_capsules` mapping in `src/jarvis/tasks/memory.py`:
  - Parse richer typed fields from `error_details_json`.
  - Add stable dedupe key strategy (`trace_id + phase + summary_hash`).
  - Validate thread/trace linkage.
- Add tests for dedupe and typed conversion behavior.

### 3. Memory UI Completion
- Expand `web/src/pages/admin/memory/index.tsx` with dedicated sections:
  - conflict review queue
  - tier distribution and archive stats
  - failure lookup
  - graph traversal preview
- Add/extend API client endpoints in `web/src/api/endpoints.ts`.
- Keep existing visual language and admin navigation patterns.

### 4. Consistency Evaluator Productization
- Ensure scheduled task output persists and is queryable historically.
- Add governance-facing summary card in admin pages (memory/governance).
- Add route-level filters by thread and time window.

### 5. WhatsApp Reliability and Security Hardening
- Add integration tests for:
  - admin channel APIs (`status/create/qrcode/pairing/disconnect`)
  - webhook secret enforcement paths
  - Evolution payload variants (text/media/reaction/group)
- Ensure no QR/pairing code leakage in logs and events.

## File-Level Change Plan
- Backend:
  - `src/jarvis/tasks/memory.py`
  - `src/jarvis/memory/service.py`
  - `src/jarvis/memory/policy.py`
  - `src/jarvis/routes/api/memory.py`
  - `src/jarvis/routes/api/governance.py` (read-only integration hooks)
- Frontend:
  - `web/src/pages/admin/memory/index.tsx`
  - `web/src/pages/admin/governance/index.tsx`
  - `web/src/api/endpoints.ts`
- Tests:
  - `tests/unit/test_memory_service.py`
  - `tests/unit/test_memory_policy.py` (new if missing)
  - `tests/integration/test_admin_api.py`
  - `tests/integration/test_whatsapp_webhook.py`
- Docs:
  - `docs/configuration.md`
  - `docs/runbook.md`
  - `docs/channels/whatsapp.md`

## Acceptance Criteria
- Lint passes.
- Targeted type checks for touched modules pass.
- New/updated unit tests pass.
- Integration tests for admin channels + webhook variants pass.
- Metrics are visible and non-zero under test flow.
- Memory admin page shows all four required sections.

## Verification Commands
- `make lint`
- `uv run mypy src/jarvis/memory src/jarvis/routes/api/memory.py src/jarvis/tasks/memory.py`
- `uv run pytest tests/unit/test_memory_service.py -v`
- `uv run pytest tests/integration/test_whatsapp_webhook.py -v`
- `uv run pytest tests/integration/test_admin_api.py -v`

## Rollout Strategy
1. Land backend + tests first.
2. Land UI and API wiring second.
3. Enable/validate metrics in dev.
4. Run full `make test-gates` before merge.

## Risks and Mitigations
- Risk: noisy retrieval/ranking changes.
  - Mitigation: keep threshold defaults conservative and test deterministic ordering.
- Risk: webhook compatibility regressions.
  - Mitigation: dual parser tests for legacy + Evolution payloads.
- Risk: operational surprises from new metrics.
  - Mitigation: document units and expected ranges in runbook.

## Execution Update (2026-02-18)
- In progress:
  - Added Evolution callback contract plumbing (`EVOLUTION_WEBHOOK_URL`, `EVOLUTION_WEBHOOK_BY_EVENTS`, `EVOLUTION_WEBHOOK_EVENTS`) and instance-state persistence fields.
  - Hardened WhatsApp webhook auth response contract and no-op handling for non-`messages.upsert` payloads.
  - Added governance evolution-item contracts:
    - event types `evolution.item.started|verified|blocked`
    - admin APIs for listing and status transitions.
- Pending before closure:
  - Run full gate evidence (`make lint`, `make typecheck`, `make test-gates`, `make docs-check`) and attach outputs.

## Execution Update (2026-02-19)
- Completed:
  - Added explicit log-capture assertion proving QR/pairing secrets are redacted in persisted webhook batch events (`tests/integration/test_whatsapp_webhook.py`).
  - Added self-update governance guardrail coverage for identity-frontmatter escalation keys (`tests/unit/test_selfupdate_pipeline.py`, `tests/integration/test_selfupdate.py`).
  - Added frontend admin workflow contract tests for memory review/resolve + filtered consistency and channel pairing/QR controls (`web/tests/adminMemoryContracts.test.mjs`, `web/tests/adminChannelsContracts.test.mjs`).
- Remaining:
  - None for this execution-plan scope.
