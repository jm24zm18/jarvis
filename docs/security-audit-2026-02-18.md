# Security Audit Report (dev branch)

Date (UTC): 2026-02-18T05:25:08Z  
Repository: `jm24zm18/jarvis`  
Branch/commit audited: `dev` / `b9a4e1447282ec8a0d67fdd22e8591b7c2b7adc4`

## 1) Repository Overview

- Backend: FastAPI app with asyncio lifespan/task scheduling in `src/jarvis/main.py`.
- Auth model: bearer session token in `Authorization` header for API (`src/jarvis/auth/dependencies.py`), token hash persisted in SQLite (`src/jarvis/auth/service.py`).
- WebSocket channel: `/ws` endpoint with subscribe actions in `src/jarvis/routes/ws.py`.
- Agent/tool runtime: centralized policy decision + tool execution in `src/jarvis/tools/runtime.py` and `src/jarvis/policy/engine.py`.
- Async task execution: in-process task runner in `src/jarvis/tasks/runner.py` and periodic scheduler in `src/jarvis/tasks/periodic.py`.
- Self-update: patch proposal/validation/test/apply pipeline in `src/jarvis/tasks/selfupdate.py` and `src/jarvis/selfupdate/pipeline.py`.
- Skills/package surface: skill CRUD and package install logic in `src/jarvis/memory/skills.py`.
- Frontend: React/Vite app under `web/`, auth token storage in `web/src/stores/auth.ts`.
- CI/CD: workflows in `.github/workflows/*.yml`.
- Deploy artifacts: `docker-compose.yml`, `deploy/systemd/*.service`.

### Trust Boundaries and Data Flows

- External HTTP -> FastAPI routes (`src/jarvis/routes/api/*`, `src/jarvis/routes/ws.py`, `src/jarvis/channels/whatsapp/router.py`).
- Auth boundary:
  - API: `require_auth` / `require_admin` in `src/jarvis/auth/dependencies.py`.
  - WS: token validation in `src/jarvis/routes/ws.py`.
- Agent boundary: LLM tool calls -> `ToolRuntime.execute` -> `policy.engine.decision` -> tool handler.
- Update boundary: self-update states + approvals (`src/jarvis/tasks/selfupdate.py`, `src/jarvis/db/queries.py`).
- Task boundary: inbound requests enqueue async tasks via in-process `TaskRunner.send_task`.

## 2) Threat Model

### Assets

- Web session tokens, admin role privileges, agent tool permissions, self-update controls, webhook secrets, event logs, and memory state.

### Actors

- Anonymous internet user, authenticated non-admin user, compromised user browser, malicious webhook sender, compromised CI/dependency source, compromised plugin/skill package source.

### Primary Attack Surfaces

- `/ws` WebSocket endpoint and subscriptions.
- `/api/v1/auth/*` login/session flow.
- `/api/v1/webhooks/*` and `/webhooks/whatsapp`.
- Tool runtime (`exec_host`, web search, session tools).
- Self-update patch pipeline and approval consumption.
- Frontend token storage and WS token transport.
- GitHub Actions third-party action execution.

### Realistic Attacker Stories

- Authenticated low-privilege user subscribes to system-level WS feed and observes privileged events.
- Stolen token from browser storage or URL logs is reused for API/WS takeover.
- Replayed signed webhook repeatedly retriggers expensive or privileged automation.
- CI action supply-chain compromise via mutable action refs.
- Untrusted skill package install injects malicious instructions without integrity checks.

## 3) Audit Findings

## A. AuthN/AuthZ and Session Security

### Finding A1: Non-admin users can subscribe to system-level WebSocket broadcasts
- Severity: **High**
- Confidence: **High**
- Evidence:
  - `src/jarvis/routes/ws.py:119` accepts `subscribe_system` with no role check.
  - `src/jarvis/routes/ws.py:184` routes `system.*` events to all subscribed system sockets.
- Exploit scenario:
  1. Attacker logs in as normal user.
  2. Opens `/ws` and sends `{"action":"subscribe_system"}`.
  3. Receives global system events not scoped to owned threads.
- Impact:
  - Leakage of system operational events and potentially sensitive metadata across tenant boundary.
- Recommended fix:
  - Gate `subscribe_system` behind `role == "admin"` (or explicit system-scope permission).
  - Add per-event filtering before broadcast.
