---
slug: skill-orchestration
pinned: false
---

# Skill Orchestration

## Purpose
Define when to solve directly, when to use an existing skill, and when to create or update a reusable skill.

## Key Facts
- Prefer direct handling for one-off, low-risk tasks with no reuse value.
- Use existing skills for recurring workflows, high-risk domains, or tasks needing consistent policy/process steps.
- Create/update a skill when guidance is reusable across agents or likely to recur with meaningful variation.
- Decision cost includes context size, latency, maintenance burden, and failure blast radius.
- Avoid overlapping skills; each skill should own one operational concern.

## Usage
1. Triage task using this decision sequence:
   - Is the task low-risk and non-recurring? -> handle directly.
   - Does a skill already cover the workflow? -> load and apply that skill.
   - Is there repeated ambiguity or inconsistency? -> create/update skill after completion.
2. If multiple skills match, choose the minimal set that fully covers the task.
3. If skills conflict, prioritize the most specific skill for the current domain and document the override.
4. After task completion, capture reusable guidance with:
   - trigger conditions
   - required steps
   - failure handling
   - scope boundaries
5. Keep skill docs short and actionable; remove duplicated or stale guidance.

## Examples
```text
Use existing skill:
Task: add DB migration + docs updates.
Decision: use jarvis-project baseline + migration-specific guidance already available.
```

```text
No skill needed:
Task: quick one-line command output formatting fix in isolated file.
Decision: direct handling; no reusable workflow added.
```

```text
Create new skill:
Task type repeats across channels with inconsistent handoff outcomes.
Decision: add session-management skill with packet schema + fallback rules.
```

## Notes
- Reuse before creation.
- If a new skill changes repo-wide defaults, update pinned baseline skills accordingly.
