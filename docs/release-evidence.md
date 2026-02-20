# Release Checklist — Completed

## Metadata
- Date (UTC): 2026-02-20T00:09:00Z
- Release candidate (git ref): `bef2e0fd` (branch: dev)
- Operator: Antigravity AI + Justin
- Environment: local (~/jarvis2)

## Prerequisites
- [x] `make test-gates` passed on candidate commit.
  - Ruff: All checks passed
  - Mypy: No issues in 133 source files
  - Unit tests: all pass (1 skipped)
  - Integration tests: all pass
  - Coverage: 86.17% (threshold 80%)
- [x] Staging deploy succeeded (API started via `uvicorn`).
- [x] `GET /healthz` returns `{"ok": true}`.
- [x] `GET /readyz` returns `{"ok":true,"db":true,"providers":{"primary":true,"fallback":true}}`.

## Security and RBAC verification
- [x] Non-admin user cannot read/update other users' threads.
- [x] Non-admin user cannot subscribe to other users' threads via WebSocket.
- [x] Non-admin user cannot call admin-only APIs:
  - `POST /api/v1/system/lockdown` — 403 ✓
  - `/api/v1/permissions/*` — 403 ✓
  - `/api/v1/selfupdate/patches/*/approve` — 403 ✓
  - `POST /api/v1/stories/run` — 403 ✓
  - `POST /api/v1/system/reset-db` — 403 ✓
  - `POST /api/v1/system/reload-agents` — 403 ✓
  - `GET /api/v1/system/repo-index` — 403 ✓
  - `GET /api/v1/selfupdate/patches` — 403 ✓
  - WhatsApp channel management (7 endpoints) — 403 ✓
  - Governance fitness/SLO/decision-timeline — 403 ✓
  - Memory maintenance — 403 ✓
- [x] Admin user can execute admin-only APIs.
- [x] `tests/integration/test_authorization.py` passes: **24/24** ✓

## 24h Readiness Soak
- Start: to be started via `deploy/soak-monitor.sh`
- Command: `nohup deploy/soak-monitor.sh 60 24 &`
- Probes `/readyz` every 60 seconds for 24 hours
- Results logged to `data/soak_log.txt`

> **Note**: The soak monitor script has been created but requires a 24h window
> to complete. The API has been verified healthy at all check points during
> this release operations session.

## Backup and Restore Drill
### Backup
- [x] Triggered `create_backup()` task.
- [x] Snapshot file exists: `/tmp/jarvis_backups/backup_20260220T001109Z.db`
- [x] Compressed: `/tmp/jarvis_backups/backup_20260220T001109Z.db.gz`
- [x] Retention applied: 2 retained, 21 pruned
- [ ] Remote upload: not configured (S3 endpoint not set)

### Restore (.db)
- Restore command: `deploy/restore_db.sh backup_20260220T001109Z.db /tmp/jarvis_restore_drill.db`
- [x] Restore completed without error.
- [x] Post-restore integrity check: `ok`
- [x] Table count: 106 tables
- [x] Previous DB backed up at `/tmp/jarvis_restore_drill.db.pre_restore.20260220T001127Z`

### Restore (.db.gz)
- Restore command: `deploy/restore_db.sh backup_20260220T001109Z.db.gz /tmp/jarvis_restore_drill_gz.db`
- [x] Compressed restore completed without error.
- [x] Post-restore integrity check: `ok`
- [x] Table count: 106 tables

### Post-Restore Health
- [x] `GET /readyz` healthy after restore drill: `{"ok":true}`

## Exit Decision
- [x] All release criteria satisfied (except 24h soak duration).
- [ ] Start soak monitor, then approve for production promotion.

## Next Steps
1. Start soak: `nohup deploy/soak-monitor.sh 60 24 &`
2. After 24h, check `data/soak_log.txt` for PASS/FAIL
3. Set secrets in `deploy/.env.prod` (TELEGRAM_BOT_TOKEN, WEB_AUTH_SETUP_PASSWORD)
4. Deploy: `sudo deploy/install-systemd.sh`
