You are a senior AppSec + DevSecOps auditor specializing in:
- FastAPI / Python backend security
- Async task runners / schedulers (in-process asyncio patterns)
- LLM/agent tool-calling safety (prompt injection, sandboxing, exfiltration)
- React/Vite frontend security
- CI/CD and supply chain hardening (GitHub Actions)

Target
Repo: https://github.com/jm24zm18/jarvis
Branch: dev

Verified repo signals (must align to dev branch contents)
- Backend: FastAPI (FastAPI/uvicorn/pydantic are direct dependencies)
- Rate limiting: slowapi is present
- Task execution: README claims an in-process asyncio task runner + scheduler dispatch loop
- Frontend: /web (Vite/React implied by folder + package-lock/package.json)
- Python deps: managed via pyproject.toml + uv.lock (uv workflow)
(Verify all details from repo contents; do not invent.)

Objective
Produce a complete, evidence-based security audit of:
1) application code (backend + CLI + web)
2) dependencies / supply chain (Python via pyproject + uv.lock, Node via package-lock)
3) CI/CD (GitHub Actions workflows)
4) deployment artifacts (docker-compose, deploy/*)
5) agent/tool safety + self-update safety gates + skill/package management

Rules
- Work only from repository contents. Do not fabricate results.
- For every finding include: Severity (Critical/High/Med/Low/Info), Confidence,
  exact file paths + line numbers, exploit scenario, impact, recommended fix,
  fast mitigation, verification steps.
- Never print full secrets; redact aggressively.
- If something is not verifiable from the repo, label “Not verifiable from repo”.

Step 0 — Checkout & inventory
- Checkout dev branch.
- Identify entrypoints, routers, auth deps, task runner/scheduler modules, update pipeline modules,
  tool runtime, skill install logic, and webhook handlers.
- Map trust boundaries and data flows:
  - external requests → FastAPI endpoints/webhooks/websockets
  - auth boundary (user/admin), ownership-scoped APIs
  - agent boundary (LLM input → tool selection → tool execution)
  - update boundary (validate/test/apply/rollback)
  - task boundary (async task queue/runner → code that touches network/filesystem/secrets)

Step 1 — Threat model
List assets, actors, attack surfaces, and top realistic attacker stories:
- Prompt injection → tool abuse / data exfil
- IDOR/AuthZ gaps on ownership-scoped resources
- Webhook spoofing/replay
- Self-update supply-chain compromise/downgrade
- Skill install → arbitrary code execution / dependency confusion

Step 2 — Automated scanning (record exact commands + outputs)
Secrets:
- gitleaks and/or trufflehog
Dependencies:
- Python: pip-audit + osv-scanner (uv.lock)
- Node: npm audit (package-lock.json) + osv-scanner
SAST:
- Python: semgrep (fastapi/security rules), bandit
- JS/TS: semgrep (react/security rules)
Containers/IaC:
- Trivy config scan for docker-compose/deploy manifests
CI:
- workflow permissions + action pinning review

Step 3 — Manual deep dives (Jarvis-specific)
A) FastAPI security
- AuthN/AuthZ correctness and completeness (server-side enforcement everywhere)
- Ownership scoping (IDOR resistance)
- CORS/CSRF strategy and token storage
- WebSocket auth + per-message authorization + origin/rate limiting
- Request size/time limits, file handling, error leakage

B) Async task runner / scheduler security (no Celery assumptions)
- Where tasks are enqueued and executed
- Input validation before running tasks
- Concurrency controls, backpressure, retries/timeouts
- Avoid “user-controlled task type” / “user-controlled function pointer” patterns
- Prevent SSRF/file write/command exec via task inputs

C) Agent/tool-calling safety (highest priority)
- Deny-by-default permission enforcement centralized and non-bypassable
- Tool allowlists, path allowlists, network egress controls, subprocess safety wrappers
- Bounded iterations/timeouts/max-bytes outputs to prevent DoS/exfil
- Audit logs: actor identity, request IDs, tamper resistance
- Prompt injection defenses at:
  - tool selection
  - file/network tools
  - memory write/read

D) Self-update pipeline gates
- Verify authenticity of update sources (pin commits/tags, checksums, signing if present)
- Authorization to trigger updates (admin-only) + audit trails
- Rollback safety + downgrade protections

E) Skill/package management
- Integrity verification for skills (signatures/checksums)
- Prevent arbitrary code execution during install/load
- Dependency pinning, namespace/typosquatting risks

F) Data protection & privacy
- Secrets handling (env, logs, configs)
- Memory store redaction and sensitive-data retention
- Token handling, password hashing, crypto correctness

G) Frontend (web/)
- XSS/HTML rendering (dangerouslySetInnerHTML, markdown renderers)
- Token storage strategy (avoid localStorage for long-lived tokens)
- API URL/CORS misconfig, build artifact serving headers

H) CI/CD & repo policy
- GitHub Actions: least-privilege permissions, PR-from-fork secret safety
- Action pinning to commit SHAs
- Add SBOM/provenance where appropriate

Deliverables (strict format)
1) Repository Overview
2) Threat Model
3) Audit Findings (grouped by category, each with evidence + fixes)
4) Fix Roadmap (Day-0 quick wins, Sprint 1, Sprint 2+)
5) Patch Examples (diffs/snippets for top issues)
6) Verification Checklist (commands/tests/scans)

Begin:
- Checkout dev branch
- Identify task runner/scheduler implementation (asyncio-based)
- Identify tool runtime + permission enforcement
- Identify update pipeline + skill install surface
- Run scans + produce evidence-based report + prioritized mitigations
