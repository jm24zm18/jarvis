# Release Checklist

Use this checklist for each staging->production release candidate.

## Metadata
- Date (UTC):
- Release candidate (git ref):
- Operator:
- Environment:

## Prerequisites
- [ ] `make test-gates` passed on candidate commit.
- [ ] `make docs-check` passed on candidate commit.
- [ ] Staging deploy succeeded (`deploy/install-systemd.sh` or equivalent process).
- [ ] `GET /healthz` returns `{"ok": true}`.
- [ ] CI workflow (`.github/workflows/ci.yml`) is green for:
  - lint
  - typecheck
  - test-unit
  - test-integration
  - coverage

## Security and RBAC verification
- [ ] Non-admin user cannot read/update other users' threads.
- [ ] Non-admin user cannot subscribe to other users' threads via WebSocket.
- [ ] Non-admin user cannot call admin-only APIs:
  - `POST /api/v1/system/lockdown`
  - `/api/v1/permissions/*`
  - `/api/v1/selfupdate/patches/*/approve`
- [ ] Admin user can execute admin-only APIs.
- [ ] `tests/integration/test_authorization.py` passes in CI and locally.

## 24h Readiness Soak
- Start time (UTC):
- End time (UTC):
- Sampling command:
  - `curl -fsS http://127.0.0.1:8000/readyz`
- [ ] `/readyz` observed healthy for continuous 24 hours.
- [ ] Any transient failures are documented below.

Notes:
- Incident timestamps (UTC):
- Root cause / remediation:

## Backup and Restore Drill
### Backup
- [ ] Trigger backup task (`jarvis.tasks.backup.create_backup`) or scheduled backup.
- [ ] Confirm snapshot file exists in local backup dir.
- [ ] Confirm remote upload exists in S3-compatible bucket (if enabled).

Backup evidence:
- Local snapshot path:
- Remote object key:

### Restore
- Restore command used:
  - `RESTORE_READYZ_URL=http://127.0.0.1:8000/readyz sudo ./deploy/restore_db.sh <snapshot.db|snapshot.db.gz> [db_path]`
- [ ] Restore completed without error.
- [ ] Post-restore integrity check result is `ok`.
- [ ] `GET /readyz` healthy after restore.
- [ ] Smoke checks passed after restore.

Restore evidence:
- Restored DB path:
- Integrity output:
- Smoke checks run:

## Exit Decision
- [ ] Release criteria satisfied.
- [ ] Approved for production promotion.

Approver:
- Name:
- Timestamp (UTC):

## Related Docs

- `docs/build-release.md`
- `docs/deploy-operations.md`
- `docs/runbook.md`
- `docs/change-safety.md`
