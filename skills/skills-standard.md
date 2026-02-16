---
slug: skills-standard
pinned: true
---

# Skills Standard

## Purpose
Define the canonical format for reusable Jarvis skills and when to write or update one.

## Key Facts
- Skills are concise, reusable markdown documents.
- Seed skills live on disk and are synced into the database at startup.
- Agent-authored skills are stored in the database and can be agent-scoped or global.
- Pinned skills are always included in prompt context.

## Usage
1. Use `skill_list` to discover existing skills before starting unfamiliar work.
2. Use `skill_read` to load relevant skills by slug.
3. Use `skill_write` to add or update reusable guidance after completing work.
4. Keep each section practical and action-oriented.

## Examples
```md
# Deploy Checklist

## Purpose
How to deploy the API service safely.

## Key Facts
- Run migrations before restart.
- Validate `/healthz` after rollout.

## Usage
1. Pull latest code.
2. Run `make migrate`.
3. Restart service and verify health.

## Notes
If rollout fails, execute rollback procedure from ops runbook.
```

## Notes
If a skill changes project-wide behavior, update `jarvis-project` so all agents inherit the current baseline.
