# Runbook

## Normal Start

1. `make dev`
2. `make migrate`
3. `make api`
4. `make worker`
5. Check `GET /healthz` and `GET /readyz`
6. If setup is incomplete, run `uv run jarvis doctor --fix`

## Web UI Operations

1. Start web dev server: `make web-dev`
2. Verify login page at `http://localhost:5173/login`
3. Verify chat route `/chat` and admin routes `/admin/*`
4. Validate API CORS origins (`WEB_CORS_ORIGINS`) if browser requests fail

## Controlled Restart

1. Trigger `/restart` as admin.
2. `system_state.restarting=1` is set.
3. System drains active/reserved/scheduled Celery work until timeout.
4. Remaining tasks are revoked after timeout.
5. Restart flag is cleared and `/readyz` is validated.

## Lockdown

1. `system_state.lockdown` auto-triggers on repeated `/readyz` or rollback bursts, or can be set manually.
2. Verify protected tools are denied by policy engine.
3. Use `/unlock <code>` before TTL expiration to clear lockdown.
4. Rotate unlock code with `jarvis.tasks.system.rotate_unlock_code`.
5. Manual lockdown API is admin-only: `POST /api/v1/system/lockdown`.

## Auth and RBAC Ops

1. Web sessions carry role (`user` or `admin`).
2. Admin-only APIs include lockdown, permissions, and self-update approval surfaces.
3. Non-admin users are ownership-scoped to their own resources.
4. Validate boundaries: `uv run pytest tests/integration/test_authorization.py -v`.

## Scheduler Check

1. Insert schedule with `cron_expr='@every:60'`.
2. Trigger `jarvis.tasks.scheduler.scheduler_tick`.
3. Confirm one `schedule.trigger` event and no duplicate dispatch for same `due_at`.
4. Use `/status` for scheduler backlog fields.

## Self-Update Check

1. Run `self_update_propose -> self_update_validate -> self_update_test -> self_update_apply`.
2. Confirm state transitions in `${SELFUPDATE_PATCH_DIR}/<trace_id>/state.json`.
3. Confirm validate passed `git apply --check`.
4. If readiness fails, run rollback and confirm marker state.

## Deploy and Rollback

1. Install units: `sudo ./deploy/install-systemd.sh`
2. Validate: `./deploy/healthcheck.sh`
3. Rollback: `sudo ./deploy/rollback.sh <git-ref>`
4. Restore DB: `RESTORE_READYZ_URL=http://127.0.0.1:8000/readyz sudo ./deploy/restore_db.sh <snapshot.db|snapshot.db.gz> [db_path]`

## Release Evidence

1. Use `docs/release-checklist.md` for every release candidate.
2. Record readiness soak and backup/restore drill evidence.

## Related Docs

- `docs/build-release.md`
- `docs/change-safety.md`
- `docs/testing.md`
- `docs/local-development.md`
