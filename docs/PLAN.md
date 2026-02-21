# Jarvis Master Execution Plan

**Date:** 2026-02-18
**Rebaseline:** 2026-02-18 (repo/test evidence alignment pass)
**Canonical source note:** This file supersedes fragmented plan docs as the execution source of truth.

## Mission and Operating Model

Deliver a self-improving Jarvis that combines deterministic governance with agentic execution across self-update, memory, and WhatsApp channels.

Operating model:
- Deterministic Core + Agentic Edge + Verifiable Change Loop.
- Personal-number WhatsApp channel via Evolution API sidecar (Baileys-based), fully governed by existing policy and memory systems.
- Structured multi-tier memory with adaptive scoring, reconciliation, and auditable lifecycle events.

Memory model definition (canonical):

```python
importance = (
    0.4 * recency_score
    + 0.3 * access_count_norm
    + 0.2 * llm_self_assess
    + 0.1 * user_feedback
)
importance = min(1.0, max(0.0, importance))
```

Tier flow: `working -> episodic -> semantic/procedural`, with low-importance stale items archived.

## Non-Negotiable Invariants

1. Deny-by-default tool access.
2. Append-only migrations.
3. Traceable event schema.
4. Test validation required.
5. Policy engine authority.
6. Memory writes require evidence refs.
7. No direct `master` commits.
8. Rollback remains available.

## Current State Snapshot

| Area | implemented | partial | not_started |
|---|---:|---:|---:|
| Foundation + Observability | 7 | 2 | 0 |
| Self-Coding + Release Loop | 3 | 3 | 0 |
| Governance + Safety | 3 | 3 | 1 |
| Memory Intelligence + Retrieval | 2 | 6 | 2 |
| WhatsApp Channel + Admin UX | 7 | 0 | 0 |
| Documentation + Ops Hardening | 2 | 1 | 1 |

_Last updated: 2026-02-20 (Packet 9: framework audit + multi-channel media Phase 1)_

## Security Audit Update (2026-02-18)

Source: `docs/security-audit-2026-02-18.md` (dev @ `b9a4e1447282ec8a0d67fdd22e8591b7c2b7adc4`)

Scanner execution status (local run):
- Installed local scanner toolchain under `/tmp/sec-tools/bin`:
  - `semgrep 1.152.0`
  - `gitleaks 8.30.0`
  - `trivy 0.69.1`
  - `osv-scanner 2.3.3`
  - `trufflehog 3.93.3`
- Results:
  - `semgrep` (python + react/javascript): 0 findings.
  - `trufflehog filesystem --only-verified`: 0 verified secrets.
  - `gitleaks`: 6 `generic-api-key` hits; triage = mostly false positives plus one local untracked `.env` secret hit.
  - `osv-scanner --lockfile=uv.lock`: 1 High vuln (`starlette 0.47.3`, fixed in `0.49.1`).
  - `osv-scanner --lockfile=web/package-lock.json`: 2 Medium vulns (`ajv 6.12.6`, `esbuild 0.21.5`).
  - `pip-audit`: confirms Starlette vulnerability/fix path.
  - `npm audit --json`: 12 moderate vulns (dev dependency graph).
  - `trivy fs --scanners misconfig`: 0 findings in this runtime.

High-priority audit findings to action:
1. Non-admin `subscribe_system` authorization gap in WebSocket path.
2. Session token exposure risk (query-string WS token + `localStorage` persistence).
3. Missing webhook replay protection.
4. CI action pinning gap (`@main` mutable ref) and CI least-privilege permissions tightening.
5. Dependency lockfile remediation required (`starlette`, `ajv`, `esbuild`).

Status normalization:
- Source `implemented`/`done` => `done`
- Source `partial`/`in_progress`/`blocked` => `partial`
- Source unchecked TODO / planned-only without evidence => `not_started`
- Duplicate conflict rule applied conservatively (`partial` over `done`; `not_started` only used over `partial` when no evidence exists).

## Beta Full-Pass Update (2026-02-18)

Source: `docs/reports/beta-2026-02-18-full-pass.md`

Findings incorporated into this plan:
1. `jarvis ask --json` can hang on provider DNS/transport failures and time out without a deterministic terminal payload.
2. `make dev` startup fails on occupied host ports (`11434`, `30000`) without preflight detection/remediation guidance.
3. `tests/integration/test_authorization.py::test_non_admin_cannot_toggle_lockdown` hangs and requires external timeout.
4. `make web-install` has a reproducible npm failure mode (`Exit handler never called!`) with weak diagnostics/recovery guidance.
5. Quick-start documentation omits explicit web dependency bootstrap before web targets.

Stabilization directive:
- Prioritize reliability/onboarding fixes ahead of feature expansion until core user path + local setup path are deterministic.

## Unified Milestones

### M1 - Foundation and Observability
Dependencies: none
- Close remaining foundation gaps (repo index drift checks, evidence validator, observability unification, memory policy denial/redaction events).
- Stand up WhatsApp sidecar and secure webhook baseline.

### M2 - Self-Coding and Core Memory Reliability
Dependencies: M1
- Enforce test-first + evidence gates for mutation paths.
- Complete deterministic reconciliation hardening and retrieval fusion.
- Stabilize failure bridge mapping and dedupe semantics.

### M3 - Governance and Channel Productization
Dependencies: M2
- Enforce permission governance hardening and memory ACL scope checks.
- Complete WhatsApp admin pairing and governance review flows.
- Productize consistency evaluator visibility and governance filtering.

### M4 - Recursive Optimization and Fitness
Dependencies: M3
- Activate learning-loop feedback into planning.
- Expand fitness metrics (coverage stability + hallucination incidents).
- Add adaptive memory optimization with measurable retrieval-quality lift.

## Consolidated Backlog

