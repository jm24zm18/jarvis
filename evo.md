# Jarvis Autonomous Evolution Master Plan (Execution Backlog)

**As of:** February 18, 2026  
**Target:** Transform `jm24zm18/jarvis` into a self-building, self-testing, self-governing, recursively improving agent system.  
**Operating model:** Deterministic Core + Agentic Edge + Verifiable Change Loop

## Document Contract

Each roadmap item is tracked as an `EvolutionWorkItem` with this schema:

| Field | Meaning |
|---|---|
| `id` | Stable work item id (example: `1.3`) |
| `title` | Work item name |
| `status` | `implemented`, `partial`, `missing`, `blocked`, `in_progress`, `done` |
| `owner_role` | Primary accountable role/agent |
| `priority` | `P0`, `P1`, `P2` |
| `depends_on` | Item ids that must land first |
| `risk_tier` | `low`, `medium`, `high` |
| `target_milestone` | `M1`..`M4` |
| `paths` | Code/docs paths to touch |
| `invariants` | Invariants that must be preserved |
| `acceptance_tests` | Required verification commands/tests |
| `rollback_plan` | Deterministic reversal path |
| `evidence_refs` | Existing repo evidence (path + line) |

## Status Transition Rules

- Allowed transitions: `missing -> in_progress -> done`, `partial -> in_progress -> done`, `* -> blocked`, `blocked -> in_progress`.
- `done` requires all acceptance tests passing and evidence links updated.
- `blocked` requires an explicit blocker reason and owner.

## Non-Negotiable Invariants

1. Deny-by-default tool access.
2. Append-only migrations.
3. Traceable event schema.
4. Test validation required.
5. Policy engine authority.
6. Memory writes require evidence refs.
7. No direct `master` commits.
8. Rollback remains available.

---

## Current Baseline Matrix

| ID | Item | Status | Evidence |
|---|---|---|---|
| 1.1 | Ground truth index | partial | `src/jarvis/repo_index/builder.py:13`, `src/jarvis/repo_index/builder.py:142` |
| 1.2 | Agent action envelope | implemented | `src/jarvis/events/envelope.py:7`, `src/jarvis/tools/runtime.py:58` |
| 1.3 | Evidence requirement rule | partial | `src/jarvis/selfupdate/contracts.py:15`, `src/jarvis/selfupdate/contracts.py:62` |
| 1.4 | Observability console | partial | `web/src/pages/admin/events/index.tsx:15`, `web/src/pages/admin/governance/index.tsx:22`, `web/src/pages/admin/selfupdate/index.tsx:53` |
| 1.5 | Memory foundation interfaces | implemented | `src/jarvis/memory/interfaces.py:9`, `src/jarvis/memory/factory.py:13` |
| 1.6 | Memory event logging | partial | `src/jarvis/memory/service.py:127`, `src/jarvis/memory/service.py:337`, `src/jarvis/memory/state_store.py:204` |
| 2.1 | Patch-as-artifact pipeline | implemented | `src/jarvis/selfupdate/contracts.py:181`, `src/jarvis/selfupdate/pipeline.py:65`, `src/jarvis/tasks/selfupdate.py:1260` |
| 2.2 | Structured state memory | implemented | `src/jarvis/memory/state_store.py:134`, `src/jarvis/db/migrations/043_state_items_tiers_importance.sql:1` |
| 2.3 | Deterministic reconciliation | partial | `src/jarvis/memory/state_store.py:220`, `src/jarvis/memory/state_store.py:277` |
| 2.4 | Test-first enforcement | partial | `src/jarvis/tasks/selfupdate.py:1196`, `src/jarvis/tasks/selfupdate.py:1243` |
| 2.5 | Autonomous PR authoring | implemented | `src/jarvis/tasks/selfupdate.py:642`, `docs/git-workflow.md:28`, `src/jarvis/tasks/github.py:494` |
| 2.6 | Failure capsule memory | implemented | `src/jarvis/tasks/selfupdate.py:262`, `src/jarvis/tasks/selfupdate.py:298`, `src/jarvis/tasks/selfupdate.py:893` |
| 3.1 | Permission governance as code | partial | `src/jarvis/db/migrations/027_agent_governance.sql:1`, `src/jarvis/agents/loader.py:119`, `src/jarvis/policy/engine.py:70` |
| 3.2 | Dependency steward agent | partial | `src/jarvis/tasks/dependency_steward.py:32`, `src/jarvis/routes/api/governance.py:218` |
| 3.3 | Release candidate agent | partial | `src/jarvis/tasks/release_candidate.py:11`, `src/jarvis/routes/api/governance.py:226` |
| 3.4 | Self-update deployment gate | partial | `src/jarvis/tasks/selfupdate.py:1288`, `src/jarvis/tasks/selfupdate.py:1371`, `src/jarvis/tasks/selfupdate.py:1634` |
| 3.5 | Memory governance | partial | `src/jarvis/memory/policy.py:44`, `src/jarvis/tasks/memory.py:58`, `src/jarvis/routes/api/governance.py:132` |
| 4.1 | Multi-agent specialization | implemented | `agents/TEAM.md:1`, `agents/dependency_steward/identity.md:1`, `agents/release_candidate/identity.md:1` |
| 4.2 | Learning loop engine | partial | `src/jarvis/tasks/maintenance.py:296`, `web/src/pages/admin/governance/index.tsx:202` |
| 4.3 | System fitness metrics | partial | `src/jarvis/tasks/maintenance.py:246`, `src/jarvis/routes/api/governance.py:159` |
| 4.4 | Recursive guardrails | implemented | `src/jarvis/db/migrations/036_recursive_guardrails.sql:1`, `src/jarvis/tasks/selfupdate.py:335` |
| 4.5 | Adaptive memory optimization | partial | `src/jarvis/tasks/memory.py:58`, `src/jarvis/tasks/memory.py:312` |

