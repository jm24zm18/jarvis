# Prompt Library

Reusable AI-agent prompts for common engineering workflows in this repository.

## How To Use

1. Pick the prompt that matches your task.
2. Copy the prompt body into your agent runner.
3. Provide task-specific context (ticket, bug report, target files, acceptance criteria).
4. Require verification output (tests/checks/docs updates) before accepting changes.

## Prompts

- [Bugfix Agent](./BUGFIX_AGENT_PROMPT.md)
  - Use for reproducible defects, regressions, and hotfixes.

- [Refactor Agent](./REFACTOR_AGENT_PROMPT.md)
  - Use for code cleanup and design improvement without behavior changes.

- [Release Manager](./RELEASE_MANAGER_PROMPT.md)
  - Use before staging/production promotion and post-release validation.

- [Security Review](./SECURITY_REVIEW_PROMPT.md)
  - Use for threat-focused audits, auth/RBAC review, and security sign-off.

- [Performance Agent](./PERFORMANCE_AGENT_PROMPT.md)
  - Use when latency/throughput/resource usage must improve with measured evidence.

- [Test Suite Hardening](./TEST_SUITE_HARDENING_PROMPT.md)
  - Use to reduce flakiness, fill coverage gaps, and improve reliability.

- [Migration Agent](./MIGRATION_AGENT_PROMPT.md)
  - Use for schema/data migrations and rollout-safe DB changes.

- [Incident Runbook](./INCIDENT_RUNBOOK_PROMPT.md)
  - Use during outages or degraded production behavior.

- [Onboarding](./ONBOARDING_PROMPT.md)
  - Use to build/update first-day setup and repo orientation guidance.

- [PR Review Agent](./PR_REVIEW_AGENT_PROMPT.md)
  - Use for structured review focused on bugs, regressions, and safety risks.

## Recommended Pairings

- Feature work: `FEATURE_BUILDER_PROMPT` + `PR_REVIEW_AGENT_PROMPT`
- Release cycle: `RELEASE_MANAGER_PROMPT` + `SECURITY_REVIEW_PROMPT`
- Production issue: `INCIDENT_RUNBOOK_PROMPT` + `BUGFIX_AGENT_PROMPT`
- Ongoing docs quality: `DOCS_AGENT_PROMPT`