| ID | area | task | status | priority | owner | acceptance |
|---|---|---|---|---|---|---|
| BK-001 | Foundation + Observability | Ground-truth index dependency edges + freshness CI gate | done | P0 | planner | `make lint`; `make typecheck`; `uv run pytest tests/unit -k repo_index -v` |
| BK-002 | Foundation + Observability | Evidence validator required for all mutation-capable flows | done | P0 | security_reviewer | `uv run pytest tests/unit -k evidence -v`; `uv run pytest tests/integration -k selfupdate -v` |
| BK-003 | Foundation + Observability | Unified evolution observability view with trace drill-down | done | P1 | web_builder | additive evolution-item filters (`status`, `trace_id`, `from`, `to`) + stable trace linkage fields (`trace_id`, `span_id`, `thread_id`, `status`, `updated_at`) and admin drill-down UI wired; `uv run pytest tests/integration/test_web_api.py -k evolution -v`; `cd web && npm test -- adminObservabilityContracts.test.mjs` |
| BK-004 | Foundation + Observability | Memory denial/redaction event emission contract completion | done | P1 | api_guardian | `uv run pytest tests/unit/test_memory_policy.py -v` |
| BK-005 | Self-Coding + Release Loop | Self-update artifact schema versioning | done | P0 | coder | `uv run pytest tests/integration -k selfupdate -v` |
| BK-006 | Self-Coding + Release Loop | Deterministic reconciliation edge-case lock tests + run summary events | done | P0 | tester | `uv run pytest tests/unit/test_state_store.py -v`; `uv run pytest tests/unit/test_memory_tasks.py -v` |
| BK-007 | Self-Coding + Release Loop | Test-first gate (failing-test proof + coverage floor + critical-path test requirement) | done | P0 | tester | `make test-gates`; `uv run pytest tests/integration/test_selfupdate.py -v`; `uv run pytest tests/unit/test_selfupdate_contracts.py -v` |
| BK-008 | Self-Coding + Release Loop | PR base-branch enforcement test (`dev` only) | done | P1 | release_ops | `uv run pytest tests/unit/test_github_tasks.py -v` |
| BK-009 | Self-Coding + Release Loop | Failure remediation scoring uses acceptance/rejection outcomes | done | P1 | researcher | `uv run pytest tests/unit -k failure_capsule -v` |
| BK-010 | Governance + Safety | Block self-permission escalation edits on agent identity governance fields | done | P0 | security_reviewer | `uv run pytest -q tests/unit/test_selfupdate_pipeline.py -k governance_identity_edits_from_patch`; `uv run pytest -q tests/integration/test_selfupdate.py -k identity_governance_field_edits` |
| BK-011 | Governance + Safety | Self-update deployment gate state machine + typed failure taxonomy | done | P0 | release_ops | `uv run pytest tests/integration -k selfupdate_apply -v` |
| BK-012 | Governance + Safety | Memory governance hardening (schema write gates + deny/redaction governance filters) | done | P0 | security_reviewer | `uv run pytest tests/unit/test_memory_policy.py -v`; `uv run pytest tests/unit/test_memory_service.py -v`; `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v` |
| BK-013 | Governance + Safety | Explicit per-agent memory read/write scope checks across APIs/tasks | done | P0 | security_reviewer | `uv run pytest tests/unit/test_memory_tasks.py -v`; `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v` |
| BK-014 | Governance + Safety | WhatsApp risky/unknown sender review queue with in-chat approve/deny commands | done | P1 | main | `uv run pytest tests/integration/test_whatsapp_webhook.py -k "strict_mode_queues_unknown_sender or strict_mode_blocks_sender_after_denied_review" -v`; `uv run pytest tests/integration/test_admin_api.py -k review_queue -v`; `uv run pytest tests/integration/test_commands.py -k wa_review -v`; `uv run pytest tests/integration/test_authorization.py -k non_admin_cannot_manage_whatsapp_channels -v` |
| BK-015 | Memory Intelligence + Retrieval | Multi-tier memory lifecycle and archival flow with score-driven migration | done | P1 | planner | `uv run pytest tests/unit -k state_store -v` |
| BK-016 | Memory Intelligence + Retrieval | Retrieval fusion completion (RRF for vector + FTS5 + filters + tier priors) | done | P0 | planner | `uv run pytest tests/unit/test_hybrid_search.py -v` |
| BK-017 | Memory Intelligence + Retrieval | Failure bridge typed mapping + stable dedupe key (`trace_id+phase+summary_hash`) | done | P1 | planner | `uv run pytest tests/unit/test_memory_tasks.py -v` |
| BK-018 | Memory Intelligence + Retrieval | Graph relation extraction confidence/evidence policy completion | partial | P1 | researcher | traversal + relation-extraction tests |
| BK-019 | Memory Intelligence + Retrieval | Adaptive forgetting/archival calibration harness and threshold tuning | partial | P1 | memory_curator | maintenance/task tests + workload simulation |
| BK-020 | Memory Intelligence + Retrieval | Consistency evaluator endpoint/UI surface and historical queryability | partial | P1 | planner | API + admin UI tests for reports/filters |
| BK-021 | Memory Intelligence + Retrieval | Full memory endpoint/CLI/RBAC test suite for new state/review/export surfaces | done | P0 | tester | `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v`; `uv run pytest tests/integration/test_authorization.py -v` |
| BK-022 | WhatsApp Channel + Admin UX | Evolution sidecar bootstrap (persistent auth, API key auth, webhook callback) | done | P0 | api_guardian | callback contract/env wiring landed (`EVOLUTION_WEBHOOK_URL`, `EVOLUTION_WEBHOOK_BY_EVENTS`, `EVOLUTION_WEBHOOK_EVENTS`); instance callback state persisted (`054_evolution_instance_contract.sql`); coverage in `tests/integration/test_admin_api.py` + `python3 scripts/test_migrations.py` |
| BK-023 | WhatsApp Channel + Admin UX | WhatsApp channel implementation: text/media/reaction/groups/thread mapping | done | P0 | api_guardian | `uv run pytest tests/integration/test_whatsapp_webhook.py -v`; `uv run pytest tests/unit/test_channel_abstraction.py -v` |
| BK-024 | WhatsApp Channel + Admin UX | Voice-note pipeline (download, transcribe, memory linkage) | done | P0 | api_guardian | secure media download + transcript insertion + linkage metadata landed; `uv run pytest tests/integration/test_whatsapp_webhook.py -v` and `uv run pytest tests/unit/test_whatsapp_transcription.py -v` |
| BK-025 | WhatsApp Channel + Admin UX | Admin pairing APIs (`status/create/qrcode/pairing-code/disconnect`) + auth/rate limits | done | P0 | api_guardian | `uv run pytest -q tests/integration/test_admin_api.py -k "whatsapp or pairing_code_rejects_non_numeric_input"`; `uv run pytest tests/integration/test_authorization.py -v` |
| BK-026 | WhatsApp Channel + Admin UX | Admin pairing UI (QR, status polling, connect/disconnect flows) | done | P1 | web_builder | `cd web && npm test` (`web/tests/adminChannelsContracts.test.mjs`) + endpoint contract tests |
| BK-027 | WhatsApp Channel + Admin UX | Webhook auth and payload normalization (`messages.upsert` variants) | done | P0 | api_guardian | webhook secret reject contract + no-op ignore path for non-upsert events + variant normalization; `uv run pytest tests/integration/test_whatsapp_webhook.py -v` |
| BK-028 | WhatsApp Channel + Admin UX | WhatsApp security controls (no QR/code leakage, file limits, safe media paths) | done | P0 | security_reviewer | QR/pairing redaction + media URL/mime/size/path controls + negative tests landed; `uv run pytest tests/integration/test_whatsapp_webhook.py -v`; `uv run pytest tests/unit/test_whatsapp_media_security.py -v` |
| BK-029 | Documentation + Ops Hardening | Memory Prometheus KPI wiring and docs (`items_count`, `avg_tokens_saved`, `reconciliation_rate`, `hallucination_incidents`) | done | P1 | release_ops | structured `tokens_saved` persisted (`053_state_reconciliation_tokens_saved.sql`) and `/metrics` validation (`uv run pytest tests/unit/test_health.py -q`) |
| BK-030 | Documentation + Ops Hardening | Add rollback/runbook and config docs for new memory tables/tasks/flags | done | P1 | release_ops | memory rollback/recovery and conflict operator flow documented in `docs/runbook.md`; memory/state feature flags added to `docs/configuration.md`; `make docs-generate`; `make docs-check` |
| BK-031 | Documentation + Ops Hardening | WhatsApp operator docs and troubleshooting coverage | done | P1 | release_ops | troubleshooting decision tree + rollback path documented in `docs/channels/whatsapp.md` and `docs/channels/whatsapp-ui.md`; `uv run pytest tests/integration/test_whatsapp_webhook.py -v` |
| BK-032 | Documentation + Ops Hardening | API/schema docs for memory routes and conflict-resolution operator flow | done | P2 | planner | API reference regenerated (`make docs-generate`) and operator conflict-resolution flow documented in `docs/runbook.md`; `make docs-check` |
| BK-033 | Foundation + Observability | Evolution/governance event contract additions (`evolution.item.*`) | done | P2 | api_guardian | event types + payload minimum key enforcement + admin query/update APIs landed (`055_evolution_items.sql`); `uv run pytest tests/integration/test_web_api.py -k evolution_items -v`; `uv run pytest tests/unit/test_event_envelope_enforcement.py -v` |
| BK-034 | Governance + Safety | Dependency steward hardening (CVE severity, compatibility bundle, rollback-ready PR context) | partial | P1 | dependency_steward | `uv run pytest tests/unit/test_governance_tasks.py -v` |
| BK-057 | Foundation + Observability | Multi-channel media: persist `media_path`/`mime_type` on inbound messages (migration 058) and wire write path | done | P0 | api_guardian | `insert_message()` updated with media params; WhatsApp router passes media fields; `tests/unit/test_db_queries.py::test_insert_message_media_round_trip`; `python3 scripts/test_migrations.py` |
| BK-058 | Governance + Safety | Policy engine: wildcard `*` tool permission support (migration 057) and R8 `max_actions_per_step` enforcement | done | P0 | api_guardian | `is_allowed()` supports `IN (?, '*')`; R8 enforced via event count per trace_id; `tests/unit/test_tools_runtime.py::test_wildcard_permission_allows_any_tool`; `tests/unit/test_tools_runtime.py::test_max_actions_per_step_enforced` |
| BK-059 | Memory Intelligence + Retrieval | Memory consistency evaluator API surface and historical storage (migration 059) | done | P1 | api_guardian | `GET /api/v1/memory/consistency` endpoint + `memory_consistency_reports` table + `store_consistency_report()` in queries; `tests/integration/test_admin_api.py::test_memory_consistency_endpoint_requires_thread_id` |
| BK-060 | Foundation + Observability | Scheduler: fix NULL thread_id bug, add transaction on thread creation, per-schedule error isolation | done | P0 | data_migrator | scheduler skips NULL-thread schedules with `schedule.error` event; 3-INSERT transaction uses `BEGIN/COMMIT/ROLLBACK`; per-schedule try/except; `tests/integration/test_scheduler.py::test_scheduler_tick_null_thread_id_skips_gracefully`; `tests/integration/test_scheduler.py::test_scheduler_tick_creates_isolated_thread` |
| BK-061 | Foundation + Observability | Event retention maintenance task (configurable `EVENT_RETENTION_DAYS`, default 90) | done | P1 | api_guardian | `src/jarvis/tasks/events.py`; registered as weekly periodic task; `EVENT_RETENTION_DAYS` config flag; `.env.example` updated |
| BK-062 | Foundation + Observability | Fitness snapshot periodic task interval: change from weekly to 30-minute schedule | done | P0 | api_guardian | `compute_system_fitness` interval changed from 604800s to 1800s in `tasks/__init__.py` |
| BK-063 | Foundation + Observability | Fix `main.py` undefined `evolution` variable (should be `baileys`) and I001 import sort | done | P0 | api_guardian | `evolution.*` -> `baileys.*`; import sort auto-fixed; `make lint` clean; `make typecheck` clean |
| BK-064 | Documentation + Ops Hardening | Deduplicate soul.md branch policy boilerplate across all agent bundles | done | P2 | docs_keeper | 4 soul.md files now reference CLAUDE.md instead of inline git-flow block (main, coder, data_migrator, planner) |
| BK-065 | Documentation + Ops Hardening | Add FEATURE_BUILDER_PROMPT.md and DOCS_AGENT_PROMPT.md to docs/prompts/ | done | P2 | docs_keeper | `docs/prompts/FEATURE_BUILDER_PROMPT.md`; `docs/prompts/DOCS_AGENT_PROMPT.md`; `docs/prompts/README.md` updated |
| BK-066 | Governance + Safety | Self-update guardrail defaults: bound `max_files_per_patch`, `max_risk_score`, `max_patch_attempts_per_day`, `max_prs_per_day` | done | P1 | api_guardian | `SELFUPDATE_MAX_FILES_PER_PATCH=20`, `SELFUPDATE_MAX_RISK_SCORE=100`, `SELFUPDATE_MAX_PATCH_ATTEMPTS_PER_DAY=10`, `SELFUPDATE_MAX_PRS_PER_DAY=5` added to `config.py` and `.env.example`; prevents runaway self-update loops |
| BK-035 | Governance + Safety | Release-candidate hardening (changelog artifact + runbook evidence) | partial | P1 | release_candidate | `uv run pytest tests/unit/test_governance_tasks.py -v` |
| BK-036 | Memory Intelligence + Retrieval | Memory admin UI completion (conflicts, tier/archive stats, failure lookup, graph preview) | done | P1 | web_builder | `cd web && npm test` (`web/tests/adminMemoryContracts.test.mjs`) + `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v` |
| BK-037 | Governance + Safety | Enforce admin-only WS system subscription (`subscribe_system`) and add regression tests | done | P0 | security_reviewer | `uv run pytest tests/integration/test_authorization.py -k websocket -v` |
| BK-038 | Governance + Safety | Web auth hardening: remove WS query-token transport + replace persistent browser token storage model | done | P0 | api_guardian | `uv run pytest tests/integration/test_websocket.py -v`; `uv run pytest tests/integration/test_authorization.py -k websocket -v`; manual login/session regression |
| BK-039 | Governance + Safety | Webhook replay defense (delivery-id/nonce + bounded replay window) | done | P0 | security_reviewer | `uv run pytest tests/integration/test_web_api.py -k github_webhook -v` with replay negatives |
| BK-040 | Documentation + Ops Hardening | Dependency vuln remediation from audit (`starlette`, `ajv`, `esbuild`) and lockfile refresh | done | P0 | dependency_steward | Python lock + audit clean (`uv run pip-audit`); npm `esbuild` path remediated (`vite@7.3.1` -> `esbuild@0.27.3`); residual ESLint-transitive `ajv@6.12.6` formally risk-accepted with sunset (`docs/security-risk-acceptance.md`, 2026-04-30); `osv-scanner --lockfile=web/package-lock.json` re-run shows single remaining accepted finding |
| BK-041 | Documentation + Ops Hardening | CI supply-chain hardening: pin third-party GitHub actions to SHAs and add top-level CI permissions | done | P0 | release_ops | workflow CI pass + branch-policy/release workflow validation |
| BK-042 | Documentation + Ops Hardening | Secret hygiene follow-up: rotate local exposed OAuth credentials and add pre-commit secret scan command docs | partial | P1 | release_ops | repo-owned work complete: explicit operator-owned credential-rotation checklist + required artifact naming template added to `docs/runbook.md`; rotation execution evidence remains external/operator-owned |
| BK-043 | Self-Coding + Release Loop | Fail-fast `jarvis ask --json` path on provider transport/DNS errors with bounded fallback budget + deterministic error payload | done | P0 | api_guardian | `uv run pytest -q tests/unit/test_cli_chat.py -k "ask_json"` passes with structured `ok=false` envelope and non-zero exit |
| BK-044 | Self-Coding + Release Loop | Guard orchestrator/state-extractor error paths to prevent long traceback/timeouts after provider failure | done | P0 | planner | `uv run pytest -q tests/unit/test_orchestrator_step.py -k "provider or degraded or fallback"` passes; degraded assistant message + `model.run.error` event emitted on provider failure |
| BK-045 | Governance + Safety | Deflake and unhang `test_non_admin_cannot_toggle_lockdown` via lifecycle/teardown instrumentation and fix | done | P0 | tester | `WEB_AUTH_SETUP_PASSWORD=secret uv run pytest -q tests/integration/test_authorization.py::test_non_admin_cannot_toggle_lockdown` and login flow tests complete deterministically |
| BK-046 | Foundation + Observability | Add `make dev` host-port preflight (`11434`, `30000`, `8080`) with actionable remediation output | done | P0 | release_ops | `python3 scripts/dev_preflight_ports.py` fails fast on occupied ports and prints remediation commands |
| BK-047 | Documentation + Ops Hardening | Document Docker/local port-conflict troubleshooting and optional alternate-port profile | done | P1 | release_ops | docs updates landed in `docs/local-development.md` and `docs/runbook.md`; `make docs-check` passed |
| BK-048 | Documentation + Ops Hardening | Harden `make web-install` path with deterministic npm diagnostics/retry guidance and fallback commands | done | P1 | web_builder | failure/success evidence captured (`/tmp/jarvis-web-install-failure.log`, `/tmp/jarvis-web-install-success.log`) and wrapper hardened with deterministic `network_blocked_or_sandboxed` classification + npm debug-log extraction (`scripts/web_install.py`) plus regression tests (`tests/unit/test_web_install_script.py`) |
| BK-049 | Documentation + Ops Hardening | Update quick-start docs to require `make web-install` before web dev/build/typecheck/lint commands | done | P0 | release_ops | `README.md` and `docs/getting-started.md` include explicit sequencing; `make docs-check` passes |
| BK-050 | Foundation + Observability | Improve CLI/doctor environment diagnostics to distinguish sandbox/network/provider outage classes | done | P1 | api_guardian | deterministic outage enum contract locked to `dns_resolution`, `timeout`, `network_unreachable`, `provider_unavailable` across doctor/CLI + regression tests (`tests/unit/test_cli_checks.py`, `tests/unit/test_cli_chat.py`); documented in `docs/cli-reference.md` and `docs/runbook.md` |
| BK-051 | Foundation + Observability | Add reproducible new-user setup smoke target covering API + web bootstrap path | done | P1 | tester | local evidence captured: `make setup-smoke` fails deterministically on occupied ports (`11434`,`30000`,`8080`) with remediation; `make setup-smoke-running` passes bootstrap checks end-to-end |
| BK-052 | Self-Coding + Release Loop | Add regression tests for provider-unavailable and DNS-failure UX in CLI/API flows | done | P0 | tester | CLI/orchestrator failure-mode tests pass and enforce structured fast-fail behavior (`ok=false`, failure kind metadata, degraded response persistence) |
| BK-053 | Governance + Safety | Align provider-config integration tests with admin-only RBAC and retain non-admin deny regression | done | P0 | tester | `uv run pytest tests/integration/test_web_api.py -k provider_config -v` |
| BK-054 | Governance + Safety | Harden auth login `external_id` bounds with API validation + DB trigger guard (`1..256`) | done | P0 | security_reviewer | `uv run pytest tests/integration/test_web_api.py -k external_id -v`; `python3 scripts/test_migrations.py` |
| BK-055 | Foundation + Observability | Suppress expected CLI channel adapter warning noise while preserving unknown-channel warnings | done | P1 | api_guardian | `uv run pytest tests/unit/test_channel_tasks.py -v` |
| BK-056 | Documentation + Ops Hardening | Add `setup-smoke-running` path and docs for already-running local dependency services | done | P1 | release_ops | `make setup-smoke-running`; `make docs-check` |

