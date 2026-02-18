# Jarvis Master Execution Plan

**Date:** 2026-02-18
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
| Foundation + Observability | 2 | 4 | 0 |
| Self-Coding + Release Loop | 3 | 3 | 0 |
| Governance + Safety | 1 | 4 | 1 |
| Memory Intelligence + Retrieval | 1 | 7 | 2 |
| WhatsApp Channel + Admin UX | 0 | 1 | 6 |
| Documentation + Ops Hardening | 0 | 1 | 3 |

Status normalization:
- Source `implemented`/`done` => `done`
- Source `partial`/`in_progress`/`blocked` => `partial`
- Source unchecked TODO / planned-only without evidence => `not_started`
- Duplicate conflict rule applied conservatively (`partial` over `done`; `not_started` only used over `partial` when no evidence exists).

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
| BK-004 | Foundation + Observability | Memory denial/redaction event emission contract completion | partial | P1 | api_guardian | `uv run pytest tests/unit -k memory_policy -v` |
| BK-005 | Self-Coding + Release Loop | Self-update artifact schema versioning | done | P0 | coder | `uv run pytest tests/integration -k selfupdate -v` |
| BK-006 | Self-Coding + Release Loop | Deterministic reconciliation edge-case lock tests + run summary events | partial | P0 | tester | `uv run pytest tests/unit -k reconcile -v` |
| BK-007 | Self-Coding + Release Loop | Test-first gate (failing-test proof + coverage floor + critical-path test requirement) | partial | P0 | tester | `make test-gates`; `uv run pytest tests/integration -k selfupdate -v` |
| BK-008 | Self-Coding + Release Loop | PR base-branch enforcement test (`dev` only) | done | P1 | release_ops | `uv run pytest tests/integration -k github_pr_summary -v` |
| BK-009 | Self-Coding + Release Loop | Failure remediation scoring uses acceptance/rejection outcomes | done | P1 | researcher | `uv run pytest tests/unit -k failure_capsule -v` |
| BK-010 | Governance + Safety | Block self-permission escalation edits on agent identity governance fields | partial | P0 | security_reviewer | `uv run pytest tests/integration -k governance -v` |
| BK-011 | Governance + Safety | Self-update deployment gate state machine + typed failure taxonomy | partial | P0 | release_ops | `uv run pytest tests/integration -k selfupdate_apply -v` |
| BK-012 | Governance + Safety | Memory governance hardening (schema write gates + deny/redaction governance filters) | partial | P0 | security_reviewer | `uv run pytest tests/integration -k memory_governance -v` |
| BK-013 | Governance + Safety | Explicit per-agent memory read/write scope checks across APIs/tasks | partial | P0 | security_reviewer | RBAC integration regressions for memory routes/tasks |
| BK-014 | Governance + Safety | WhatsApp risky/unknown sender review queue with in-chat approve/deny commands | not_started | P1 | main | webhook + review-flow integration tests |
| BK-015 | Memory Intelligence + Retrieval | Multi-tier memory lifecycle and archival flow with score-driven migration | done | P1 | planner | `uv run pytest tests/unit -k state_store -v` |
| BK-016 | Memory Intelligence + Retrieval | Retrieval fusion completion (RRF for vector + FTS5 + filters + tier priors) | partial | P0 | planner | retrieval correctness + latency benchmark and tests |
| BK-017 | Memory Intelligence + Retrieval | Failure bridge typed mapping + stable dedupe key (`trace_id+phase+summary_hash`) | partial | P1 | planner | unit tests for mapping/dedupe/linkage |
| BK-018 | Memory Intelligence + Retrieval | Graph relation extraction confidence/evidence policy completion | partial | P1 | researcher | traversal + relation-extraction tests |
| BK-019 | Memory Intelligence + Retrieval | Adaptive forgetting/archival calibration harness and threshold tuning | partial | P1 | memory_curator | maintenance/task tests + workload simulation |
| BK-020 | Memory Intelligence + Retrieval | Consistency evaluator endpoint/UI surface and historical queryability | partial | P1 | planner | API + admin UI tests for reports/filters |
| BK-021 | Memory Intelligence + Retrieval | Full memory endpoint/CLI/RBAC test suite for new state/review/export surfaces | not_started | P0 | tester | endpoint + CLI + ownership regression tests |
| BK-022 | WhatsApp Channel + Admin UX | Evolution sidecar bootstrap (persistent auth, API key auth, webhook callback) | partial | P0 | api_guardian | container boots; instance QR available; webhook 200 |
| BK-023 | WhatsApp Channel + Admin UX | WhatsApp channel implementation: text/media/reaction/groups/thread mapping | not_started | P0 | api_guardian | integration tests for text/media/reaction/group payloads |
| BK-024 | WhatsApp Channel + Admin UX | Voice-note pipeline (download, transcribe, memory linkage) | not_started | P0 | api_guardian | voice message integration tests with transcript assertions |
| BK-025 | WhatsApp Channel + Admin UX | Admin pairing APIs (`status/create/qrcode/pairing-code/disconnect`) + auth/rate limits | not_started | P0 | api_guardian | admin API integration tests |
| BK-026 | WhatsApp Channel + Admin UX | Admin pairing UI (QR, status polling, connect/disconnect flows) | not_started | P1 | web_builder | UI functional checks + endpoint contract tests |
| BK-027 | WhatsApp Channel + Admin UX | Webhook auth and payload normalization (`messages.upsert` variants) | not_started | P0 | api_guardian | webhook secret enforcement + variant payload tests |
| BK-028 | WhatsApp Channel + Admin UX | WhatsApp security controls (no QR/code leakage, file limits, safe media paths) | not_started | P0 | security_reviewer | log-redaction checks + negative security tests |
| BK-029 | Documentation + Ops Hardening | Memory Prometheus KPI wiring and docs (`items_count`, `avg_tokens_saved`, `reconciliation_rate`, `hallucination_incidents`) | partial | P1 | release_ops | metric visibility under test flow |
| BK-030 | Documentation + Ops Hardening | Add rollback/runbook and config docs for new memory tables/tasks/flags | not_started | P1 | release_ops | updates in `docs/runbook.md` and `docs/configuration.md` |
| BK-031 | Documentation + Ops Hardening | WhatsApp operator docs and troubleshooting coverage | not_started | P1 | release_ops | `docs/channels/whatsapp.md` + UI/troubleshooting docs updated |
| BK-032 | Documentation + Ops Hardening | API/schema docs for memory routes and conflict-resolution operator flow | not_started | P2 | planner | docs-check and payload schema review |
| BK-033 | Foundation + Observability | Evolution/governance event contract additions (`evolution.item.*`) | partial | P2 | api_guardian | event schema tests + payload minimum key validation |
| BK-034 | Governance + Safety | Dependency steward hardening (CVE severity, compatibility bundle, rollback-ready PR context) | partial | P1 | dependency_steward | `uv run pytest tests/unit -k dependency_steward -v` |
| BK-035 | Governance + Safety | Release-candidate hardening (changelog artifact + runbook evidence) | partial | P1 | release_candidate | `uv run pytest tests/unit -k release_candidate -v` |
| BK-036 | Memory Intelligence + Retrieval | Memory admin UI completion (conflicts, tier/archive stats, failure lookup, graph preview) | partial | P1 | web_builder | admin memory page sections visible and populated |