---

## Phase 1 - Foundation and Observability (M1)

### 1.1 Ground Truth Index
- `status`: partial
- `owner_role`: planner
- `priority`: P0
- `depends_on`: none
- `risk_tier`: medium
- `paths`: `src/jarvis/repo_index/*`, `docs/codebase-tour.md`
- `invariants`: 1, 2, 3, 5
- Gap: dependency graph and protected-module drift checks are not emitted.
- Implementation tasks:
1. Extend repo index schema with dependency edges and critical-module ownership metadata.
2. Add index freshness check in CI to fail stale `.jarvis/repo_index.json`.
3. Document generation and consumption contract in `docs/architecture.md`.
- Acceptance tests: `make lint`, `make typecheck`, `uv run pytest tests/unit -k repo_index -v`.
- Rollback plan: revert schema extension and keep current index fields only.

### 1.2 Agent Action Envelope
- `status`: implemented
- `owner_role`: api_guardian
- `priority`: P1
- `depends_on`: 1.1
- `risk_tier`: low
- `paths`: `src/jarvis/events/envelope.py`, `src/jarvis/tools/runtime.py`, `src/jarvis/orchestrator/step.py`
- `invariants`: 3, 5
- Gap: enforce envelope completeness in tests across all emitting components.
- Implementation tasks:
1. Add unit tests ensuring required envelope keys for all `tool.call.*`, `policy.*`, and `agent.step.*` events.
2. Add runtime assertion helper used by emit points.
- Acceptance tests: `uv run pytest tests/unit -k envelope -v`.
- Rollback plan: keep envelope enrichment but drop strict assertions if false positives block runtime.

### 1.3 Evidence Requirement Rule
- `status`: partial
- `owner_role`: security_reviewer
- `priority`: P0
- `depends_on`: 1.1
- `risk_tier`: high
- `paths`: `src/jarvis/selfupdate/contracts.py`, `src/jarvis/orchestrator/step.py`, `docs/change-safety.md`
- `invariants`: 1, 4, 5, 6
- Gap: evidence contract is enforced for self-update, not uniformly for all autonomous code modifications.
- Implementation tasks:
1. Add shared evidence validator service reused by self-update and direct coding workflows.
2. Require `file_refs`, `line_refs`, `policy_refs`, and `invariant_checks` before mutation-capable steps.
3. Emit a standard `evidence.check` denial event on failure.
- Acceptance tests: `uv run pytest tests/unit -k evidence -v`, `uv run pytest tests/integration -k selfupdate -v`.
- Rollback plan: scope strict enforcement to self-update path behind feature flag.