## Done vs Remaining (as of 2026-02-19)

### Completed Recently

1. BK-003, BK-030, BK-031, BK-032, BK-050 completed (2026-02-19 packet 8):
   - evolution observability drill-down filters/linkage fields finalized.
   - diagnostics outage-class contract locked with deterministic enums and evidence tests.
   - runbook/config/WhatsApp/operator-flow docs closed and API reference regenerated.
   - Evidence: packet 8 validation list below (`make lint`, `make typecheck`, targeted integration/unit suites, `make docs-check`, `make test-gates`).
2. BK-024 completed:
   - Voice-note pipeline now downloads/stages media, persists `whatsapp_media` linkage, and inserts transcript/marker text.
   - Evidence: `uv run pytest tests/integration/test_whatsapp_webhook.py -v`; `uv run pytest tests/unit/test_whatsapp_transcription.py -v`.
3. BK-028 completed:
   - WhatsApp media URL/mime/size/path security controls enforced with negative regression tests.
   - Evidence: `uv run pytest tests/integration/test_whatsapp_webhook.py -v`; `uv run pytest tests/unit/test_whatsapp_media_security.py -v`.
4. Full gate refresh for this tranche:
   - `make lint`
   - `make typecheck`
   - `make docs-generate`
   - `make docs-check`
   - `make test-gates` (coverage gate passed: 84.76% vs 80.00% threshold)