## Execution Packets

### Packet 1 (next): M1 closure + channel ingress baseline
1. Finish BK-001, BK-002, BK-004, BK-022, BK-027.
2. Add/lock core tests for evidence, memory policy events, webhook auth.
3. Validate end-to-end inbound path: WhatsApp webhook -> orchestrator -> memory store with auditable events.

### Packet 2 (next): M2 memory reliability + self-update enforcement
1. Finish BK-006, BK-007, BK-016, BK-017, BK-021.
2. Run warn-mode then enforce-mode transition for strict gates.
3. Validate deterministic ordering, reconciliation summaries, and failure-bridge linkage correctness.

### Packet 3 (next): M3 productization and governance visibility
1. Finish BK-010, BK-011, BK-012, BK-013, BK-025, BK-026, BK-036.
2. Complete admin UX for pairing and memory governance visibility.
3. Run governance/RBAC regression suite before merge.

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

## Appendix

### Merged from
- `evo.md`
- `whatsapp.md`
- `docs/memory-roadmap.md`
- `docs/memory-roadmap-todo.md`
- `docs/evolution-whatsapp-memory-execution-plan.md`

### Deferred/Excluded items
- No source items were discarded. Items were merged/deduplicated into normalized backlog IDs.
- Optional API additions (`GET/POST /api/v1/governance/evolution/items*`) from `evo.md` were retained as lower-priority backlog coverage under BK-033 unless promoted by milestone pressure.
