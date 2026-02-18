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
| Foundation + Observability | 3 | 3 | 0 |
| Self-Coding + Release Loop | 3 | 3 | 0 |
| Governance + Safety | 1 | 4 | 1 |
| Memory Intelligence + Retrieval | 1 | 7 | 2 |
| WhatsApp Channel + Admin UX | 0 | 1 | 6 |
| Documentation + Ops Hardening | 0 | 1 | 3 |

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
| BK-001 | Foundation + Observability | Ground-truth index dependency edges + freshness CI gate | partial | P0 | planner | `make lint`; `make typecheck`; `uv run pytest tests/unit -k repo_index -v` |
| BK-002 | Foundation + Observability | Evidence validator required for all mutation-capable flows | partial | P0 | security_reviewer | `uv run pytest tests/unit -k evidence -v`; `uv run pytest tests/integration -k selfupdate -v` |
| BK-003 | Foundation + Observability | Unified evolution observability view with trace drill-down | partial | P1 | web_builder | `uv run pytest tests/integration -k governance -v`; manual admin flow validation |
| BK-004 | Foundation + Observability | Memory denial/redaction event emission contract completion | done | P1 | api_guardian | `uv run pytest tests/unit/test_memory_policy.py -v` |
| BK-005 | Self-Coding + Release Loop | Self-update artifact schema versioning | done | P0 | coder | `uv run pytest tests/integration -k selfupdate -v` |
| BK-006 | Self-Coding + Release Loop | Deterministic reconciliation edge-case lock tests + run summary events | done | P0 | tester | `uv run pytest tests/unit/test_state_store.py -v`; `uv run pytest tests/unit/test_memory_tasks.py -v` |
| BK-007 | Self-Coding + Release Loop | Test-first gate (failing-test proof + coverage floor + critical-path test requirement) | partial | P0 | tester | `make test-gates`; `uv run pytest tests/integration/test_selfupdate.py -v`; `uv run pytest tests/unit/test_selfupdate_contracts.py -v` |
| BK-008 | Self-Coding + Release Loop | PR base-branch enforcement test (`dev` only) | done | P1 | release_ops | `uv run pytest tests/unit/test_github_tasks.py -v` |
| BK-009 | Self-Coding + Release Loop | Failure remediation scoring uses acceptance/rejection outcomes | done | P1 | researcher | `uv run pytest tests/unit -k failure_capsule -v` |
| BK-010 | Governance + Safety | Block self-permission escalation edits on agent identity governance fields | partial | P0 | security_reviewer | `uv run pytest tests/integration -k governance -v` |
| BK-011 | Governance + Safety | Self-update deployment gate state machine + typed failure taxonomy | partial | P0 | release_ops | `uv run pytest tests/integration -k selfupdate_apply -v` |
| BK-012 | Governance + Safety | Memory governance hardening (schema write gates + deny/redaction governance filters) | partial | P0 | security_reviewer | `uv run pytest tests/unit/test_memory_policy.py -v`; `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v` |
| BK-013 | Governance + Safety | Explicit per-agent memory read/write scope checks across APIs/tasks | partial | P0 | security_reviewer | RBAC integration regressions for memory routes/tasks |
| BK-014 | Governance + Safety | WhatsApp risky/unknown sender review queue with in-chat approve/deny commands | not_started | P1 | main | webhook + review-flow integration tests |
| BK-015 | Memory Intelligence + Retrieval | Multi-tier memory lifecycle and archival flow with score-driven migration | done | P1 | planner | `uv run pytest tests/unit -k state_store -v` |
| BK-016 | Memory Intelligence + Retrieval | Retrieval fusion completion (RRF for vector + FTS5 + filters + tier priors) | done | P0 | planner | `uv run pytest tests/unit/test_hybrid_search.py -v` |
| BK-017 | Memory Intelligence + Retrieval | Failure bridge typed mapping + stable dedupe key (`trace_id+phase+summary_hash`) | done | P1 | planner | `uv run pytest tests/unit/test_memory_tasks.py -v` |
| BK-018 | Memory Intelligence + Retrieval | Graph relation extraction confidence/evidence policy completion | partial | P1 | researcher | traversal + relation-extraction tests |
| BK-019 | Memory Intelligence + Retrieval | Adaptive forgetting/archival calibration harness and threshold tuning | partial | P1 | memory_curator | maintenance/task tests + workload simulation |
| BK-020 | Memory Intelligence + Retrieval | Consistency evaluator endpoint/UI surface and historical queryability | partial | P1 | planner | API + admin UI tests for reports/filters |
| BK-021 | Memory Intelligence + Retrieval | Full memory endpoint/CLI/RBAC test suite for new state/review/export surfaces | partial | P0 | tester | `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v`; `uv run pytest tests/integration/test_authorization.py -v` |
| BK-022 | WhatsApp Channel + Admin UX | Evolution sidecar bootstrap (persistent auth, API key auth, webhook callback) | done | P0 | api_guardian | callback contract/env wiring landed (`EVOLUTION_WEBHOOK_URL`, `EVOLUTION_WEBHOOK_BY_EVENTS`, `EVOLUTION_WEBHOOK_EVENTS`); instance callback state persisted (`054_evolution_instance_contract.sql`); coverage in `tests/integration/test_admin_api.py` + `python3 scripts/test_migrations.py` |
| BK-023 | WhatsApp Channel + Admin UX | WhatsApp channel implementation: text/media/reaction/groups/thread mapping | partial | P0 | api_guardian | `uv run pytest tests/integration/test_whatsapp_webhook.py -v`; `uv run pytest tests/unit/test_channel_abstraction.py -v` |
| BK-024 | WhatsApp Channel + Admin UX | Voice-note pipeline (download, transcribe, memory linkage) | not_started | P0 | api_guardian | voice message integration tests with transcript assertions |
| BK-025 | WhatsApp Channel + Admin UX | Admin pairing APIs (`status/create/qrcode/pairing-code/disconnect`) + auth/rate limits | partial | P0 | api_guardian | `uv run pytest tests/integration/test_admin_api.py -v`; `uv run pytest tests/integration/test_authorization.py -v` |
| BK-026 | WhatsApp Channel + Admin UX | Admin pairing UI (QR, status polling, connect/disconnect flows) | partial | P1 | web_builder | manual UI validation at `/admin/channels` + endpoint contract tests |
| BK-027 | WhatsApp Channel + Admin UX | Webhook auth and payload normalization (`messages.upsert` variants) | done | P0 | api_guardian | webhook secret reject contract + no-op ignore path for non-upsert events + variant normalization; `uv run pytest tests/integration/test_whatsapp_webhook.py -v` |
| BK-028 | WhatsApp Channel + Admin UX | WhatsApp security controls (no QR/code leakage, file limits, safe media paths) | not_started | P0 | security_reviewer | log-redaction checks + negative security tests |
| BK-029 | Documentation + Ops Hardening | Memory Prometheus KPI wiring and docs (`items_count`, `avg_tokens_saved`, `reconciliation_rate`, `hallucination_incidents`) | done | P1 | release_ops | structured `tokens_saved` persisted (`053_state_reconciliation_tokens_saved.sql`) and `/metrics` validation (`uv run pytest tests/unit/test_health.py -q`) |
| BK-030 | Documentation + Ops Hardening | Add rollback/runbook and config docs for new memory tables/tasks/flags | not_started | P1 | release_ops | updates in `docs/runbook.md` and `docs/configuration.md` |
| BK-031 | Documentation + Ops Hardening | WhatsApp operator docs and troubleshooting coverage | partial | P1 | release_ops | `docs/channels/whatsapp.md` + `docs/channels/whatsapp-ui.md` updated |
| BK-032 | Documentation + Ops Hardening | API/schema docs for memory routes and conflict-resolution operator flow | partial | P2 | planner | `docs/api-reference.md` coverage + `make docs-check` |
| BK-033 | Foundation + Observability | Evolution/governance event contract additions (`evolution.item.*`) | done | P2 | api_guardian | event types + payload minimum key enforcement + admin query/update APIs landed (`055_evolution_items.sql`); `uv run pytest tests/integration/test_web_api.py -k evolution_items -v`; `uv run pytest tests/unit/test_event_envelope_enforcement.py -v` |
| BK-034 | Governance + Safety | Dependency steward hardening (CVE severity, compatibility bundle, rollback-ready PR context) | partial | P1 | dependency_steward | `uv run pytest tests/unit/test_governance_tasks.py -v` |
| BK-035 | Governance + Safety | Release-candidate hardening (changelog artifact + runbook evidence) | partial | P1 | release_candidate | `uv run pytest tests/unit/test_governance_tasks.py -v` |
| BK-036 | Memory Intelligence + Retrieval | Memory admin UI completion (conflicts, tier/archive stats, failure lookup, graph preview) | partial | P1 | web_builder | admin memory page sections visible and populated |
| BK-037 | Governance + Safety | Enforce admin-only WS system subscription (`subscribe_system`) and add regression tests | done | P0 | security_reviewer | `uv run pytest tests/integration/test_authorization.py -k websocket -v` |
| BK-038 | Governance + Safety | Web auth hardening: remove WS query-token transport + replace persistent browser token storage model | done | P0 | api_guardian | `uv run pytest tests/integration/test_websocket.py -v`; `uv run pytest tests/integration/test_authorization.py -k websocket -v`; manual login/session regression |
| BK-039 | Governance + Safety | Webhook replay defense (delivery-id/nonce + bounded replay window) | done | P0 | security_reviewer | `uv run pytest tests/integration/test_web_api.py -k github_webhook -v` with replay negatives |
| BK-040 | Documentation + Ops Hardening | Dependency vuln remediation from audit (`starlette`, `ajv`, `esbuild`) and lockfile refresh | done | P0 | dependency_steward | Python lock + audit clean (`uv run pip-audit`); npm `esbuild` path remediated (`vite@7.3.1` -> `esbuild@0.27.3`); residual ESLint-transitive `ajv@6.12.6` formally risk-accepted with sunset (`docs/security-risk-acceptance.md`, 2026-04-30); `osv-scanner --lockfile=web/package-lock.json` re-run shows single remaining accepted finding |
| BK-041 | Documentation + Ops Hardening | CI supply-chain hardening: pin third-party GitHub actions to SHAs and add top-level CI permissions | done | P0 | release_ops | workflow CI pass + branch-policy/release workflow validation |
| BK-042 | Documentation + Ops Hardening | Secret hygiene follow-up: rotate local exposed OAuth credentials and add pre-commit secret scan command docs | partial | P1 | release_ops | Pre-commit secret scan command documented and codified (`make secret-scan` in `Makefile`, `docs/local-development.md`, `docs/runbook.md`); local Google/GitHub/webhook credential rotation remains operator-owned and pending execution evidence |
| BK-043 | Self-Coding + Release Loop | Fail-fast `jarvis ask --json` path on provider transport/DNS errors with bounded fallback budget + deterministic error payload | done | P0 | api_guardian | `uv run pytest -q tests/unit/test_cli_chat.py -k "ask_json"` passes with structured `ok=false` envelope and non-zero exit |
| BK-044 | Self-Coding + Release Loop | Guard orchestrator/state-extractor error paths to prevent long traceback/timeouts after provider failure | done | P0 | planner | `uv run pytest -q tests/unit/test_orchestrator_step.py -k "provider or degraded or fallback"` passes; degraded assistant message + `model.run.error` event emitted on provider failure |
| BK-045 | Governance + Safety | Deflake and unhang `test_non_admin_cannot_toggle_lockdown` via lifecycle/teardown instrumentation and fix | done | P0 | tester | `WEB_AUTH_SETUP_PASSWORD=secret uv run pytest -q tests/integration/test_authorization.py::test_non_admin_cannot_toggle_lockdown` and login flow tests complete deterministically |
| BK-046 | Foundation + Observability | Add `make dev` host-port preflight (`11434`, `30000`, `8080`) with actionable remediation output | done | P0 | release_ops | `python3 scripts/dev_preflight_ports.py` fails fast on occupied ports and prints remediation commands |
| BK-047 | Documentation + Ops Hardening | Document Docker/local port-conflict troubleshooting and optional alternate-port profile | done | P1 | release_ops | docs updates landed in `docs/local-development.md` and `docs/runbook.md`; `make docs-check` passed |
| BK-048 | Documentation + Ops Hardening | Harden `make web-install` path with deterministic npm diagnostics/retry guidance and fallback commands | done | P1 | web_builder | failure/success evidence captured (`/tmp/jarvis-web-install-failure.log`, `/tmp/jarvis-web-install-success.log`) and wrapper hardened with deterministic `network_blocked_or_sandboxed` classification + npm debug-log extraction (`scripts/web_install.py`) plus regression tests (`tests/unit/test_web_install_script.py`) |
| BK-049 | Documentation + Ops Hardening | Update quick-start docs to require `make web-install` before web dev/build/typecheck/lint commands | done | P0 | release_ops | `README.md` and `docs/getting-started.md` include explicit sequencing; `make docs-check` passes |
| BK-050 | Foundation + Observability | Improve CLI/doctor environment diagnostics to distinguish sandbox/network/provider outage classes | partial | P1 | api_guardian | doctor HTTP checks now classify `dns_resolution`/`timeout`/network classes and CLI JSON errors map to outage classes; pending targeted evidence run |
| BK-051 | Foundation + Observability | Add reproducible new-user setup smoke target covering API + web bootstrap path | done | P1 | tester | local evidence captured: `make setup-smoke` fails deterministically on occupied ports (`11434`,`30000`,`8080`) with remediation; `make setup-smoke-running` passes bootstrap checks end-to-end |
| BK-052 | Self-Coding + Release Loop | Add regression tests for provider-unavailable and DNS-failure UX in CLI/API flows | done | P0 | tester | CLI/orchestrator failure-mode tests pass and enforce structured fast-fail behavior (`ok=false`, failure kind metadata, degraded response persistence) |
| BK-053 | Governance + Safety | Align provider-config integration tests with admin-only RBAC and retain non-admin deny regression | done | P0 | tester | `uv run pytest tests/integration/test_web_api.py -k provider_config -v` |
| BK-054 | Governance + Safety | Harden auth login `external_id` bounds with API validation + DB trigger guard (`1..256`) | done | P0 | security_reviewer | `uv run pytest tests/integration/test_web_api.py -k external_id -v`; `python3 scripts/test_migrations.py` |
| BK-055 | Foundation + Observability | Suppress expected CLI channel adapter warning noise while preserving unknown-channel warnings | done | P1 | api_guardian | `uv run pytest tests/unit/test_channel_tasks.py -v` |
| BK-056 | Documentation + Ops Hardening | Add `setup-smoke-running` path and docs for already-running local dependency services | done | P1 | release_ops | `make setup-smoke-running`; `make docs-check` |