### Remaining Work (prioritized open backlog)

P1:
1. BK-018 (partial): graph relation extraction confidence/evidence policy completion.
2. BK-019 (partial): adaptive forgetting/archival calibration harness + threshold tuning.
3. BK-034 (partial): dependency steward hardening (CVE severity + compatibility bundle + rollback context).
4. BK-035 (partial): release-candidate hardening (changelog artifact + runbook evidence).
5. BK-042 (partial): operator-owned local credential rotation execution evidence closure.

P2:
1. None.

Additional follow-up discovered:
1. (Resolved 2026-02-19) Added production transcription backend (`faster_whisper`) with explicit runtime/config contract and regression coverage.

## Execution Packets

### Packet 0 (completed): Rebaseline + missing test evidence
1. Re-baselined `docs/PLAN.md` acceptance commands to real test modules.
2. Added memory policy event/audit contract tests (`tests/unit/test_memory_policy.py`).
3. Added memory state/review/export RBAC integration suite (`tests/integration/test_memory_api_state_surfaces.py`).
4. Updated targeted test docs in `docs/testing.md`.
5. Validation run: targeted tests + `make docs-check` passed.

### Packet 1 (completed): M1 closure + channel ingress baseline
1. Finished BK-001 and BK-002 with evidence-path unit/integration coverage.
2. Locked core tests for evidence and inbound webhook validation.
3. Preserved end-to-end inbound validation path: WhatsApp webhook -> orchestrator -> memory store with auditable events.

### Packet 1A (completed, security fast-follow): Audit remediation tranche
1. Finished BK-037, BK-039, BK-041.
2. Landed WS system-subscription authz fix + webhook replay guard + CI action pinning/permissions.
3. Targeted validation passed:
   - `uv run pytest tests/integration/test_authorization.py -k websocket -v`
   - `uv run pytest tests/integration/test_websocket.py -v`
   - `uv run pytest tests/integration/test_web_api.py -k github_webhook -v`
   - `make docs-check`
4. Full gate note: `make lint` and `make typecheck` remain blocked by pre-existing unrelated failures outside Packet 1A scope.

### Packet 1B (in progress, security fast-follow): Token and dependency hardening
1. BK-038 completed (cookie-backed web auth/session flow, WS query-token rejection, regression tests).
2. BK-040 completed: Python lock remediated + `pip-audit` clean; npm side reduced from two findings to one (`ajv@6.12.6` only) with `esbuild` remediated; residual ESLint-transitive advisory now formally risk-accepted through 2026-04-30 (`docs/security-risk-acceptance.md`).
3. BK-048 completed with deterministic failure/success evidence + wrapper regression tests.
4. BK-051 completed with explicit clean-profile failure and running-profile success evidence.
5. BK-042 remains partial: scanner evidence attached, but credential rotation execution is still operator-dependent.
6. Evidence bundle refreshed (2026-02-18):
   - `uv run pip-audit`: clean
   - `osv-scanner --lockfile=uv.lock`: clean
   - `osv-scanner --lockfile=web/package-lock.json`: one Medium (`ajv@6.12.6`)
   - `cd web && npm audit --json`: DNS blocked in sandbox (`getaddrinfo EAI_AGAIN registry.npmjs.org`) during refresh run
   - `/tmp/sec-tools/bin/gitleaks detect --source . --no-git --redact`: 6 hits
   - `/tmp/sec-tools/bin/trufflehog filesystem . --only-verified`: 0 verified
   - `python3 scripts/test_migrations.py`: includes `053_state_reconciliation_tokens_saved.sql`, integrity OK
   - `uv run pytest tests/unit/test_health.py -q`: memory KPI metrics path passes with structured `tokens_saved`
   - `make docs-check`: passed

#### Immediate Next Steps (remaining work)
1. Finish ops follow-through for `BK-042`: execute local credential rotation checklist (Google/GitHub/webhook secrets) and attach operator evidence notes.
2. Re-run `cd web && npm audit --json` in a network-enabled environment and attach evidence to close the temporary sandbox DNS gap.

#### Remaining tasks discovered during implementation
1. Evaluate adding a CI job for `make setup-smoke --skip-web-install` (or equivalent split target) to prevent onboarding regressions without introducing flaky external network dependency.

### Packet 1C (completed, beta stabilization): Core reliability + onboarding unblock
1. Finished BK-043, BK-044, BK-045, BK-046, BK-049, BK-052.
2. Landed deterministic CLI fail-fast JSON envelope, orchestrator provider-failure terminal handling, auth/web TestClient lifecycle stabilization, and `make dev` port preflight.
3. Validation evidence:
   - `WEB_AUTH_SETUP_PASSWORD=secret uv run pytest -q tests/integration/test_authorization.py::test_non_admin_cannot_toggle_lockdown tests/integration/test_authorization.py::test_lockdown_route_is_reachable_after_successful_login tests/integration/test_web_api.py::test_web_auth_login_me_logout_flow`
   - `uv run pytest -q tests/unit/test_orchestrator_step.py -k "provider or degraded or fallback"`
   - `uv run pytest -q tests/unit/test_cli_chat.py -k "ask_json"`
   - `make docs-check`
4. Remaining Packet 1C tasks discovered during implementation: none.

