# Testing

## Test Layout

- Unit tests: `tests/unit/` (30 files currently)
- Integration tests: `tests/integration/` (13 files currently)
- Shared fixtures: `tests/conftest.py`

## Core Fixture Behavior (`tests/conftest.py`)

- Creates a temp SQLite DB (`APP_DB`) per test context.
- Sets temp self-update patch dir.
- Runs all migrations before tests execute.
- Registers/reset WhatsApp channel adapter around each test.

## Running Tests

```bash
make test
uv run pytest tests/unit -v
uv run pytest tests/integration -v
uv run pytest tests/unit/test_foo.py -v
uv run pytest tests/unit/test_foo.py::test_bar -v
```

## CI Test Pipeline

CI workflow `.github/workflows/ci.yml` runs:

1. `lint`
2. `typecheck`
3. `test-unit`
4. `test-integration`
5. `coverage` (with Codecov upload + diff-cover on PRs)
6. `validate-agents` — validates all agent bundles under `agents/`
7. `test-migrations` — applies all SQL migrations to a fresh SQLite DB
8. `security` — bandit + pip-audit + TruffleHog
9. `web-lint` / `web-typecheck` / `web-test` — frontend quality gates

## Coverage Gates

`make test-gates` enforces coverage checks for:

- `jarvis.orchestrator`
- `jarvis.policy`
- `jarvis.tools.runtime`

via `scripts/check_coverage.py` and `/tmp/jarvis_coverage.json`.

## Additional Gates

`make test-gates` also runs:

- `scripts/validate_agents.py` — checks all agent bundles have required files, valid frontmatter, and known tools
- `scripts/test_migrations.py` — applies all migrations to a fresh DB and runs integrity check

## Writing New Tests

- Use unit tests for pure logic and policy branching.
- Use integration tests for route auth/ownership boundaries and DB/task behavior.
- Add both unit and integration coverage for behavior changes crossing runtime boundaries.

## Agent Notes

- Default pytest timeout is `30s` from `pyproject.toml`.
- Keep tests deterministic; avoid hidden dependencies on host services unless explicitly integration-scoped.

## Related Docs

- `docs/change-safety.md`
- `docs/build-release.md`
- `docs/local-development.md`