## Execution Packets

### Packet 0 (completed): Rebaseline + missing test evidence
1. Re-baselined `docs/PLAN.md` acceptance commands to real test modules.
2. Added memory policy event/audit contract tests (`tests/unit/test_memory_policy.py`).
3. Added memory state/review/export RBAC integration suite (`tests/integration/test_memory_api_state_surfaces.py`).
4. Updated targeted test docs in `docs/testing.md`.
5. Validation run: targeted tests + `make docs-check` passed.

### Packet 1 (next): M1 closure + channel ingress baseline
1. Finish BK-001, BK-002.
2. Add/lock core tests for evidence, memory policy events, webhook auth.
3. Preserve end-to-end inbound validation path: WhatsApp webhook -> orchestrator -> memory store with auditable events.

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
   - Add CLI integration assertion that `jarvis ask --json` output remains warning-free under a mocked provider to prevent log-noise regression.

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
   - Wire CI merge-time environment defaults to explicit test-gate enforce mode while preserving local warn default.
   - Add a committed retrieval benchmark artifact/report output path (current benchmark evidence is test-level timing assertion only).

### Packet 3 (next): M3 productization and governance visibility
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
1. Add frontend component-level tests for `/admin/memory` review/resolve and filtered consistency workflows.
2. Add explicit log-capture assertions for QR/pairing leakage prevention beyond payload redaction unit tests.
3. (Resolved 2026-02-18) Prior repo-wide lint/typecheck blockers cleared and full `make test-gates` evidence attached in Packet 1E.

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