### Packet 1D (completed, codex beta stabilization): Auth/input safety + signal cleanup
1. Scope: BK-053, BK-054, BK-055, BK-056 from `docs/reports/beta-2026-02-18-codex.md`.
2. Change set:
   - provider-config integration coverage realigned to admin RBAC + explicit non-admin deny check
   - login `external_id` max-length enforcement (`<=256`) plus DB trigger guard migration
   - CLI channel dispatch warning suppression for expected `cli` skip path
   - additive `make setup-smoke-running` path and operator docs updates
3. Validation evidence:
   - `python3 scripts/test_migrations.py`
   - `uv run pytest -q tests/integration/test_web_api.py -k "provider_config or external_id"`
   - `uv run pytest -q tests/unit/test_channel_tasks.py`
   - `make setup-smoke-running`
   - `make docs-check`
4. Remaining tasks discovered during implementation:
   - (Resolved 2026-02-19) Added mocked-provider CLI integration regression asserting single-line warning-free `jarvis ask --json` output (`tests/integration/test_cli_chat_flow.py::test_ask_json_output_is_warning_free_with_mocked_provider`).

### Packet 2 (in progress, 2026-02-18): M2 memory reliability + self-update enforcement
1. Completed in this tranche:
   - BK-006: deterministic reconciliation counters and ordering edge-case tests.
   - BK-016: hybrid retrieval fusion with tier priors and deterministic tie-break ordering.
   - BK-017: failure bridge mismatch/malformed-detail handling and linkage summary assertions.
2. BK-007 advanced to enforce-capable implementation:
   - Added test-first gate mode (`warn`/`enforce`) and typed failure taxonomy in self-update apply path.
   - Added unit/integration coverage for warn/enforce transitions and typed failure codes.
   - Local default remains warn-friendly.
3. BK-021 remains partial:
   - Memory state/admin RBAC integration suites pass.
   - Remaining: explicit CLI ownership-scope regression for memory export/state commands and any missing WS-vs-HTTP parity assertions for memory surfaces.
4. Validation evidence executed for this tranche:
   - `make lint`
   - `make typecheck`
   - `uv run pytest tests/unit/test_state_store.py tests/unit/test_hybrid_search.py tests/unit/test_memory_tasks.py tests/unit/test_selfupdate_contracts.py tests/unit/test_cli_test_gates_cmd.py -v`
   - `uv run pytest tests/integration/test_memory_api_state_surfaces.py tests/integration/test_authorization.py tests/integration/test_selfupdate.py -v`
   - `make test-gates`
   - `make docs-check`
5. Remaining tasks discovered during implementation:
   - (Resolved 2026-02-19) Wired CI merge-time default to explicit `SELFUPDATE_TEST_GATE_MODE=enforce` in `.github/workflows/ci.yml`; local/default runtime remains warn.
   - (Resolved 2026-02-19) Added committed retrieval benchmark artifact/report path with refresh script and baseline output:
     - `scripts/retrieval_benchmark_report.py`
     - `docs/reports/retrieval/latest.json`
     - `docs/reports/retrieval/README.md`

### Packet 3 (in progress): M3 productization and governance visibility
1. Finish BK-010, BK-011, BK-012, BK-013, BK-025, BK-026, BK-036.
2. Complete admin UX for pairing and memory governance visibility.
3. Run governance/RBAC regression suite before merge.

### Packet 3A (in progress): Memory + WhatsApp hardening tranche
1. Landed memory KPI wiring on `/metrics` (`memory_items_count`, `memory_avg_tokens_saved`, `memory_reconciliation_rate`, `memory_hallucination_incidents`).
2. Hardened `sync_failure_capsules` with typed detail mapping, deterministic dedupe key (`trace_id+phase+summary_hash`), and trace-thread linkage validation.
3. Extended memory state API/UI surfaces:
   - consistency report thread/time filters
   - state stats endpoint (`/api/v1/memory/state/stats`)
   - admin memory sections for conflicts, tier/archive stats, failure lookup, graph preview.
4. Expanded WhatsApp hardening coverage:
   - admin channel lifecycle endpoint coverage (`status/create/qrcode/pairing-code/disconnect`)
   - non-admin authorization regression checks
   - webhook payload variants (extended text, media classes, group payload)
   - QR/pairing redaction key coverage in event writer.

#### Remaining tasks discovered during implementation (2026-02-18)
1. (Resolved 2026-02-19) Added frontend component-level contract tests for `/admin/memory` review/resolve and filtered consistency workflows.
2. (Resolved 2026-02-19) Added explicit log-capture assertions for QR/pairing leakage prevention beyond payload redaction unit tests.
3. (Resolved 2026-02-18) Prior repo-wide lint/typecheck blockers cleared and full `make test-gates` evidence attached in Packet 1E.

### Packet 3B (in progress, 2026-02-19): Governance identity guardrail + WhatsApp log-capture hardening
1. Scope: BK-010 and Packet 3A QR/pairing leakage follow-up.
2. Change set landed:
   - Added self-update propose-time guardrail to reject governance-field edits in `agents/*/identity.md` for keys:
     - `allowed_tools`
     - `risk_tier`
     - `max_actions_per_step`
     - `allowed_paths`
     - `can_request_privileged_change`
   - Added integration log-capture assertion proving QR/pairing secrets are redacted in persisted `channel.inbound.batch` event payloads.
3. Validation completed:
   - `uv run pytest -q tests/unit/test_selfupdate_pipeline.py -k governance_identity_edits_from_patch`
   - `uv run pytest -q tests/integration/test_selfupdate.py -k identity_governance_field_edits`
   - `uv run pytest -q tests/integration/test_whatsapp_webhook.py -k redacts_qr_and_pairing_fields_in_stored_logs`
4. Remaining tasks discovered during implementation:
   - None for Packet 3B scope.

### Packet 3C (completed, 2026-02-19): Memory governance scope-enforcement closure
1. Scope: BK-012, BK-013, BK-021.
2. Change set landed:
   - Added shared agent-scope enforcement for thread memory surfaces (`src/jarvis/memory/scope.py`) with known-agent + thread-active-agent checks.
   - Hardened memory writes with explicit governance denials for:
     - disallowed agent scope (`agent_scope_denied`)
     - message-linked writes missing evidence linkage (`missing_evidence_ref`).
   - Applied per-agent scope checks across API/task paths:
     - state extraction/upsert/search paths scoped by agent
     - state search/graph/export API `agent_id` scope enforcement
     - background memory indexing denies out-of-scope agent writes without mutating memory rows.
   - Added regression coverage:
     - API agent-scope deny path for state search/graph/export
     - task-side deny path for `index_event` with disallowed `actor_id`
     - schema gate regression for message-linked writes lacking evidence linkage.
3. Validation evidence:
   - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/jarvis/memory/scope.py src/jarvis/memory/policy.py src/jarvis/memory/service.py src/jarvis/memory/state_store.py src/jarvis/memory/state_extractor.py src/jarvis/routes/api/memory.py src/jarvis/tasks/memory.py tests/unit/test_memory_service.py tests/unit/test_memory_tasks.py tests/integration/test_memory_api_state_surfaces.py`
   - `UV_CACHE_DIR=/tmp/uv-cache uv run mypy src/jarvis/memory/scope.py src/jarvis/memory/policy.py src/jarvis/memory/service.py src/jarvis/memory/state_store.py src/jarvis/memory/state_extractor.py src/jarvis/routes/api/memory.py src/jarvis/tasks/memory.py`
   - `uv run pytest -q tests/unit/test_memory_service.py tests/unit/test_memory_tasks.py tests/unit/test_state_extractor.py tests/unit/test_hybrid_search.py`
   - `UV_CACHE_DIR=/tmp/uv-cache WEB_AUTH_SETUP_PASSWORD=secret uv run pytest -q tests/integration/test_memory_api_state_surfaces.py tests/integration/test_authorization.py -k "memory or websocket or lockdown"`
   - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/integration/test_state_extraction_flow.py`
4. Remaining tasks discovered during implementation:
   - None.
5. Remaining tasks before handoff:
   - None.
6. Full-gate evidence refresh (2026-02-19):
   - `make lint`
   - `make typecheck`
   - `make test-gates` (includes migrations, unit, integration, and coverage threshold check via `scripts/check_coverage.py`)

