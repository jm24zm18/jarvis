1) Executive Summary
- Overall stability score (1–10): 4
- Production readiness score (1–10): 3
- Biggest risk: Core user path (`jarvis ask`) can hang under provider/network failure and time out without returning a structured response.
- Biggest usability issue: Fresh setup flow is brittle (`make dev` port conflicts, `make web-install` failure), causing early-user onboarding failure.

2) Bug Report Table

| Severity | Type | Component | Description | Repro Steps | Expected | Actual | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| High | reliability/ux | CLI ask path | `jarvis ask --json` hangs and times out (exit 124) when provider DNS/egress fails; prints large traceback during state extraction. | `timeout 45s .venv/bin/jarvis ask 'hello beta test' --json; echo ASK_EXIT=$?` (run twice) | Fast failure with concise, user-facing error JSON and non-timeout exit. | Both runs ended with `ASK_EXIT=124`, `Primary provider failed: ConnectError`, plus long traceback from state extraction timeout. | Reproduced twice. Affected call chain includes `src/jarvis/cli/main.py:74`, `src/jarvis/orchestrator/step.py:494`, `src/jarvis/memory/state_extractor.py:125`. |
| High | setup/ops | Docker dependency startup | `make dev` fails due host port collisions and does not preflight or provide actionable conflict detection. | `make dev` (run twice) | Either clean startup or explicit preflight identifying occupied ports before partial container recreation. | Two runs failed with bind errors on `11434` and `30000`. | Reproduced twice. See `Makefile:5`, `docker-compose.yml` host bindings. |
| High | reliability/testing | Integration test harness | Single integration test hangs beyond 60s and requires external timeout kill. | `WEB_AUTH_SETUP_PASSWORD=secret timeout 60s .venv/bin/pytest -q tests/integration/test_authorization.py::test_non_admin_cannot_toggle_lockdown; echo PYTEST_EXIT=$?` (run twice) | Test should complete quickly with pass/fail status. | Both runs returned `PYTEST_EXIT=124`. | Reproduced twice. Test at `tests/integration/test_authorization.py:142`. |
| Medium | setup/ux | Web setup/install | `make web-install` fails with npm internal error and cannot complete web prerequisites. | `timeout 120s make web-install` (run twice) | Dependencies install or clear actionable package/network error. | Both runs: `npm error Exit handler never called!` and `make` failed. | Reproduced twice. `Makefile:52`. |
| Medium | docs/ux | Onboarding docs | Quick-start/docs omit explicit `make web-install` before web commands, leading immediate module-not-found/typecheck failures for new users. | Follow `README.md` quick start + run `make web-build` or `make web-typecheck`. | Docs should include dependency install step before web scripts. | Web commands fail with missing modules/tooling (`react`, `eslint`, etc.) when deps not installed. | Evidence in `README.md:20-34`, `docs/getting-started.md:59-64`, `Makefile:52-65`. |

3) Detailed Findings

### Finding 1
- category: bug/reliability
- severity: High
- confidence: High
- affected files or endpoints: `src/jarvis/cli/main.py:74`, `src/jarvis/orchestrator/step.py:494`, `src/jarvis/memory/state_extractor.py:125`
- reproduction steps:
  1. Run `timeout 45s .venv/bin/jarvis ask 'hello beta test' --json; echo ASK_EXIT=$?`
  2. Observe `Primary provider failed: ConnectError: [Errno -3] Temporary failure in name resolution`.
  3. Observe traceback ending in `TimeoutError` from state extraction and final `ASK_EXIT=124`.
  4. Repeat once more; same timeout behavior.
- why it happens (hypothesis): Provider failure handling does not short-circuit downstream state extraction/orchestration work quickly; error path remains slow/noisy and CLI call does not return a compact failure payload before timeout.
- fix recommendation: Add explicit fail-fast behavior on provider transport errors, bounded fallback budget, and guaranteed terminal CLI response object for `ask --json`.
- quick workaround if any: Use shorter `--timeout-s` and validate provider connectivity before invoking `ask`.