### 1.4 Observability Console
- `status`: partial
- `owner_role`: web_builder
- `priority`: P1
- `depends_on`: 1.2, 1.3
- `risk_tier`: medium
- `paths`: `web/src/pages/admin/events/*`, `web/src/pages/admin/governance/*`, `web/src/pages/admin/selfupdate/*`, `src/jarvis/routes/api/governance.py`
- `invariants`: 3, 5
- Gap: panels exist but are distributed; no single trace-to-patch lifecycle flow and no explicit memory access audit panel.
- Implementation tasks:
1. Add unified "Evolution" admin page linking trace explorer, timeline, memory audit, policy decisions, patch lifecycle.
2. Add route-level aggregation endpoint for cross-panel drill-down by `trace_id`.
- Acceptance tests: `make web-dev` manual verification + `uv run pytest tests/integration -k governance -v`.
- Rollback plan: keep existing pages and hide unified page behind feature toggle.

### 1.5 Memory Foundation Layer
- `status`: implemented
- `owner_role`: planner
- `priority`: P1
- `depends_on`: none
- `risk_tier`: low
- `paths`: `src/jarvis/memory/interfaces.py`, `src/jarvis/memory/factory.py`
- `invariants`: 5, 6
- Gap: add explicit backend capability matrix in docs.
- Implementation tasks:
1. Document interface compatibility and fallback behavior.
- Acceptance tests: `uv run pytest tests/unit -k memory_factory -v`.
- Rollback plan: doc-only; no runtime rollback needed.

### 1.6 Memory Event Logging
- `status`: partial
- `owner_role`: api_guardian
- `priority`: P1
- `depends_on`: 1.2
- `risk_tier`: medium
- `paths`: `src/jarvis/memory/service.py`, `src/jarvis/memory/state_store.py`, `src/jarvis/memory/policy.py`
- `invariants`: 3, 6
- Gap: `retrieve/write/compact/reconcile` events exist; explicit `redaction` and `denial` event types are missing.
- Implementation tasks:
1. Emit `memory.policy.redaction` and `memory.policy.denial` from memory policy decisions.
2. Add event payload contract docs for memory events.
- Acceptance tests: `uv run pytest tests/unit -k memory_policy -v`.
- Rollback plan: fallback to current audit table-only behavior.

### Phase 1 Exit Criteria
- Zero roadmap items in `missing` for Phase 1.
- All Phase 1 acceptance tests pass.
- Unified observability flow works from trace to patch and memory audit.

---

## Phase 2 - Self-Coding Loop (M2)

### 2.1 Patch-as-Artifact Pipeline
- `status`: implemented
- `owner_role`: coder
- `priority`: P0
- `depends_on`: 1.3
- `risk_tier`: medium
- `paths`: `src/jarvis/selfupdate/contracts.py`, `src/jarvis/selfupdate/pipeline.py`, `src/jarvis/tasks/selfupdate.py`
- `invariants`: 2, 4, 5, 8
- Gap: artifact schema versioning is not explicit.
- Implementation tasks:
1. Add `artifact_schema_version` and migration notes for backward compatibility.
- Acceptance tests: `uv run pytest tests/integration -k selfupdate -v`.
- Rollback plan: support reading versionless artifact as v1.

### 2.2 Structured State Memory Implementation
- `status`: implemented
- `owner_role`: planner
- `priority`: P1
- `depends_on`: 1.5
- `risk_tier`: medium
- `paths`: `src/jarvis/memory/state_store.py`, `src/jarvis/db/migrations/043_state_items_tiers_importance.sql`
- `invariants`: 2, 6
- Gap: formal schema contract doc is missing.
- Implementation tasks:
1. Publish field-level schema in `docs/architecture.md` with lifecycle semantics.
- Acceptance tests: `uv run pytest tests/unit -k state_store -v`.
- Rollback plan: no behavior change; doc-only.

### 2.3 Deterministic Reconciliation Engine
- `status`: partial
- `owner_role`: tester
- `priority`: P0
- `depends_on`: 2.2
- `risk_tier`: medium
- `paths`: `src/jarvis/memory/state_store.py`, `src/jarvis/memory/state_items.py`
- `invariants`: 3, 6
- Gap: conflict/supersede/stale transitions are present but not fully test-locked for all edge cases.
- Implementation tasks:
1. Add deterministic tests for contradiction, supersession evidence merge, and stale demotion ordering.
2. Add reconciliation run summary event per batch.
- Acceptance tests: `uv run pytest tests/unit -k reconcile -v`.
- Rollback plan: keep current merge logic and disable new strict conflict promotion rules.