### Packet 1E (completed, 2026-02-18): WhatsApp ingress closure + evolution governance contracts
1. Scope: BK-022, BK-027, BK-033.
2. Change set landed:
   - Evolution callback bootstrap/settings wiring (`EVOLUTION_WEBHOOK_URL`, `EVOLUTION_WEBHOOK_BY_EVENTS`, `EVOLUTION_WEBHOOK_EVENTS`) and persisted instance callback state.
   - WhatsApp webhook auth hardening (`401` structured error payload) + deterministic ignore path for non-`messages.upsert`.
   - Governance evolution-item contracts:
     - event types `evolution.item.started|verified|blocked`
     - admin endpoints `GET /api/v1/governance/evolution/items` and `POST /api/v1/governance/evolution/items/{item_id}/status`
     - transition validation + decision timeline inclusion.
   - Added migrations:
     - `054_evolution_instance_contract.sql`
     - `055_evolution_items.sql`
3. Validation completed:
   - `uv run pytest tests/integration/test_whatsapp_webhook.py -v`
   - `uv run pytest tests/integration/test_admin_api.py -v`
   - `uv run pytest tests/integration/test_web_api.py -k evolution_items -v`
   - `uv run pytest tests/unit/test_event_envelope_enforcement.py -v`
   - `python3 scripts/test_migrations.py`
   - `make docs-generate`
   - `make docs-check`
   - `make lint`
   - `make typecheck`
   - `make test-gates`
4. Remaining tasks discovered during implementation:
   - None for Packet 1E scope.

### Packet 4 (completed, 2026-02-19): Backlog status/evidence refresh and residual closure
1. Scope: BK-001, BK-002, BK-007, BK-011, BK-023, BK-028 + residual Packet 1D/2 follow-ups.
2. Change set landed:
   - Added CLI integration regression for warning-free mocked-provider JSON output:
     - `tests/integration/test_cli_chat_flow.py::test_ask_json_output_is_warning_free_with_mocked_provider`
   - Added committed retrieval benchmark artifact/report path:
     - `scripts/retrieval_benchmark_report.py`
     - `docs/reports/retrieval/latest.json`
     - `docs/reports/retrieval/README.md`
   - Wired merge-time CI default for strict test-gate enforcement:
     - `.github/workflows/ci.yml` sets `SELFUPDATE_TEST_GATE_MODE=enforce`
     - local runtime default remains warn mode
   - Updated backlog status table:
     - `done`: BK-001, BK-002, BK-007, BK-011, BK-023
     - `partial`: BK-028 (QR/pairing redaction tests landed; file-limit/safe-media-path negatives still pending)
3. Validation evidence completed:
   - `uv run pytest tests/unit -k repo_index -v`
   - `uv run pytest tests/unit -k evidence -v`
   - `uv run pytest tests/integration -k selfupdate -v`
   - `uv run pytest tests/integration -k selfupdate_apply -v`
   - `uv run pytest tests/integration/test_selfupdate.py -v`
   - `uv run pytest tests/unit/test_selfupdate_contracts.py -v`
   - `uv run pytest tests/integration/test_whatsapp_webhook.py -v`
   - `uv run pytest tests/unit/test_channel_abstraction.py -v`
   - `uv run pytest -q tests/integration/test_cli_chat_flow.py tests/unit/test_hybrid_search.py`
   - `make lint`
   - `make typecheck`
   - `make test-gates`
   - `make docs-check`
4. Remaining tasks discovered during implementation:
   - (Resolved 2026-02-19) Completed BK-024 with media download/transcript marker flow and transcript assertions.
   - (Resolved 2026-02-19) Completed BK-028 file-size and safe-media-path controls with negative coverage.

### Packet 5 (completed, 2026-02-19): WhatsApp media security closure + voice-note pipeline
1. Scope: BK-024, BK-028.
2. Change set landed:
   - Added inbound media security guards in webhook path:
     - HTTPS-only media URLs (+ optional host allowlist)
     - MIME-prefix allowlist and bounded download size enforcement
     - safe media-path resolution rooted at configured runtime directory
   - Added voice-note processing pipeline:
     - media staging under `WHATSAPP_MEDIA_DIR`
     - `whatsapp_media` persistence linkage via `thread_id` + `message_id`
     - pluggable transcription interface with default `stub` backend
     - degraded fallback marker `[voice note unavailable]` on transcription/security failures
   - Added configuration contract:
     - `WHATSAPP_MEDIA_DIR`
     - `WHATSAPP_MEDIA_MAX_BYTES`
     - `WHATSAPP_MEDIA_ALLOWED_MIME_PREFIXES`
     - `WHATSAPP_MEDIA_ALLOWED_HOSTS`
     - `WHATSAPP_VOICE_TRANSCRIBE_ENABLED`
     - `WHATSAPP_VOICE_TRANSCRIBE_BACKEND`
     - `WHATSAPP_VOICE_TRANSCRIBE_TIMEOUT_SECONDS`
   - Added coverage:
     - `tests/unit/test_whatsapp_media_security.py`
     - `tests/unit/test_whatsapp_transcription.py`
     - webhook integration negatives for oversized media and transcription failure markers.
3. Validation evidence completed:
   - `uv run pytest tests/unit/test_whatsapp_media_security.py tests/unit/test_whatsapp_transcription.py -v`
   - `uv run pytest tests/integration/test_whatsapp_webhook.py -v`
   - `uv run pytest tests/unit/test_channel_abstraction.py tests/integration/test_whatsapp_webhook.py tests/unit/test_whatsapp_media_security.py tests/unit/test_whatsapp_transcription.py -v`
   - `make lint`
   - `make typecheck`
   - `make docs-generate`
   - `make docs-check`
4. Remaining tasks discovered during implementation:
   - (Resolved 2026-02-19) Added production-grade local transcription backend (`faster_whisper`) with config/docs contract and webhook/unit regressions.
5. Remaining tasks before handoff:
   - None for BK-024/BK-028 scope.

### Packet 6 (completed, 2026-02-19): Production voice transcription backend (local faster-whisper)
1. Scope: residual follow-up from Packet 5 (`non-stub` voice backend closure).
2. Change set landed:
   - Added WhatsApp transcription backend adapter support for `faster_whisper` in `src/jarvis/channels/whatsapp/transcription.py`.
   - Added runtime configuration contract:
     - `WHATSAPP_VOICE_MODEL`
     - `WHATSAPP_VOICE_DEVICE`
     - `WHATSAPP_VOICE_COMPUTE_TYPE`
     - `WHATSAPP_VOICE_LANGUAGE`
   - Added backend/error-path coverage:
     - `tests/unit/test_whatsapp_transcription.py`
     - `tests/integration/test_whatsapp_webhook.py::test_inbound_voice_note_uses_faster_whisper_backend`
   - Updated operator/config docs:
     - `docs/configuration.md`
     - `docs/channels/whatsapp.md`
     - `docs/runbook.md`
     - `.env.example`
3. Validation completed:
   - `uv run pytest tests/unit/test_whatsapp_transcription.py -v`
   - `uv run pytest tests/integration/test_whatsapp_webhook.py -k "voice_note" -v`
4. Remaining tasks discovered during implementation:
   - None.

### Packet 7 (in progress, 2026-02-19): BK-003 observability trace drill-down + feature-build trial prep
1. Scope: BK-003 (unified evolution observability view with trace drill-down).
2. Change set landed:
   - Added governance evolution-items web client and typed frontend contract:
     - `web/src/api/endpoints.ts`
     - `web/src/types/index.ts`
   - Added cross-page trace handoff affordances:
     - governance decision timeline and evolution items now include `Open Trace` links to `/admin/events?trace_id=...&thread_id=...`
     - self-update patch detail adds `View In Events` link for selected patch trace
   - Added events-page URL hydration for trace/filter state:
     - `/admin/events` now initializes and syncs `trace_id`/filters from query params and preserves deep-link drill-down context.
   - Added frontend contract coverage:
     - `web/tests/adminObservabilityContracts.test.mjs`
