# Build and Release

## CI Pipeline

From `.github/workflows/ci.yml`:

1. `lint`
2. `typecheck`
3. `test-unit`
4. `test-integration`
5. `coverage`

## Local Equivalent

```bash
make test-gates
```

`make test-gates` runs lint + mypy + unit + integration + coverage check script.

## Build Commands

```bash
make web-build
make api
make worker
```

## Deploy Scripts

- Install services: `deploy/install-systemd.sh`
- Health check: `deploy/healthcheck.sh`
- Rollback: `deploy/rollback.sh <git-ref>`
- Restore DB: `deploy/restore_db.sh <snapshot.db|snapshot.db.gz> [db_path]`

## Release Flow

1. Run `make test-gates`.
2. Run runbook validations (`docs/runbook.md`).
3. Open a PR from `dev` to `master` for promotion.
4. Require at least one non-author human approval on that PR.
5. Execute release checklist (`docs/release-checklist.md`).
6. Capture readiness and backup/restore evidence.

## Automated Releases

Merges to `master` trigger `.github/workflows/release.yml` which uses
[python-semantic-release](https://python-semantic-release.readthedocs.io/) to:

1. Determine the next version from conventional commit messages.
2. Update the version in `pyproject.toml`.
3. Create a Git tag and GitHub Release with auto-generated changelog.

Requires conventional commits (e.g. `feat:`, `fix:`, `chore:`) on the `master` branch.

## Related Docs

- `docs/release-checklist.md`
- `docs/runbook.md`
- `docs/change-safety.md`
- `docs/git-workflow.md`