### 2.4 Test-First Enforcement
- `status`: partial
- `owner_role`: tester
- `priority`: P0
- `depends_on`: 1.3
- `risk_tier`: high
- `paths`: `src/jarvis/tasks/selfupdate.py`, `src/jarvis/selfupdate/contracts.py`, `docs/testing.md`
- `invariants`: 4, 5
- Gap: smoke/test-plan validation exists, but mandatory failing-test-first and coverage-preservation checks are not enforced.
- Implementation tasks:
1. Require evidence packet to include failing test proof for critical changes.
2. Add coverage floor check per touched module.
3. Reject patch when no new or updated tests are present for critical-path changes.
- Acceptance tests: `make test-gates`, `uv run pytest tests/integration -k selfupdate -v`.
- Rollback plan: run checks in warn mode first, then enforce mode.

### 2.5 Autonomous PR Authoring
- `status`: implemented
- `owner_role`: release_ops
- `priority`: P1
- `depends_on`: 2.1
- `risk_tier`: medium
- `paths`: `src/jarvis/tasks/selfupdate.py`, `docs/git-workflow.md`, `src/jarvis/tasks/github.py`
- `invariants`: 5, 7
- Gap: add explicit test that PR creation fails for non-`dev` base.
- Implementation tasks:
1. Add integration test for branch base enforcement.
- Acceptance tests: `uv run pytest tests/integration -k github_pr_summary -v`.
- Rollback plan: keep current base restriction logic.

### 2.6 Failure Capsule Memory
- `status`: implemented
- `owner_role`: researcher
- `priority`: P1
- `depends_on`: 2.1
- `risk_tier`: low
- `paths`: `src/jarvis/tasks/selfupdate.py`, `src/jarvis/tasks/memory.py`, `src/jarvis/memory/service.py`
- `invariants`: 3, 6
- Gap: add richer remediation quality scoring loop.
- Implementation tasks:
1. Weight remediation ranking by accepted/rejected feedback outcomes.
- Acceptance tests: `uv run pytest tests/unit -k failure_capsule -v`.
- Rollback plan: fallback to recency-based remediation ranking.

### Phase 2 Exit Criteria
- All self-update patches have versioned artifacts.
- Critical changes are blocked without test-first evidence and coverage checks.
- Reconciliation edge-case tests are deterministic and green.

---

## Phase 3 - Autonomous Governance (M3)

### 3.1 Permission Governance as Code
- `status`: partial
- `owner_role`: security_reviewer
- `priority`: P0
- `depends_on`: 1.3
- `risk_tier`: high
- `paths`: `src/jarvis/agents/loader.py`, `src/jarvis/policy/engine.py`, `src/jarvis/db/migrations/027_agent_governance.sql`
- `invariants`: 1, 5, 7
- Gap: self-modification protections for agent permission files are policy-driven but not explicitly immutable by source agent identity.
- Implementation tasks:
1. Add guard that blocks an agent from proposing changes to its own `identity.md` governance fields.
2. Add audit event with denial reason for self-permission mutation attempts.
- Acceptance tests: `uv run pytest tests/integration -k governance -v`.
- Rollback plan: keep current governance constraints and disable self-identity block behind flag if needed.

### 3.2 Dependency Steward Agent
- `status`: partial
- `owner_role`: dependency_steward
- `priority`: P1
- `depends_on`: 2.4
- `risk_tier`: medium
- `paths`: `src/jarvis/tasks/dependency_steward.py`, `src/jarvis/routes/api/governance.py`
- `invariants`: 4, 5, 8
- Gap: currently proposes upgrades; lacks vulnerability scan integration, compatibility matrix, and rollback-ready PR automation.
- Implementation tasks:
1. Integrate vulnerability advisory feed and annotate proposals with CVE severity.
2. Add compatibility test bundle execution per proposal.
3. Add optional draft PR generation with rollback notes.
- Acceptance tests: `uv run pytest tests/unit -k dependency_steward -v`.
- Rollback plan: keep read-only proposal mode if scanners fail.

### 3.3 Release Candidate Agent
- `status`: partial
- `owner_role`: release_candidate
- `priority`: P1
- `depends_on`: 2.4, 3.2
- `risk_tier`: medium
- `paths`: `src/jarvis/tasks/release_candidate.py`, `docs/build-release.md`
- `invariants`: 4, 5, 8
- Gap: readiness checks exist but changelog generation and runbook compliance attestations are incomplete.
- Implementation tasks:
1. Generate changelog artifact from merged commits since last tag.
2. Add runbook checklist evidence to release candidate payload.
- Acceptance tests: `uv run pytest tests/unit -k release_candidate -v`.
- Rollback plan: continue using existing blocker-only release summary.