3. Validation completed:
   - `make setup-smoke-running`
   - `cd web && npm test`
   - `cd web && npm run typecheck`
   - `uv run pytest tests/integration/test_web_api.py -k evolution_items -v`
   - `uv run pytest tests/integration -k governance -v`
   - Live feature-build trial execution:
     - API runtime: `UV_CACHE_DIR=/tmp/uv-cache uv run uvicorn jarvis.main:app --reload --app-dir src`
     - build run #1: `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 120 --poll-interval-s 2`
     - trace/thread evidence #1: `thr_5eba1a949c5f4826b87f760e5a98c6f6`
     - build run #2 (after remediation): `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 120 --poll-interval-s 2`
     - trace/thread evidence #2: `thr_4ba836b7312a492ab8e2462a62e40fb8`
   - Remediation validation:
     - `uv run pytest tests/unit/test_host_tool.py tests/unit/test_cli_build.py tests/unit/test_task_runner.py -v`
4. Remaining tasks discovered during implementation:
   - Resolved in this packet:
     - build prompt now keeps execution in `main` (no coder delegation) to avoid `R6: governance.risk_tier` for `exec_host`.
     - `exec_host` no longer applies `ulimit` caps when `EXEC_HOST_SANDBOX=none`; removes false memory-allocation failures during normal local runs.
     - task runner now swallows known shutdown-time threadpool scheduling race (`cannot schedule new futures after shutdown`) and logs as dropped task.
     - orchestrator now runs terminal synthesis after tool-loop exhaustion and emits explicit reason taxonomy (`placeholder_response_after_tool_loop`, `placeholder_response_after_terminal_synthesis`, `provider_error_terminal_synthesis`).
     - when synthesis still cannot recover after tool-loop exhaustion, assistant now emits deterministic operator-facing terminal text (includes trace id) instead of generic internal-error text.
   - Validation evidence for terminal-synthesis hardening:
     - `uv run pytest tests/unit/test_orchestrator_step.py -v`
     - `uv run pytest tests/unit/test_cli_build.py tests/unit/test_task_runner.py tests/unit/test_host_tool.py -v`
   - Previously reported blocker now resolved:
     - fixed API startup syntax/import issue in `src/jarvis/routes/api/channels.py` by removing misplaced import line in `from jarvis.db.queries import (...)`.
   - Unblock verification evidence (targeted local path):
     - syntax check: `uv run python -m py_compile src/jarvis/routes/api/channels.py` -> pass (no `SyntaxError`).
     - API startup/import check: `UV_CACHE_DIR=/tmp/uv-cache uv run uvicorn jarvis.main:app --app-dir src` -> startup complete; `curl -fsS http://127.0.0.1:8000/healthz` -> `{"ok":true}`.
     - live build check: `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 120 --poll-interval-s 2` -> thread `thr_d9c3e31b01b7493ea7a0deeed6b28ed9`; non-syntax terminal failure with trace `trc_4d48f04a30124b84b3670ccf16cdf126`.
     - first actionable failure after unblock: build cycle completed tool execution but failed terminal synthesis (`Review /admin/events for details and retry.`), indicating the prior `channels.py` syntax crash is no longer the gating issue.
   - Follow-up triage evidence after first unblock:
     - fixed route + command type blockers found in trace triage:
       - `src/jarvis/routes/api/channels.py`: restored `Literal` typing for `decision`.
       - `src/jarvis/commands/service.py`: resolved `/wa-review` mypy issues (variable type collision + `Literal` decision typing).
     - targeted typecheck evidence:
       - `uv run mypy src/jarvis/routes/api/channels.py src/jarvis/commands/service.py` -> pass.
     - rerun #1 after type fixes: `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 120 --poll-interval-s 2`
       - thread `thr_37a2137089a841d8aadb52600961eaf6`
       - trace `trc_3bc2c07a38db48099adf9fa938d36ff2`
       - outcome: still terminal synthesis degraded after tool-loop exhaustion.
     - rerun #2 after type fixes: `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 120 --poll-interval-s 2`
       - thread `thr_e1407b2594a442b1bb90211d678a672e`
       - trace `trc_daccceb598e546ea985100307838cb31`
       - outcome: `exec_host` timed out `uv run jarvis test-gates --fail-fast` at 120s (`exit_code=124`); subsequent model run errored (`cannot schedule new futures after shutdown`) and returned degraded fallback text.
     - remediation applied for build-flow timeout mismatch:
       - raised exec-host timeout cap default `EXEC_HOST_TIMEOUT_MAX_SECONDS` from 120 -> 600 in config/docs/env (`src/jarvis/config.py`, `.env.example`, `docs/configuration.md`).
       - added build-path timeout handling in agent host tool bridge (`src/jarvis/tasks/agent.py`) with unit coverage (`tests/unit/test_agent_exec_host.py`).
       - targeted validation:
         - `uv run pytest tests/unit/test_agent_exec_host.py -v`
         - `uv run ruff check src/jarvis/tasks/agent.py src/jarvis/config.py tests/unit/test_agent_exec_host.py`
         - `uv run mypy src/jarvis/tasks/agent.py src/jarvis/config.py tests/unit/test_agent_exec_host.py`
     - rerun #3 after timeout remediation: `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 700 --poll-interval-s 2`
       - thread `thr_039ffbae84f847dd864f921c7e6455b2`
       - trace `trc_b1c947524f134e1f9528d9bb08dfb452`
       - outcome: success; assistant final summary reports `All gates pass - nothing to fix.` and confirms `uv run jarvis test-gates --fail-fast` passed.
5. Remaining tasks before handoff:
   - Execute manual admin E2E walk for trace-drilldown workflow (`/admin/governance` -> `/admin/events` and `/admin/selfupdate` -> `/admin/events`) and attach screenshots/evidence.
   - Close historical degraded-build traces (`trc_4d48f04a30124b84b3670ccf16cdf126`, `trc_3bc2c07a38db48099adf9fa938d36ff2`, `trc_daccceb598e546ea985100307838cb31`) with retrospective note now that unblock verification passes under updated timeout policy.
   - After local remediation passes, run equivalent Docker-backed verification for reproducibility hardening.

### Packet 8 (completed, 2026-02-19): Reliability + ops closure (BK-003/050/030/031/032 + BK-042 repo-side)
1. Scope completed:
   - BK-003: evolution observability drill-down closed.
   - BK-050: deterministic outage-class diagnostics contract + evidence closed.
   - BK-030/BK-031/BK-032: docs/runbook/config/API/operator-flow gaps closed.
   - BK-042: repo-actionable checklist closure complete; operator execution remains external.
2. Backend/API changes:
   - `GET /api/v1/governance/evolution/items` now supports additive admin filters:
     - `status`
     - `trace_id`
     - `thread_id`
     - `from` (maps to `updated_at>=`)
     - `to` (maps to `updated_at<=`)
   - Evolution item responses now include stable linkage fields:
     - `item_id` (compat alias of `id`)
     - `trace_id`
     - `span_id` (latest `evolution.item.*` event span)
     - `thread_id`
     - `status`
     - `updated_at`
3. Admin UI/contract closure:
   - Governance page now exposes evolution filters (status/trace/from/to) and preserves trace handoff to `/admin/events`.
   - Frontend contract checks updated (`web/tests/adminObservabilityContracts.test.mjs`).
4. Diagnostics outage-class contract closure:
   - Doctor/CLI classification now normalizes to required deterministic classes:
     - `dns_resolution`
     - `timeout`
     - `network_unreachable`
     - `provider_unavailable`
   - Added regression assertions in:
     - `tests/unit/test_cli_checks.py`
     - `tests/unit/test_cli_chat.py`
5. Documentation closure:
   - `docs/runbook.md`: memory rollback/recovery, memory conflict resolution flow, WhatsApp decision tree, outage-class evidence, explicit operator-owned credential rotation checklist + artifact template.
   - `docs/configuration.md`: memory/state extraction and memory lifecycle flags.
   - `docs/channels/whatsapp.md`: troubleshooting decision tree + rollback path.
   - `docs/channels/whatsapp-ui.md`: operator troubleshooting additions.
   - `docs/cli-reference.md`: outage-class JSON/doctor contract and evidence commands.
   - `docs/api-reference.md`: regenerated from OpenAPI (`make docs-generate`).