- Fast mitigation:
  - Disable system subscriptions for non-admin in WS action handler.
- Verification steps:
  - Add integration test: non-admin `subscribe_system` returns `forbidden`.
  - Add integration test: admin still receives `system.*`.
- Remediation update (2026-02-18): **Resolved**
  - Code fix:
    - `src/jarvis/routes/ws.py:119` now gates `subscribe_system` with `role == "admin"` and returns `forbidden` for non-admins (`src/jarvis/routes/ws.py:120` to `src/jarvis/routes/ws.py:123`).
  - Regression evidence:
    - `tests/integration/test_authorization.py:126` (`test_non_admin_websocket_subscribe_system_rejected`).
    - `tests/integration/test_websocket.py:59` (`test_admin_subscribe_system_receives_system_events`).
  - Validation run:
    - `uv run pytest tests/integration/test_authorization.py -k websocket -v` -> `2 passed`.
    - `uv run pytest tests/integration/test_websocket.py -v` -> `2 passed`.

### Finding A2: Session token is passed in WS query string and persisted in localStorage
- Severity: **High**
- Confidence: **High**
- Evidence:
  - `web/src/hooks/useWebSocket.ts:30` uses `/ws?token=...`.
  - `web/src/stores/auth.ts:10` and `web/src/stores/auth.ts:17` store token in `localStorage`.
- Exploit scenario:
  - Token appears in logs/proxies/history as URL query and is persistently available to XSS payloads through `localStorage`.
- Impact:
  - Session hijack and unauthorized API/WS actions.
- Recommended fix:
  - Move WS auth to `Authorization` via subprotocol or post-connect auth message.
  - Store auth token in secure, short-lived HTTP-only cookie (or memory-only token with refresh flow).
- Fast mitigation:
  - Reduce token TTL and rotate active sessions.
  - Disable verbose access logs that include URL query.
- Verification steps:
  - Confirm no token appears in WS URL.
  - Confirm token is absent from `localStorage`.

### Finding A3: Login endpoint lacks explicit rate limiting / brute-force controls
- Severity: **Medium**
- Confidence: **High**
- Evidence:
  - Login route does direct password compare with no throttling in `src/jarvis/routes/api/auth.py:216`.
  - Route-level limiter use appears only in channels routes (`src/jarvis/routes/api/channels.py:53` and `src/jarvis/routes/api/channels.py:90`).
- Exploit scenario:
  - Automated password guessing against `/api/v1/auth/login`.
- Impact:
  - Elevated risk of unauthorized admin/user session issuance.
- Recommended fix:
  - Apply per-IP and per-account rate limits + short lockouts + telemetry.
- Fast mitigation:
  - Front reverse-proxy rate limiting for `/api/v1/auth/login`.
- Verification steps:
  - Repeated failed login attempts should return 429/lockout.

## B. Webhooks

### Finding B1: Webhook signatures are validated but replay protection is missing
- Severity: **Medium**
- Confidence: **High**
- Evidence:
  - Signature check for GitHub validates HMAC only (`src/jarvis/routes/api/webhooks.py:87` to `src/jarvis/routes/api/webhooks.py:101`).
  - Trigger webhook HMAC check has no nonce/timestamp/replay cache (`src/jarvis/routes/api/webhooks.py:50` to `src/jarvis/routes/api/webhooks.py:59`).
- Exploit scenario:
  - Adversary replays a previously valid signed payload to trigger duplicate automation.
- Impact:
  - Task storms, duplicate PR automation, and operational abuse.
- Recommended fix:
  - Enforce replay window + deduplicate using delivery ID / nonce storage.
- Fast mitigation:
  - Implement temporary dedupe on payload hash + recent timestamp.
- Verification steps:
  - Same delivery ID or nonce is rejected on second attempt.