### 3.4 Self-Update Deployment Gate
- `status`: partial
- `owner_role`: release_ops
- `priority`: P0
- `depends_on`: 2.1, 2.4, 3.1
- `risk_tier`: high
- `paths`: `src/jarvis/tasks/selfupdate.py`, `src/jarvis/routes/api/selfupdate.py`
- `invariants`: 4, 5, 8
- Gap: validate/test/approve/apply/verify/monitor exists; add explicit gate-state machine contract and failure taxonomies.
- Implementation tasks:
1. Publish gate state machine and terminal conditions.
2. Enforce typed failure reasons for each gate and export in patch timeline API.
- Acceptance tests: `uv run pytest tests/integration -k selfupdate_apply -v`.
- Rollback plan: continue current transition model while emitting compatibility fields.

### 3.5 Memory Governance
- `status`: partial
- `owner_role`: security_reviewer
- `priority`: P0
- `depends_on`: 1.6, 2.2
- `risk_tier`: high
- `paths`: `src/jarvis/memory/policy.py`, `src/jarvis/tasks/memory.py`, `src/jarvis/routes/api/governance.py`
- `invariants`: 3, 5, 6
- Gap: PII masking, secret scanning, retention, and audit exist; schema-change gate and explicit per-agent memory access policy checks are incomplete.
- Implementation tasks:
1. Add schema-version gate for memory tables to block unsafe runtime writes during migrations.
2. Enforce explicit per-agent read/write scope checks for memory and state retrieval APIs.
3. Add governance page filter for deny/redaction events by actor.
- Acceptance tests: `uv run pytest tests/integration -k memory_governance -v`.
- Rollback plan: keep current policy behavior with audit-only escalation.

### Phase 3 Exit Criteria
- Governance denies self-permission escalation attempts.
- Dependency and release agents emit auditable evidence artifacts.
- Deployment gate and memory governance expose typed, queryable outcomes.

---

## Phase 4 - Scaling and Recursive Optimization (M4)

### 4.1 Multi-Agent Specialization
- `status`: implemented
- `owner_role`: main
- `priority`: P1
- `depends_on`: 3.1
- `risk_tier`: medium
- `paths`: `agents/*`, `agents/TEAM.md`
- `invariants`: 1, 5, 7
- Gap: align naming with roadmap role taxonomy and map each role to KPI ownership.
- Implementation tasks:
1. Add role-to-KPI ownership table in `agents/TEAM.md`.
- Acceptance tests: `uv run pytest tests/unit -k agents_loader -v`.
- Rollback plan: documentation-only.

### 4.2 Learning Loop Engine
- `status`: partial
- `owner_role`: researcher
- `priority`: P1
- `depends_on`: 2.6
- `risk_tier`: medium
- `paths`: `src/jarvis/tasks/maintenance.py`, `src/jarvis/routes/api/governance.py`, `web/src/pages/admin/governance/index.tsx`
- `invariants`: 3, 4
- Gap: pattern extraction exists; automated planner feedback injection is limited.
- Implementation tasks:
1. Feed high-confidence remediations into planning prompts as structured constraints.
2. Track remediation success deltas after adoption.
- Acceptance tests: `uv run pytest tests/integration -k learning_loop -v`.
- Rollback plan: keep display-only learning loop without prompt injection.

### 4.3 System Fitness Metrics
- `status`: partial
- `owner_role`: release_ops
- `priority`: P1
- `depends_on`: 3.4, 4.2
- `risk_tier`: medium
- `paths`: `src/jarvis/tasks/maintenance.py`, `src/jarvis/routes/api/governance.py`, `web/src/pages/admin/governance/index.tsx`
- `invariants`: 3, 4, 8
- Gap: current metrics miss explicit coverage stability and hallucination incident rates.
- Implementation tasks:
1. Add coverage stability metric from test reports.
2. Add hallucination incident counter from evidence-check and policy-denial diagnostics.
3. Add weekly snapshot rollup endpoint.
- Acceptance tests: `uv run pytest tests/unit -k fitness -v`.
- Rollback plan: continue existing snapshot metrics set.

