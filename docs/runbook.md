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

### Memory Conflict Resolution Operator Flow

1. Fetch open conflicts:
   - `curl -sS -H "Authorization: Bearer <admin-token>" "http://127.0.0.1:8000/api/v1/memory/state/review/conflicts?limit=50"`
2. For each item, capture operator evidence:
   - queue item `id`
   - `uid`
   - `thread_id`
   - `agent_id`
   - `reason`
   - selected resolution rationale
3. Resolve with explicit note:
   - `curl -sS -X POST -H "Authorization: Bearer <admin-token>" -H "Content-Type: application/json" "http://127.0.0.1:8000/api/v1/memory/state/review/<uid>/resolve" -d '{"resolution":"<operator-note>"}'`
4. Verify queue drain for that `uid`:
   - `curl -sS -H "Authorization: Bearer <admin-token>" "http://127.0.0.1:8000/api/v1/memory/state/review/conflicts?limit=50"`
5. If conflict volume spikes unexpectedly, suspend mutation-heavy workflows and run:
   - `uv run jarvis memory review --conflicts --limit 50`
   - `uv run jarvis maintenance run`

### Memory Rollback and Recovery

1. Stop write-heavy jobs:
   - disable maintenance/reconciliation toggles in `.env` (`MAINTENANCE_ENABLED=0`, `MEMORY_TIERS_ENABLED=0`, `MEMORY_IMPORTANCE_ENABLED=0`) and restart API.
2. Preserve forensic state:
   - snapshot DB file before changes (`cp /tmp/jarvis.db /tmp/jarvis.db.pre-memory-rollback`).
3. Restore last known-good DB snapshot when required:
   - `RESTORE_READYZ_URL=http://127.0.0.1:8000/readyz sudo ./deploy/restore_db.sh <snapshot.db|snapshot.db.gz> [db_path]`
4. Re-run migrations and readiness:
   - `make migrate`
   - `curl -fsS http://127.0.0.1:8000/readyz`
5. Re-enable memory toggles in stages:
   - first `MEMORY_REVIEW_QUEUE_ENABLED=1` / `MEMORY_FAILURE_BRIDGE_ENABLED=1`
   - then `MEMORY_TIERS_ENABLED=1` / `MEMORY_IMPORTANCE_ENABLED=1`
   - finally `MAINTENANCE_ENABLED=1`
6. Validate post-rollback memory surfaces:
   - `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v`

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

### WhatsApp Troubleshooting Decision Tree

1. If admin status endpoint fails:
   - check `GET /api/v1/channels/whatsapp/status`
   - if `evolution_api_disabled`, set `EVOLUTION_API_URL` and restart API.
2. If webhook calls return `401`:
   - verify `X-WhatsApp-Secret` equals `WHATSAPP_WEBHOOK_SECRET`.
3. If no inbound messages appear:
   - confirm callback contract from status payload (`callback.enabled`, `callback.configured`, `callback.events`).
   - validate Evolution is sending `messages.upsert`.
4. If inbound is accepted but no message persisted:
   - inspect sender review mode (`WHATSAPP_REVIEW_MODE`, `WHATSAPP_ALLOWED_SENDERS`).
   - check review queue APIs and resolve pending sender decisions.
5. If media/voice messages are degraded:
   - inspect latest `channel.inbound.degraded` reasons and map to config:
     - `media_host_denied` -> `WHATSAPP_MEDIA_ALLOWED_HOSTS`
     - `media_mime_denied` -> `WHATSAPP_MEDIA_ALLOWED_MIME_PREFIXES`
     - `media_size_exceeded` -> `WHATSAPP_MEDIA_MAX_BYTES`
     - `voice_transcription_timeout` -> `WHATSAPP_VOICE_TRANSCRIBE_TIMEOUT_SECONDS`
     - `voice_transcription_backend_unavailable` -> backend/runtime setup
6. If pairing appears stuck:
   - recreate/disconnect instance from admin channel APIs
   - regenerate QR / pairing code
   - confirm sidecar reachability and credentials (`EVOLUTION_API_URL`, `EVOLUTION_API_KEY`)

## Outage-Class Diagnostics Evidence

Deterministic outage classes used in doctor/CLI JSON error reporting:
- `dns_resolution`
- `timeout`
- `network_unreachable`
- `provider_unavailable`

Targeted evidence commands:
- `uv run pytest tests/unit/test_cli_checks.py -q`
- `uv run pytest tests/unit/test_cli_chat.py -q`
- `uv run jarvis doctor --json`

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

### Operator-Owned Rotation Checklist (External Dependency)

Repo-side automation is complete; execution remains operator-owned. Capture all artifacts below when rotation is performed:

1. Rotate and record timestamped evidence for:
   - `GOOGLE_OAUTH_CLIENT_SECRET`
   - `GOOGLE_OAUTH_REFRESH_TOKEN`
   - `GITHUB_TOKEN`
   - `GITHUB_WEBHOOK_SECRET`
   - `WHATSAPP_WEBHOOK_SECRET`
2. Save evidence artifacts (names required):
   - `docs/reports/ops/credential-rotation-YYYYMMDD.md`
   - `docs/reports/ops/credential-rotation-YYYYMMDD-env-diff.txt`
   - `docs/reports/ops/credential-rotation-YYYYMMDD-secret-scan.txt`
3. Required command transcript in evidence:
   - `make secret-scan`
   - `uv run jarvis doctor --json`
   - `curl -fsS http://127.0.0.1:8000/readyz`
4. Attach redacted proof:
   - old credential values are not included
   - only key names, rotation timestamps, and success/health outputs are retained.

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
