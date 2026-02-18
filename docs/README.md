# Documentation Index

Canonical navigation for repository documentation.

## Start Here

### New Developer

1. `docs/getting-started.md`
2. `docs/local-development.md`
3. `docs/configuration.md`
4. `docs/testing.md`
5. `docs/codebase-tour.md`

### Operator / On-call

1. `docs/runbook.md`
2. `docs/deploy-operations.md`
3. `docs/change-safety.md`
4. `docs/release-checklist.md`

### Release Owner

1. `docs/build-release.md`
2. `docs/release-checklist.md`
3. `docs/github-pr-automation.md`
4. `docs/git-workflow.md`

## Interface References

- API reference (generated): `docs/api-reference.md`
- API workflows: `docs/api-usage-guide.md`
- CLI reference: `docs/cli-reference.md`
- Web admin/chat behavior: `docs/web-admin-guide.md`
- Deploy and systemd ops: `docs/deploy-operations.md`

## Architecture and Safety

- `docs/architecture.md`
- `docs/codebase-tour.md`
- `docs/change-safety.md`
- `docs/testing.md`

## Prompt and Agent Maintenance

- Prompt library: `docs/prompts/README.md`
- Docs maintenance prompt: `docs/DOCS_AGENT_PROMPT.md`
- Feature build prompt: `docs/FEATURE_BUILDER_PROMPT.md`

## Maintenance Commands

```bash
make docs-generate
make docs-check
```

`make docs-generate` refreshes `docs/api-reference.md` from live FastAPI OpenAPI.
`make docs-check` validates local markdown links, docs command drift, and API reference sync.
