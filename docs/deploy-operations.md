# Deploy Operations

Operational guide for `deploy/*` scripts and systemd units.

## Artifacts

- Install script: `deploy/install-systemd.sh`
- Health check: `deploy/healthcheck.sh`
- Rollback: `deploy/rollback.sh`
- DB restore: `deploy/restore_db.sh`
- Units: `deploy/systemd/jarvis-api.service`, `deploy/systemd/jarvis-scheduler.service`, `deploy/systemd/jarvis-worker.service`

## Install / Upgrade

```bash
sudo ./deploy/install-systemd.sh
./deploy/healthcheck.sh
```

Expected result: health script returns success for configured readiness checks.

## Rollback

```bash
sudo ./deploy/rollback.sh <git-ref>
```

Use a known-good ref. Re-run `./deploy/healthcheck.sh` immediately after rollback.

## Restore Database

```bash
RESTORE_READYZ_URL=http://127.0.0.1:8000/readyz \
  sudo ./deploy/restore_db.sh <snapshot.db|snapshot.db.gz> [db_path]
```

Recommended sequence:

1. Stop relevant services.
2. Restore snapshot.
3. Start services.
4. Verify `GET /readyz` and smoke API/WS flows.

## Systemd Notes

- API unit is primary runtime.
- Scheduler/worker units exist for operational compatibility; current local developer flow uses in-process task execution from API runtime.
- Keep service definitions and docs aligned when runtime model changes.

## Operator Checks

- `GET /healthz`
- `GET /readyz`
- `GET /api/v1/system/status`
- Web login + chat smoke test

## Related Docs

- `docs/runbook.md`
- `docs/build-release.md`
- `docs/release-checklist.md`