- Remediation update (2026-02-18): **Resolved (GitHub webhook path)**
  - Code fix:
    - Replay receipt table added in `src/jarvis/db/migrations/051_webhook_replay_guard.sql:1`.
    - Replay window config added: `WEBHOOK_REPLAY_WINDOW_MINUTES` (`src/jarvis/config.py:186`, `.env.example:77`).
    - Delivery ID required and replay rejected in `src/jarvis/routes/api/webhooks.py:168` to `src/jarvis/routes/api/webhooks.py:176`.
  - API contract update:
    - `POST /api/v1/webhooks/github` now documents `400/401/409` responses (`src/jarvis/routes/api/webhooks.py:146`, `docs/api-reference.md:95`).
  - Regression evidence:
    - Missing delivery header test: `tests/integration/test_web_api.py:413`.
    - Replay rejection test: `tests/integration/test_web_api.py:437`.
    - Distinct IDs accepted test: `tests/integration/test_web_api.py:461`.
  - Validation run:
    - `uv run pytest tests/integration/test_web_api.py -k github_webhook -v` -> `6 passed`.

## C. Agent/Tool Runtime and Logging

### Finding C1: Redaction list is narrow relative to logged tool arguments/results
- Severity: **Medium**
- Confidence: **Medium**
- Evidence:
  - Sensitive key list is limited in `src/jarvis/events/writer.py:13`.
  - Tool runtime logs `arguments` and `result` payloads in events:
    - `src/jarvis/tools/runtime.py:54`
    - `src/jarvis/tools/runtime.py:130`
- Exploit scenario:
  - Tool responses containing non-standard secret keys (`secret`, `private_key`, `cookie`, etc.) may persist in event logs.
- Impact:
  - Confidentiality loss via logs and trace APIs.
- Recommended fix:
  - Expand key-based redaction + add value-pattern redaction (token/key/PEM formats).
  - Consider denylisting sensitive tool output fields before persistence.
- Fast mitigation:
  - Restrict access to raw trace views and event exports.
- Verification steps:
  - Inject synthetic secret-like output and confirm redaction in stored events.

## D. Skill/Package Management

### Finding D1: Skill package install has no integrity/authenticity verification
- Severity: **Medium**
- Confidence: **High**
- Evidence:
  - Installation consumes local package files and manifest directly:
    - `src/jarvis/memory/skills.py:445`
    - `src/jarvis/memory/skills.py:477`
  - No signature/checksum validation before install.
- Exploit scenario:
  - Tampered package content is installed and later influences agent behavior.
- Impact:
  - Prompt-level supply-chain compromise and behavior manipulation.
- Recommended fix:
  - Require signed manifest or trusted checksum allowlist for package sources.
- Fast mitigation:
  - Restrict install source to audited local paths and admin-only workflows.
- Verification steps:
  - Tampered package should fail integrity check pre-install.

## E. CI/CD and Supply Chain

### Finding E1: GitHub Actions use mutable refs (including `@main`) instead of pinned SHAs
- Severity: **Medium**
- Confidence: **High**
- Evidence:
  - `.github/workflows/ci.yml:13`, `.github/workflows/ci.yml:14`, `.github/workflows/ci.yml:90`.
  - `trufflesecurity/trufflehog@main` in `.github/workflows/ci.yml:90`.
- Exploit scenario:
  - Upstream action compromise changes runtime behavior in CI.
- Impact:
  - Build pipeline compromise, secret exposure, malicious artifact production.
- Recommended fix:
  - Pin all third-party actions to full commit SHAs.
- Fast mitigation:
  - Replace `@main` immediately with a reviewed tag/SHA.
- Verification steps:
  - Workflow diff shows only SHA-pinned external actions.
- Remediation update (2026-02-18): **Resolved**
  - Code fix:
    - Action refs pinned to full SHAs in:
      - `.github/workflows/ci.yml:16`
      - `.github/workflows/branch-policy.yml:19`
      - `.github/workflows/release.yml:14`
  - Additional hardening:
    - Replaced mutable `trufflesecurity/trufflehog@main` usage with pinned image digest invocation in `.github/workflows/ci.yml:85` to `.github/workflows/ci.yml:89`.

### Finding E2: CI workflow lacks explicit least-privilege `permissions` block
- Severity: **Low**
- Confidence: **High**
- Evidence:
  - `.github/workflows/ci.yml` has no top-level `permissions`.
- Exploit scenario:
  - Token permissions may exceed job requirements.
- Impact:
  - Increased blast radius if CI job is compromised.
- Recommended fix:
  - Add `permissions: contents: read` globally and elevate per job only if needed.
- Fast mitigation:
  - Add minimal permissions at workflow top-level now.