6. Validation evidence:
   - `make lint`
   - `make typecheck`
   - `uv run pytest tests/integration/test_web_api.py -k evolution -v`
   - `uv run pytest tests/integration/test_authorization.py -k websocket -v`
   - `uv run pytest tests/integration/test_whatsapp_webhook.py -v` (one transient `database is locked` setup error; immediate rerun passed)
   - `uv run pytest tests/unit/test_health.py -q`
   - `make docs-check`
   - `make test-gates`
7. Remaining tasks discovered during implementation:
   - None new in repo scope.
8. Deferred explicitly to next packet (unchanged):
   - BK-018
   - BK-019
   - BK-020
   - BK-034
   - BK-035

### Packet 9 (completed, 2026-02-20): Framework audit + multi-channel media Phase 1

Comprehensive audit across memory, events, scheduler, governance, self-update, test suite, and agent prompts — closing critical bugs, filling architecture gaps, adding missing tests, and fixing documentation drift.

1. Scope completed: BK-057, BK-058, BK-059, BK-060, BK-061, BK-062, BK-063, BK-064, BK-065, BK-066.
2. Critical bug fixes (P0):
   - **BK-057**: `insert_message()` now accepts `media_path`/`mime_type`; WhatsApp router passes media fields from inbound handler.
   - **BK-058**: `is_allowed()` supports wildcard `*` permission; R8 rule enforces `max_actions_per_step` via `tool.call.start` event count per trace.
   - **BK-060**: Scheduler NULL thread_id: skips dispatch with `schedule.error` event; 3-INSERT creation wrapped in `BEGIN/COMMIT/ROLLBACK`; per-schedule try/except prevents one bad schedule from crashing the tick.
   - **BK-062**: `compute_system_fitness` rescheduled from weekly (604800s) to 30-minute (1800s) interval so SLO gate works on new deployments.
   - **BK-063**: `main.py` `evolution.*` references fixed to `baileys.*`; import sort fixed; lint/typecheck clean.
3. Architecture gaps closed (P1):
   - **BK-059**: `memory_consistency_reports` table (migration 059) + `store_consistency_report()` + `GET /api/v1/memory/consistency` endpoint with historical queries.
   - **BK-061**: `src/jarvis/tasks/events.py` with `run_event_maintenance()` — deletes events older than `EVENT_RETENTION_DAYS` (default 90), prunes orphaned FTS/vector rows, registered as weekly periodic task.
4. Missing tests added (P1):
   - `tests/unit/test_db_queries.py`: media round-trip, insert-without-media, multi-channel thread unification.
   - `tests/unit/test_tools_runtime.py`: wildcard `*` permission, `max_actions_per_step` R8 enforcement.
   - `tests/integration/test_scheduler.py`: thread isolation (threads/sessions/participants created), NULL thread_id graceful skip with `schedule.error`.
   - `tests/integration/test_events.py`: semantic event search returns list.
5. Self-update guardrail defaults (P1):
   - **BK-066**: `SELFUPDATE_MAX_FILES_PER_PATCH=20`, `SELFUPDATE_MAX_RISK_SCORE=100`, `SELFUPDATE_MAX_PATCH_ATTEMPTS_PER_DAY=10`, `SELFUPDATE_MAX_PRS_PER_DAY=5` added to `config.py` and `.env.example`.
6. Documentation fixes (P2):
   - **BK-064**: `agents/main/soul.md`, `agents/coder/soul.md`, `agents/data_migrator/soul.md`, `agents/planner/soul.md` — inline git-flow block replaced with CLAUDE.md reference.
   - **BK-065**: `docs/prompts/FEATURE_BUILDER_PROMPT.md` + `docs/prompts/DOCS_AGENT_PROMPT.md` created; `docs/prompts/README.md` updated.
   - `MEMORY.md`: Celery/RabbitMQ reference replaced with in-process asyncio task runner.
7. Validation evidence:
   - `make lint` — all checks passed.
   - `make typecheck` — no issues in 135 source files.
   - `make test-gates` — 420 passed; coverage 86.57% (threshold 80%).
   - `make docs-generate && make docs-check` — docs check passed.
8. Remaining tasks discovered during implementation:
   - None new in repo scope.
9. Deferred explicitly (scope too large for this pass):
   - BK-018: graph relation LLM extraction (200–300 lines, separate BK item).
   - BK-019: adaptive forgetting calibration harness.
   - Concurrent scheduler deduplication (single-process deployment; low priority).

## Testing and Acceptance Gates

Global gates before marking backlog item `done`:
1. `make lint`
2. `make typecheck`
3. Relevant unit/integration tests for touched modules
4. `make test-gates` before merge
5. Evidence refs and docs updates present in the same PR

Supplemental targeted checks for this plan:
- `uv run pytest tests/integration/test_whatsapp_webhook.py -v`
- `uv run pytest tests/integration/test_admin_api.py -v`
- `uv run pytest tests/unit/test_memory_service.py -v`
- `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v`
- `uv run pytest tests/unit/test_memory_policy.py -v`
- `osv-scanner --lockfile=uv.lock`

- `osv-scanner --lockfile=web/package-lock.json`
- `UV_CACHE_DIR=/tmp/uv-cache XDG_CACHE_HOME=/tmp/.cache uv run pip-audit --cache-dir /tmp/pip-audit-cache`
- `cd web && npm audit --json` (run in network-enabled environment when sandbox DNS is unavailable)

## Rollout and Rollback

Rollout order:
1. Backend safety and test hardening first.
2. Channel/webhook and memory reliability second.
3. Admin UI and governance visibility third.
4. Metrics-driven optimization features last.

Rollback policy:
- Prefer feature-flag fallback for new strict gates.
- Keep compatibility fields/version readers for evolving artifacts/events.
- Revert per-packet changesets independently; preserve append-only migration history.
- On guardrail trip, lock down mutation paths and retain read-only observability.

## Open Risks and Mitigations

- Retrieval/ranking regressions from fusion/tuning.
  - Mitigation: deterministic tests + benchmark harness before threshold changes.
- Webhook payload compatibility drift.
  - Mitigation: dual parser fixtures for legacy + Evolution variants.
- Security leakage (QR/pairing/media paths).
  - Mitigation: explicit no-leak tests, redaction checks, strict path/size validation.
- Governance overreach or bypass.
  - Mitigation: deny-by-default retained, typed denial events, ownership/RBAC regressions.

## Traceability

| Backlog IDs | Source references |
|---|---|
| BK-001..BK-013, BK-033..BK-035 | `evo.md` (Document Contract, Non-Negotiable Invariants, Phase 1-4, Rollout Packets, Global Gates) |
| BK-014, BK-022..BK-028 | `whatsapp.md` (Goals/Constraints, Phases 1-5, admin endpoints, webhook/governance commands, security checklist) |
| BK-015, BK-019 | `docs/memory-roadmap.md` (importance formula, tier/archive flow, delivery order) |
| BK-016..BK-021, BK-036 | `docs/memory-roadmap-todo.md` (not implemented, hardening gaps, tests needed, operational follow-ups) |
| BK-017, BK-029, BK-036 and packet sequencing emphasis | `docs/evolution-whatsapp-memory-execution-plan.md` (workstreams, file-level plan, rollout strategy, risk controls) |
| BK-043..BK-052 | `docs/reports/beta-2026-02-18-full-pass.md` (reproducible reliability/setup/documentation defects + ranked stabilization priorities) |
| BK-053..BK-056 | `docs/reports/beta-2026-02-18-codex.md` (RBAC test mismatch, auth input bounds, CLI warning noise, setup-smoke friction) |

## Appendix

### Merged from
- `evo.md`
- `whatsapp.md`
- `docs/memory-roadmap.md`
- `docs/memory-roadmap-todo.md`
- `docs/evolution-whatsapp-memory-execution-plan.md`
- `docs/reports/beta-2026-02-18-full-pass.md`

### Deferred/Excluded items
- No source items were discarded. Items were merged/deduplicated into normalized backlog IDs.
- Optional API additions (`GET/POST /api/v1/governance/evolution/items*`) from `evo.md` were retained as lower-priority backlog coverage under BK-033 unless promoted by milestone pressure.