### 4.4 Recursive Optimization Guardrails
- `status`: implemented
- `owner_role`: security_reviewer
- `priority`: P0
- `depends_on`: 3.4
- `risk_tier`: high
- `paths`: `src/jarvis/db/migrations/036_recursive_guardrails.sql`, `src/jarvis/tasks/selfupdate.py`
- `invariants`: 1, 5, 8
- Gap: add explicit human alert routing for all guardrail trips.
- Implementation tasks:
1. Emit pager/webhook notifications on guardrail-triggered lockdown events.
- Acceptance tests: `uv run pytest tests/integration -k guardrail -v`.
- Rollback plan: keep lockdown-only response path.

### 4.5 Adaptive Memory Optimization
- `status`: partial
- `owner_role`: memory_curator (implemented by planner + researcher until role is formalized)
- `priority`: P1
- `depends_on`: 3.5, 4.2
- `risk_tier`: medium
- `paths`: `src/jarvis/tasks/memory.py`, `src/jarvis/memory/state_store.py`
- `invariants`: 3, 6
- Gap: pruning, dedupe, supersession, and tiering exist; promotion heuristics need closed-loop validation against retrieval quality.
- Implementation tasks:
1. Add retrieval quality KPI before and after maintenance cycles.
2. Auto-tune importance thresholds based on observed recall/precision.
- Acceptance tests: `uv run pytest tests/unit -k memory_maintenance -v`.
- Rollback plan: pin fixed thresholds and disable auto-tune.

### Phase 4 Exit Criteria
- Learning loop influences planning with measurable lift.
- Fitness metrics include coverage stability and hallucination incidents.
- Memory optimization is quality-scored, not only size-scored.

---

## Crosswalk: Items to Invariants

| Item | Primary invariants |
|---|---|
| 1.1 | 1, 2, 3, 5 |
| 1.2 | 3, 5 |
| 1.3 | 1, 4, 5, 6 |
| 1.4 | 3, 5 |
| 1.5 | 5, 6 |
| 1.6 | 3, 6 |
| 2.1 | 2, 4, 5, 8 |
| 2.2 | 2, 6 |
| 2.3 | 3, 6 |
| 2.4 | 4, 5 |
| 2.5 | 5, 7 |
| 2.6 | 3, 6 |
| 3.1 | 1, 5, 7 |
| 3.2 | 4, 5, 8 |
| 3.3 | 4, 5, 8 |
| 3.4 | 4, 5, 8 |
| 3.5 | 3, 5, 6 |
| 4.1 | 1, 5, 7 |
| 4.2 | 3, 4 |
| 4.3 | 3, 4, 8 |
| 4.4 | 1, 5, 8 |
| 4.5 | 3, 6 |

---

## Rollout Packets

### Packet A (M1)
1. Land Phase 1 partial-item closures in separate PRs by item.
2. Run `make lint`, `make typecheck`, targeted tests per item, then `make test-gates`.
3. Verify admin observability path end-to-end in web UI.

### Packet B (M2)
1. Enforce evidence and test-first checks in warn mode for one cycle.
2. Move to enforce mode after zero critical false positives.
3. Verify self-update pipeline with dry-run traces before enabling full automation.

### Packet C (M3)
1. Turn on governance self-mutation blocks.
2. Expand dependency/release evidence artifacts.
3. Verify approval and rollback pathways in staging.

### Packet D (M4)
1. Enable learning-loop prompt feedback for one role first.
2. Observe fitness trend changes for two weekly snapshots.
3. Enable adaptive threshold tuning after baseline stability.

---

## Test and Acceptance Gate (Global)

Required before marking any item `done`:

1. `make lint`
2. `make typecheck`
3. Item-scoped unit and integration tests
4. `make test-gates` before merge
5. Evidence refs updated in this file

---

## Public Interface Additions Planned

These are planned contracts and are not yet fully implemented:

1. Event types:
- `evolution.item.started`
- `evolution.item.verified`
- `evolution.item.blocked`

2. Event payload minimum keys:
- `item_id`
- `trace_id`
- `status`
- `evidence_refs`
- `result`

3. Optional admin API (future):
- `GET /api/v1/governance/evolution/items`
- `POST /api/v1/governance/evolution/items/{id}/status`

---

## Assumptions and Defaults

1. Existing implemented capabilities are tracked as completed baseline, not re-implemented.
2. Work branches target `dev`; promotion to `master` requires human approval.
3. Migrations remain append-only.
4. Any new strict gate should ship in warn mode first, then enforce mode.
