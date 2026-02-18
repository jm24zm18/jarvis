  # Full Documentation Refresh and Gap-Fill Plan (Jarvis)

  ## Summary

  Perform a full-surface docs maintenance pass across repository docs, agent guidance
  docs, and operator docs; correct stale instructions; add missing interface references
  (API + CLI + deploy/web ops); and add doc-sync automation so docs stay accurate.

  This plan uses your chosen defaults:

  - Scope: Full surface.
  - API docs: Dual structure (generated reference + curated usage guide).

  ## Public Interfaces / Types Changes

  1. Add documentation-only interfaces:

  - docs/README.md as the canonical docs index and navigation entrypoint.
  - docs/api-reference.md generated from FastAPI OpenAPI as machine-accurate endpoint/
    source-of-truth.
  - docs/api-usage-guide.md as human workflow guide (auth, threads/messages, memory,
    schedules, self-update, governance).
  - docs/cli-reference.md covering all CLI commands/options in src/jarvis/cli/main.py.
  - docs/deploy-operations.md for deploy/* scripts and systemd units.
  - docs/web-admin-guide.md for web pages and RBAC behavior.

  2. Add doc maintenance tooling surface:

  - scripts/generate_api_docs.py (or equivalent) to emit/update docs/api-reference.md
    from OpenAPI.
  - scripts/docs_check.py (or equivalent) to validate links, command drift, and API-doc
    sync.
  - Makefile targets:
      - make docs-generate
      - make docs-check

  3. No runtime API behavior changes are planned.

  ## Implementation Plan

  ### Phase 1: Baseline and Drift Matrix

  1. Build a “docs drift matrix” mapping each major area to source files and current doc
     coverage.
  2. Include at minimum these source areas:

  - API routes: src/jarvis/routes/health.py, src/jarvis/routes/ws.py, src/jarvis/routes/
    api/* (mounted only).
  - CLI: src/jarvis/cli/main.py.
  - Runtime/ops: src/jarvis/main.py, src/jarvis/tasks/*, deploy/*, Makefile.
  - Web/admin: web/src/pages/admin/*, web/src/pages/chat/index.tsx, web/src/pages/login/
    index.tsx.

  3. Record known stale items to fix first:

  - README.md:28 (make worker)
  - docs/build-release.md:26 (make worker)
  - docs/github-pr-automation.md:46 (make worker)
  - docs/DOCS_AGENT_PROMPT.md:103 (make worker)
  - Slash-command ambiguity in runbook (/restart, /unlock, /status) vs HTTP endpoints.

  ### Phase 2: Normalize Existing Core Docs

  1. Update and align:

  - README.md
  - docs/getting-started.md
  - docs/local-development.md
  - docs/configuration.md
  - docs/architecture.md
  - docs/codebase-tour.md
  - docs/testing.md
  - docs/runbook.md
  - docs/build-release.md
  - docs/change-safety.md
  - docs/release-checklist.md

  2. Enforce consistency rules across these files:

  - Commands must exist (make target, CLI command, route).
  - Endpoint naming must distinguish HTTP endpoint vs chat slash command.
  - Cross-links must be reciprocal for related docs.
  - Terminology and invariants match AGENTS.md and CLAUDE.md.

  ### Phase 3: Add Missing Docs

  1. Create docs/README.md:

  - Purpose of each doc.
  - “Start here” sequences for new devs, operators, and release owners.

  2. Create docs/cli-reference.md:

  - Full command reference: setup, doctor, gemini-login, ask, chat, export, build, test-
    gates, skill install/list/info.
  - Required preconditions and examples.

  3. Create docs/api-reference.md:

  - Generated endpoint reference from live OpenAPI.
  - Include method/path, auth requirement, request/response schema summaries.

  4. Create docs/api-usage-guide.md:

  - Task-oriented flows: login/session, thread lifecycle, messaging, memory ops,
    schedules, self-update approvals, governance/stories.

  5. Create docs/deploy-operations.md:

  - deploy/install-systemd.sh, deploy/healthcheck.sh, deploy/rollback.sh, deploy/
    restore_db.sh, deploy/systemd/*.
  - Rollback/restore procedures and prerequisites.

  6. Create docs/web-admin-guide.md:

  - Route map for admin/chat/login pages.
  - Role/ownership behavior from UI perspective.
  - WebSocket subscription model and expected events.

  ### Phase 4: Keep AGENTS/CLAUDE/README Synchronized

  1. Update AGENTS.md and CLAUDE.md to match refreshed command set and docs map.
  2. Ensure README.md “Documentation Index” points to all canonical docs, including new
     API/CLI/deploy/web docs.
  3. Preserve policy/security invariants wording consistency across all three files.

  ### Phase 5: Automation and Guardrails

  1. Implement make docs-generate:

  - Regenerate docs/api-reference.md from OpenAPI.

  2. Implement make docs-check:

  - Broken local markdown links.
  - Command drift check:
      - make commands in docs exist in Makefile.
      - uv run jarvis ... commands exist in CLI.
  - API drift check:
      - Referenced endpoints in docs/api-reference.md match current OpenAPI.

  3. Add docs checks to CI quality gates (test-gates or dedicated docs job).

  ## Test Cases and Scenarios

  1. Docs link integrity:

  - All markdown links resolve locally (excluding external URLs).

  2. Command validity:

  - Every make ... in docs maps to a real target.
  - Every CLI command in docs exists in jarvis --help / subcommand help.

  3. API sync:

  - Regenerated API reference has no diff after clean generation.
  - Mounted routes only are documented as public API.

  4. Consistency checks:

  - AGENTS.md, CLAUDE.md, and README.md command blocks and doc index are aligned.

  5. Operator flow validation:

  - Follow docs/deploy-operations.md and docs/runbook.md start-to-finish with no missing
    step/ambiguity.

  6. Web/admin flow validation:

  - docs/web-admin-guide.md matches real page paths and role behavior.

  ## Assumptions and Defaults

  1. Include full repository docs surface, including prompt-library and agent instruction
     docs.
  2. API docs are split into:

  - Generated reference (docs/api-reference.md)
  - Curated guide (docs/api-usage-guide.md)

  3. Do not delete existing docs unless replaced by a clearly superior canonical doc with
     redirects/links updated.
  4. Treat vendored/generated trees as out of scope for manual maintenance:

  - web/node_modules/**
  - docs/gemini/venv/**

  5. Document only mounted/public endpoints as API reference; mention unmounted/internal
     route modules only as implementation notes.
