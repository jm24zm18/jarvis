---
slug: jarvis-project
pinned: true
---

# Jarvis Project

## Purpose
Provide shared operational knowledge for Jarvis agents working in this repository.

## Key Facts
- Python package code is under `src/jarvis`.
- Agent bundles and runtime identity files live in `agents/<agent_id>/`.
- SQL migrations live in `src/jarvis/db/migrations/` and run in filename order.
- Unit tests live under `tests/unit/`.
- Runtime prompt assembly is implemented in `src/jarvis/orchestrator/step.py` and `src/jarvis/orchestrator/prompt_builder.py`.
- Tool registration for agent execution is in `src/jarvis/tasks/agent.py`.
- GitHub PR automation is implemented in `src/jarvis/routes/api/webhooks.py` and `src/jarvis/tasks/github.py`.
- PR chat trigger commands:
  - `/jarvis review <question>`
  - `/jarvis summarize <question>`
  - `/jarvis risks <question>`
  - `/jarvis tests <question>`
  - `/jarvis help`
  - `/jarvis <question>` or `@jarvis <question>` (general mode)

## Usage
1. Before coding, inspect relevant module + tests and follow existing patterns.
2. For schema changes, add a new numbered migration and tests.
3. For agent capabilities, update identity tool lists and registry wiring together.
4. Run targeted tests first, then broader test suites.
5. After structural changes, refresh this skill with updated paths and behavior.
6. For GitHub automation changes, update `docs/github-pr-automation.md` and env docs together.

## Examples
```bash
make migrate
make test
uv run pytest tests/unit/test_orchestrator_step.py
```

```bash
uv run pytest tests/unit/test_agent_seed.py tests/unit/test_agent_loader.py
```

## Notes
Keep prompt context compact: prefer short, high-signal skills over long narrative docs.