- Verification steps:
  - Workflow runs successfully with constrained token permissions.
- Remediation update (2026-02-18): **Resolved**
  - Code fix:
    - Added top-level least-privilege permissions to CI workflow:
      - `.github/workflows/ci.yml:9` -> `permissions: contents: read`.
  - Verification note:
    - Local YAML update applied; runtime workflow pass confirmation will occur on next CI run for this branch.

### Finding E3: Known vulnerable dependency versions in lockfiles (Python + Node)
- Severity: **Medium**
- Confidence: **High**
- Evidence:
  - `uv.lock` includes `starlette==0.47.3` (`uv.lock:1062`, `uv.lock:1063`).
  - `osv-scanner` and `pip-audit` both reported Starlette vulnerability fixed in `0.49.1`.
  - `web/package-lock.json` includes vulnerable dev dependencies:
    - `ajv@6.12.6` (`web/package-lock.json:1798`, `web/package-lock.json:1799`)
    - `esbuild@0.21.5` (`web/package-lock.json:2222`, `web/package-lock.json:2223`)
  - `osv-scanner` reported:
    - `GHSA-7f5h-v6xp-fcq8` (PyPI `starlette`, fixed `0.49.1`)
    - `GHSA-2g4f-4pwh-qvx6` (`ajv`, fixed `8.18.0`)
    - `GHSA-67mh-4wv8-2f99` (`esbuild`, fixed `0.25.0`)
- Exploit scenario:
  - Vulnerable transitive or direct package behavior can be reached via application or build/test tooling flows.
- Impact:
  - Increased risk of known CVE-class exploitation and downstream compromise.
- Recommended fix:
  - Upgrade lockfiles to fixed versions and rerun full test gates.
  - Add CI gate to fail on new High/Critical advisories from lockfile scans.
- Fast mitigation:
  - Prioritize `starlette` bump to fixed release.
  - Update Node lockfile for `ajv` and `esbuild` remediation path.
- Verification steps:
  - `osv-scanner --lockfile=uv.lock` returns zero affected packages.
  - `osv-scanner --lockfile=web/package-lock.json` returns zero affected packages.
  - `uv run pip-audit` and `npm audit --json` show no unresolved target vulnerabilities.

## F. Deployment Hardening

### Finding F1: Systemd services lack sandbox hardening directives
- Severity: **Medium**
- Confidence: **High**
- Evidence:
  - Service units define runtime commands but no hardening flags:
    - `deploy/systemd/jarvis-api.service:5`
    - `deploy/systemd/jarvis-worker.service:5`
    - `deploy/systemd/jarvis-scheduler.service:5`
- Exploit scenario:
  - Post-compromise process has broad filesystem/process capabilities.
- Impact:
  - Higher privilege abuse and lateral movement risk on host.
- Recommended fix:
  - Add `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectSystem=strict`, `ProtectHome=yes`, `ReadWritePaths=...`, `CapabilityBoundingSet=`.
- Fast mitigation:
  - Introduce `NoNewPrivileges=yes` and `PrivateTmp=yes` immediately.
- Verification steps:
  - `systemd-analyze security` score improves for each unit.

## G. Informational / Potential False Positives

- Bandit reported many `B608` string-built SQL issues, but reviewed patterns mostly still parameterize user values and/or build placeholder-only clauses. Treat as refactor opportunities, not confirmed SQLi.
- `gitleaks` reported 6 `generic-api-key` matches; triage indicates 5 are clear false positives (agent prose/C-header tokens/placeholders) and 1 is in local untracked `.env` (not versioned repo content).

## 4A) Open Follow-Ups (Plan Alignment)

- Finding A2 (WS query token + `localStorage` persistence):
  - Backlog mapping: `BK-038` in `docs/PLAN.md`.
  - Target state: migrate off WS query-token transport and replace persistent browser token storage model.
- Finding E3 (dependency vulnerabilities in lockfiles):
  - Backlog mapping: `BK-040` in `docs/PLAN.md`.
  - Target state: remediate `starlette`, `ajv`, and `esbuild` lockfile findings with scanner re-runs attached to PR evidence.

## 4) Fix Roadmap

