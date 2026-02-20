# Beta Test Report - 2026-02-18

## 1) Executive Summary
- Overall stability score (1-10): 7/10
- Production readiness score (1-10): 6/10
- Biggest risk: Unbounded login input size allows very large `external_id` values to be stored (resource abuse risk).
- Biggest usability issue: CLI prints warning on ask flows: `No adapter registered for channel_type=cli`.

## 2) Bug Report Table

| Severity | Type | Component | Description | Repro Steps | Expected | Actual | Notes |
|---|---|---|---|---|---|---|---|
| High | reliability/testing | Integration test harness / auth provider config | Full integration suite has deterministic failure in provider config auth expectations. | `uv run pytest tests/integration -q`; `uv run pytest tests/integration/test_web_api.py::test_provider_config_get_and_update -q` | Suite green or failing test aligned with current RBAC policy. | Both runs fail: `403` on `GET /api/v1/auth/providers/config` while test expects `200`. | Assertion in `tests/integration/test_web_api.py:81`; route enforces admin in `src/jarvis/routes/api/auth.py:374`. |
| Medium | ux | CLI/channel dispatch | Every CLI ask prints noisy warning about missing CLI channel adapter. | `uv run jarvis ask "hello"`; `uv run jarvis ask "hello" --json` | Clean CLI response without internal warning for expected CLI usage. | Both runs print `No adapter registered for channel_type=cli` before normal answer. | Log emitted at `src/jarvis/tasks/channel.py:52`. |
| Medium | security/performance | Auth login input validation | `/api/v1/auth/login` accepts extremely large `external_id` payloads and creates users. | Login with external_id length 200k; repeat with 500k | Request rejected with size/format validation. | Both requests returned `200 OK`. | Accepted at `src/jarvis/routes/api/auth.py:235`; persisted by `src/jarvis/db/queries.py:211`. |
| Low | docs/ux | Setup smoke flow | `make setup-smoke` hard-fails if ports already occupied. | Run `make setup-smoke` twice | Clear guidance in setup docs or adaptive handling for already-running services. | Both runs failed on occupied ports `11434`, `30000`, `8080`. | Current behavior via `Makefile:81` and `scripts/dev_preflight_ports.py`. |

## 3) Detailed Findings

### A. Provider Config RBAC Test Mismatch
- category: bug/reliability
- severity: High
- confidence: High
- affected: `tests/integration/test_web_api.py:81`, `src/jarvis/routes/api/auth.py:372`
- reproduced twice: yes
- hypothesis: test expectation is stale; endpoint requires `admin`.
- recommendation: align test setup with admin auth or adjust endpoint policy/docs.
- workaround: skip or xfail this test until expectation is corrected.

### B. CLI Warning Noise on Normal Ask Flows
- category: ux
- severity: Medium
- confidence: High
- affected: `src/jarvis/tasks/channel.py:52`
- reproduced twice: yes
- hypothesis: dispatch path checks channel adapter for `cli` where none is registered.
- recommendation: suppress warning for expected non-adapter channels or add no-op `cli` adapter.
- workaround: ignore warning; command still returns answer.

### C. Oversized `external_id` Accepted
- category: security/performance
- severity: Medium
- confidence: High
- affected: `/api/v1/auth/login`, `src/jarvis/routes/api/auth.py:235`, `src/jarvis/db/queries.py:211`
- reproduced twice: yes (200k and 500k values)
- hypothesis: no input length/format validation before user upsert.
- recommendation: enforce max length + charset in request validation and DB constraints.
- workaround: do not allow untrusted clients to set custom `external_id`.

### D. Setup Smoke Port Preflight Friction
- category: docs/ux
- severity: Low
- confidence: High
- affected: `Makefile:81`, `docs/getting-started.md`
- reproduced twice: yes
- hypothesis: strict preflight assumes fresh host and blocks common dev setups.
- recommendation: document this precondition prominently and suggest resolution commands.
- workaround: free required ports before `make setup-smoke`.

## 4) Top 10 Fix Priority List
1. Fix or realign `test_provider_config_get_and_update` with admin RBAC.
2. Add validation limits for `external_id` in login payload.
3. Add DB-level constraint for `users.external_id` size.
4. Suppress expected `cli` channel warning noise.
5. Add regression tests for oversized login payload rejection.
6. Add regression tests for provider-config RBAC.
7. Clarify `setup-smoke` preconditions in docs.
8. Improve preflight output for already-running local services.
9. Reduce non-actionable warning verbosity in CLI mode.
10. Re-run full `make test-gates` after fixes.

## 5) Beta Tester Verdict
- Needs major fixes
