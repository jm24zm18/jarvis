# Git Workflow

Canonical branch and PR policy for this repository.

## Branch Model

- `master`: production/stable branch.
- `dev`: integration branch for ongoing work.
- Work branches: short-lived branches created from `dev`.

## Branch Naming

Use one of these prefixes for work branches:

- `agent/<topic>` for AI-agent implementation branches.
- `feature/<topic>` for feature work.
- `fix/<topic>` for bug fixes.
- `chore/<topic>` for maintenance.

Examples:

- `agent/lintfix-b904`
- `feature/webhook-trigger-admin-ui`
- `fix/rbac-thread-ownership`

## PR Routing Rules

1. Work branch -> `dev`
2. `dev` -> `master` (release promotion only)
3. Never open work branch -> `master` directly

## Human-in-the-Loop Rule

- `dev -> master` requires at least one non-author human approval.
- Agent-generated changes may not self-promote to `master`.

## Required GitHub Settings

Configure branch protection rules:

- `dev` protection:
  - Require pull request before merging
  - Require status check: `Branch Policy / enforce-policy`
  - Optional: require CI checks (`CI / lint`, `CI / typecheck`, test jobs)

- `master` protection:
  - Require pull request before merging
  - Require status check: `Branch Policy / enforce-policy`
  - Require at least 1 approval
  - Dismiss stale approvals on new commits (recommended)
  - Restrict who can push directly (recommended)

## Standard Flow

```bash
# 1) sync integration branch
git checkout dev
git pull

# 2) create work branch
git checkout -b agent/<topic>

# 3) implement + verify
make lint
make typecheck
make test-gates
make docs-check

# 4) push and open PR to dev
git push -u origin agent/<topic>

# 5) after merge to dev, promote dev to master via PR
```

## Agent Notes

- Agents should always report branch name and target PR base in handoff notes.
- If a task starts from `master` accidentally, restart from `dev`.

## Related Docs

- `docs/README.md`
- `CONTRIBUTING.md`
- `AGENTS.md`
- `docs/build-release.md`
- `agents/TEAM.md`
