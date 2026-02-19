# Memory Roadmap TODO

Status snapshot of remaining work after the current implementation pass.

## Not Implemented Yet

- [ ] Extend the admin memory UI with dedicated sections for:
  - conflicts review queue
  - tier distribution and archive stats
  - failure lookup
  - graph traversal preview
- [ ] Add explicit Prometheus metric wiring for:
  - `items_count`
  - `avg_tokens_saved`
  - `reconciliation_rate`
  - `hallucination_incidents`
- [ ] Add explicit event emission coverage for all planned memory lifecycle events (including graph/review/archive specifics) and validate naming consistency across components.
- [ ] Add a consistency evaluator endpoint/UI surface (task exists, but no admin route/view exposing reports yet).

## Partially Implemented / Needs Hardening

- [ ] Structured retrieval fusion for state memory is not fully implemented as planned:
  - current `search_state` is vector-first and decision-biased
  - needs true RRF fusion of vector + FTS5 + structured filters + tier priors
- [ ] Namespace/ACL model is only partially enforced:
  - `agent_id` is present on state records
  - full `agent + user + thread` enforcement needs additional join-time checks and policy tests across all new endpoints/tasks
- [ ] Failure bridge is implemented, but needs stronger mapping semantics:
  - richer conversion from `failure_capsules.error_details_json` to typed failure fields
  - dedupe strategy and trace/thread linkage validation
- [ ] Graph relation extraction is only minimally covered:
  - traversal API exists
  - relation extraction during reconciliation (beyond basic inserts) needs completion
  - confidence/evidence quality policy is still basic
- [ ] Adaptive forgetting/archival policy needs tuning and validation against production-like workloads:
  - thresholds currently fixed
  - no policy calibration harness yet

## Tests Still Needed

- [ ] End-to-end tests for new memory API endpoints:
  - `/memory/state/search`
  - `/memory/state/failures`
  - `/memory/state/graph/{uid}`
  - `/memory/state/review/conflicts`
  - `/memory/state/review/{uid}/resolve`
  - `/memory/export`
- [ ] CLI tests for:
  - `jarvis memory review --conflicts`
  - `jarvis memory export --format=jsonl --tier=...`
- [ ] RBAC/ownership regression tests for non-admin access on new memory routes.
- [ ] Task-level tests for:
  - `migrate_tiers`
  - `prune_adaptive`
  - `sync_failure_capsules`
  - `evaluate_consistency`
- [ ] Embedding cache tests for hit/miss/update semantics and fallback behavior under backend failure.

## Operational / Migration Follow-ups

- [ ] Validate migration execution on a fresh DB and on representative existing DBs with pre-existing local migration files in this branch.
- [ ] Add explicit rollback/runbook notes for new memory tables and scheduled tasks in `docs/runbook.md`.
- [ ] Document new env flags in `docs/configuration.md`.

## Optional but Recommended

- [ ] Add REST/JSON schema docs for new memory route payloads and responses.
- [x] Add benchmark script for retrieval quality and latency before/after RRF fusion (`scripts/retrieval_benchmark_report.py`, artifact path `docs/reports/retrieval/latest.json`).
- [ ] Add conflict-resolution UX flow documentation for operators.