### Day-0 (Immediate)
- Block non-admin `subscribe_system`.
- Move off WS query-token transport path (or at minimum stop logging query strings).
- Add login and webhook replay/throttle controls.
- Pin `trufflesecurity/trufflehog` away from `@main`.
- Upgrade vulnerable locked dependencies (`starlette`, `ajv`, `esbuild`) and regenerate lockfiles.

### Sprint 1
- Token model hardening (short-lived, rotation, safer browser storage model).
- Expand event redaction policy and add tests for secret-pattern masking.
- Add replay-safe webhook model (nonce/delivery-id persistence).
- Add CI `permissions` minimum baseline.

### Sprint 2+
- Skill package signature/checksum trust chain.
- Systemd hardening profile with documented required writable paths.
- Add SBOM/provenance generation in CI release flow.

## 5) Patch Examples (snippets only)

### Example 1: Restrict system WS subscription to admins

```python
# src/jarvis/routes/ws.py
elif action == "subscribe_system":
    if role != "admin":
        await websocket.send_json({"type": "error", "detail": "forbidden"})
        continue
    await hub.subscribe_system(websocket)
```

### Example 2: Add replay guard for GitHub webhook

```python
# pseudo: persist X-GitHub-Delivery for N minutes and reject duplicates
delivery_id = request.headers.get("X-GitHub-Delivery", "").strip()
if not delivery_id or seen_recently(delivery_id):
    raise HTTPException(status_code=409, detail="replay detected")
mark_seen(delivery_id, ttl_minutes=10)
```

### Example 3: CI action pinning

```yaml
- uses: actions/checkout@<full-commit-sha>
- uses: astral-sh/setup-uv@<full-commit-sha>
- uses: trufflesecurity/trufflehog@<full-commit-sha>
```

## 6) Verification Checklist (commands/tests/scans)

Commands executed in this audit session:

```bash
# Repo baseline
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD

# Local SAST
UV_CACHE_DIR=/tmp/uv-cache uv run bandit -r src/jarvis -c pyproject.toml -ll

# Dependency scans
UV_CACHE_DIR=/tmp/uv-cache XDG_CACHE_HOME=/tmp/.cache uv run pip-audit --cache-dir /tmp/pip-audit-cache
cd web && npm audit --json

# Secret scanning
gitleaks detect --source . --no-git --redact --report-format json --report-path /tmp/sec-tools/reports/gitleaks.json
trufflehog filesystem . --only-verified

# SAST
semgrep --config p/python --config p/owasp-top-ten src/jarvis
semgrep --config p/react --config p/javascript web/src

# Lockfile vulnerability scans
osv-scanner --lockfile=uv.lock
osv-scanner --lockfile=web/package-lock.json

# IaC/config scan
trivy fs --scanners misconfig . --cache-dir /tmp/sec-tools/trivy-cache --skip-dirs docs/gemini/venv --skip-dirs .venv --skip-dirs web/node_modules --format json -o /tmp/sec-tools/reports/trivy-fs-misconfig.json

# Supplemental secret pattern grep
rg -n --hidden -g '!*uv.lock' -g '!docs/gemini/venv/**' '(AKIA|BEGIN .*PRIVATE KEY|ghp_|AIza|xox)' .
```

Observed outcomes:
- `bandit`: completed with medium findings (many B608/B108/B104 flags; manual triage performed).
- `semgrep` (python/react/javascript): 0 findings across scanned tracked files.
- `gitleaks`: 6 findings (all `generic-api-key`); triage indicates mostly false positives and one untracked local `.env` secret.
- `trufflehog --only-verified`: 0 verified secrets.
- `osv-scanner`:
  - Python lockfile: 1 High advisory affecting `starlette` (fixed in `0.49.1`).
  - Node lockfile: 2 Medium advisories affecting `ajv` and `esbuild`.
- `pip-audit`: 1 known vulnerability in `starlette 0.47.3` (fix `0.49.1`).
- `npm audit --json`: 12 moderate vulnerabilities (dev dependency graph).
- `trivy`:
  - `trivy config` mode: environment-specific detection issue (`Detected config files num=0` in this runtime).
  - `trivy fs --scanners misconfig`: executed successfully but reported 0 misconfig findings.

Items marked **Not verifiable from repo/runtime in this environment**:
- Full root-cause for Trivy `config` target detection anomaly in this environment.
- Real deployment runtime controls outside committed files.