### Finding 2
- category: bug/setup
- severity: High
- confidence: High
- affected files or endpoints: `Makefile:5`, Docker startup path from `docker-compose.yml`
- reproduction steps:
  1. Run `make dev`.
  2. Observe bind failure (`11434` in one run, `30000` in another).
  3. Repeat `make dev`; failure persists (port conflict changes by service).
- why it happens (hypothesis): Startup assumes required host ports are free; no preflight or alternate port strategy.
- fix recommendation: Add preflight port checks and fail early with explicit remediation (`lsof/ss` hints, optional alternate port profile).
- quick workaround if any: Stop conflicting host services/containers before `make dev`.

### Finding 3
- category: bug/reliability
- severity: High
- confidence: Medium
- affected files or endpoints: `tests/integration/test_authorization.py:142`
- reproduction steps:
  1. Run `WEB_AUTH_SETUP_PASSWORD=secret timeout 60s .venv/bin/pytest -q tests/integration/test_authorization.py::test_non_admin_cannot_toggle_lockdown; echo PYTEST_EXIT=$?`.
  2. Observe `PYTEST_EXIT=124`.
  3. Repeat command; same timeout.
- why it happens (hypothesis): Lifespan/background task teardown or shared resource lock causes request/test completion stall in integration context.
- fix recommendation: Instrument this test with per-step timing and isolate app lifecycle/background task shutdown behavior in test mode.
- quick workaround if any: Run unit/security policy tests for fast signal while integration hang is investigated.

### Finding 4
- category: bug/setup
- severity: Medium
- confidence: Medium
- affected files or endpoints: `Makefile:52`
- reproduction steps:
  1. Run `timeout 120s make web-install`.
  2. Observe `npm error Exit handler never called!` and command failure.
  3. Repeat once more; same failure signature.
- why it happens (hypothesis): npm install path is brittle under this runtime (likely environment/network/logging interaction) and currently lacks resilient handling or fallback guidance.
- fix recommendation: Add deterministic install guidance (lockfile strategy, npm cache/log fallback flags, retry hints) and preflight checks.
- quick workaround if any: Run npm install with verbose flags and validated network/cache permissions in a non-restricted shell.

### Finding 5
- category: docs
- severity: Medium
- confidence: High
- affected files or endpoints: `README.md:20`, `README.md:30`, `docs/getting-started.md:59`, `Makefile:52`
- reproduction steps:
  1. Follow quick-start docs exactly.
  2. Run web commands (`make web-build`, `make web-typecheck`, `make web-lint`) without prior install step.
  3. Observe missing module/tooling errors.
- why it happens (hypothesis): Web dependency bootstrap is not included in quick-start sequence.
- fix recommendation: Add explicit `make web-install` step before any web command in README/getting-started.
- quick workaround if any: Run `make web-install` before `make web-dev`/`make web-build`.

4) Top 10 Fix Priority List
1. Make `jarvis ask --json` fail fast and deterministic on provider transport/DNS errors.
2. Add orchestrator/state-extraction guardrails so provider failure does not trigger long noisy timeout paths.
3. Fix integration hang for `test_non_admin_cannot_toggle_lockdown` and audit nearby authorization integration tests.
4. Add `make dev` preflight checks for bound ports (`11434`, `30000`, `8080`) with actionable remediation.
5. Add docs troubleshooting for Docker port conflicts and optional alternate-port profiles.
6. Stabilize `make web-install` failure mode with robust npm diagnostics and retry guidance.
7. Update quick-start docs to include explicit web dependency bootstrap step.
8. Improve CLI/doctor messaging to distinguish environment sandbox limits vs real service outages.
9. Add a CI or local smoke target that validates “new user setup” end-to-end.
10. Add regression tests for provider-unavailable and DNS-failure UX in CLI/API flows.

5) Beta Tester Verdict
- Needs major fixes
