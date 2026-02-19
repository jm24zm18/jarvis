# Runbook

## Normal Start

1. `make dev`
2. `make migrate`
3. `make api`
4. Check `GET /healthz` and `GET /readyz`
5. If setup is incomplete, run `uv run jarvis doctor --fix`

## Local Maintenance Loop

1. Set `MAINTENANCE_ENABLED=1` and `MAINTENANCE_INTERVAL_SECONDS>0` in `.env`.
   - `MAINTENANCE_HEARTBEAT_INTERVAL_SECONDS` provides default cron heartbeat.
2. Configure commands via `MAINTENANCE_COMMANDS`.
3. Periodic maintenance runs in-process while API is running.
4. Trigger manually with `uv run jarvis maintenance run`.
5. Review generated failures in `/api/v1/bugs` when enabled.
6. CLI controls:
   - `uv run jarvis maintenance status --json`
   - `uv run jarvis maintenance run`
   - `uv run jarvis maintenance enqueue`

## GitHub Integration Ops

1. PR automation:
   - Enable `GITHUB_PR_SUMMARY_ENABLED=1`.
   - Configure webhook to `POST /api/v1/webhooks/github`.
   - Ensure API is running for task processing.
2. Bug/feature sync to GitHub Issues:
   - Enable `GITHUB_ISSUE_SYNC_ENABLED=1`.
   - Set `GITHUB_ISSUE_SYNC_REPO=owner/repo`.
   - Submit with `"sync_to_github": true` on create.
3. Validate sync results:
   - `GET /api/v1/bugs` should show `github_issue_number`, `github_issue_url`, `github_synced_at`.
   - If sync fails, inspect `github_sync_error`.

## Web UI Operations

1. Start web dev server: `make web-dev`
2. Verify login page at `http://localhost:5173/login`
3. Verify chat route `/chat` and admin routes `/admin/*`
4. Validate API CORS origins (`WEB_CORS_ORIGINS`) if browser requests fail

### Web Install Recovery

1. Run `make web-install` (uses resilient wrapper + retry path).
2. If it fails, inspect `/tmp/jarvis-web-install.log`.
3. If npm emitted a debug log path, inspect that file as well.
4. Apply targeted remediation:
   - `npm cache clean --force`
   - `cd web && npm install --cache /tmp/npm-cache --prefer-offline=false`
   - retry in a non-restricted shell if network/DNS egress is blocked.

## Controlled Restart

1. Trigger chat slash command `/restart` as admin (for example: `uv run jarvis ask "/restart"`).
2. `system_state.restarting=1` is set.
3. System drains in-flight in-process tasks until timeout.
4. Restart command is executed.
5. Restart flag is cleared and `/readyz` is validated.

## Lockdown

1. `system_state.lockdown` auto-triggers on repeated `/readyz` or rollback bursts, or can be set manually.
2. Verify protected tools are denied by policy engine.
3. Use chat slash command `/unlock <code>` before TTL expiration to clear lockdown.
4. Rotate unlock code with `jarvis.tasks.system.rotate_unlock_code`.
5. Manual lockdown API is admin-only: `POST /api/v1/system/lockdown`.

## Auth and RBAC Ops

1. Web sessions carry role (`user` or `admin`).
2. Admin-only APIs include lockdown, permissions, and self-update approval surfaces.
3. Non-admin users are ownership-scoped to their own resources.
4. Validate boundaries: `uv run pytest tests/integration/test_authorization.py -v`.

## Memory Governance Ops

1. Open `/admin/memory` to review:
   - conflict review queue
   - tier/archive stats
   - failure lookup
   - graph traversal preview
   - consistency reports (thread/time filters)
2. API equivalents:
   - `GET /api/v1/memory/state/review/conflicts`
   - `POST /api/v1/memory/state/review/{uid}/resolve`
   - `GET /api/v1/memory/state/stats`
   - `GET /api/v1/memory/state/failures`
   - `GET /api/v1/memory/state/graph/{uid}`
   - `GET /api/v1/memory/state/consistency/report?thread_id=...&from_ts=...&to_ts=...`
3. Monitor `/metrics` memory KPI fields:
   - `memory_items_count`
   - `memory_avg_tokens_saved`
   - `memory_reconciliation_rate`
   - `memory_hallucination_incidents`

## WhatsApp Media and Voice Ops

1. Confirm media safety config:
   - `WHATSAPP_MEDIA_DIR` points to a writable runtime directory.
   - `WHATSAPP_MEDIA_MAX_BYTES` matches expected inbound limits.
   - `WHATSAPP_MEDIA_ALLOWED_MIME_PREFIXES` and `WHATSAPP_MEDIA_ALLOWED_HOSTS` match policy.
2. For voice notes, verify:
   - `WHATSAPP_VOICE_TRANSCRIBE_ENABLED=1`
   - `WHATSAPP_VOICE_TRANSCRIBE_BACKEND` set to either `stub` (smoke/dev) or `faster_whisper` (production local transcription)
   - when using `faster_whisper`, set:
     - `WHATSAPP_VOICE_MODEL`
     - `WHATSAPP_VOICE_DEVICE`
     - `WHATSAPP_VOICE_COMPUTE_TYPE`
     - optional `WHATSAPP_VOICE_LANGUAGE`
3. If inbound media is blocked, inspect latest `channel.inbound.degraded` events for reason codes:
   - `media_url_invalid`
   - `media_host_denied`
   - `media_mime_denied`
   - `media_size_exceeded`
   - `media_path_unsafe`
   - `media_download_failed`
   - `voice_transcription_backend_unavailable`
   - `voice_transcription_failed`
   - `voice_transcription_timeout`
4. Media rows are persisted in `whatsapp_media`; verify linkage by thread/message when debugging ingestion.

## Secret Rotation and Scan

1. Rotate compromised or leaked local credentials at the provider:
   - Google OAuth client secret / refresh token
   - GitHub token / webhook secret
   - Any third-party API key in `.env`
2. Update local `.env` and token cache files with new values.
3. Run local verification scans:
   - `make secret-scan`
4. Confirm no findings and restart API/web services.
5. Re-run critical auth checks (`/api/v1/auth/login`, `/api/v1/auth/me`, WebSocket `/ws`).

## Scheduler Check

1. Insert schedule with `cron_expr='@every:60'`.
2. Trigger `jarvis.tasks.scheduler.scheduler_tick`.
3. Confirm one `schedule.trigger` event and no duplicate dispatch for same `due_at`.
4. Use chat slash command `/status` for scheduler backlog fields.
5. HTTP equivalent: `GET /api/v1/system/status`.

## Local Setup Smoke Validation

1. Run `make setup-smoke`.
2. This validates:
   - local toolchain availability (`python3`, `uv`, `docker`, `node`, `npm`)
   - host-port preflight for dependency services
   - DB migrations
   - API import/bootstrap sanity
   - web dependency bootstrap
3. If dependency ports are intentionally occupied by already-running local services,
   run `make setup-smoke-running` (skips dev port preflight only).
4. If it fails, fix the failing step and rerun until it passes.

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
- `docs/deploy-operations.md`
- `docs/api-usage-guide.md`
- `docs/change-safety.md`
- `docs/testing.md`
- `docs/local-development.md`
