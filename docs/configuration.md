# Configuration

Source of truth: `src/jarvis/config.py`.

## Usage

1. Copy `.env.example` to `.env`.
2. Set environment values.
3. Restart API after changes (`make api` in local dev).

## Environment Variables

### Core Runtime

| Variable | Type | Default | Description |
|---|---|---|---|
| `APP_ENV` | str | `dev` | Runtime environment (`dev`/`prod`). |
| `APP_DB` | str | `/tmp/jarvis.db` | SQLite DB path. |
| `BROKER_URL` | str | `amqp://guest:guest@localhost:5672//` | Celery broker URL. |
| `RESULT_BACKEND` | str | `rpc://` | Celery result backend. |
| `LOG_LEVEL` | str | `INFO` | Logging level. |
| `TRACE_SAMPLE_RATE` | float | `1.0` | Event trace sampling fraction. |

### Prompt and Compaction

| Variable | Type | Default | Description |
|---|---|---|---|
| `COMPACTION_EVERY_N_EVENTS` | int | `25` | Trigger compaction every N events. |
| `COMPACTION_INTERVAL_SECONDS` | int | `600` | Min interval between compactions. |
| `PROMPT_BUDGET_GEMINI_TOKENS` | int | `200000` | Prompt budget for Gemini lane. |
| `PROMPT_BUDGET_SGLANG_TOKENS` | int | `110000` | Prompt budget for SGLang lane. |

### Lockdown and Queue Controls

| Variable | Type | Default | Description |
|---|---|---|---|
| `LOCKDOWN_DEFAULT` | int | `0` | Initial lockdown flag. |
| `LOCKDOWN_READYZ_FAIL_THRESHOLD` | int | `3` | Consecutive `/readyz` fails before lockdown. |
| `LOCKDOWN_ROLLBACK_THRESHOLD` | int | `2` | Rollback count threshold for lockdown. |
| `LOCKDOWN_ROLLBACK_WINDOW_MINUTES` | int | `30` | Rollback window in minutes. |
| `LOCKDOWN_EXEC_HOST_FAIL_THRESHOLD` | int | `5` | Exec-host failure threshold. |
| `LOCKDOWN_EXEC_HOST_FAIL_WINDOW_MINUTES` | int | `10` | Exec-host failure window. |
| `QUEUE_THRESHOLD_AGENT_PRIORITY` | int | `200` | Queue warning threshold. |
| `QUEUE_THRESHOLD_AGENT_DEFAULT` | int | `500` | Queue warning threshold. |
| `QUEUE_THRESHOLD_TOOLS_IO` | int | `500` | Queue warning threshold. |
| `QUEUE_THRESHOLD_LOCAL_LLM` | int | `10` | Queue warning threshold. |

### Self-Update

| Variable | Type | Default | Description |
|---|---|---|---|
| `SELFUPDATE_AUTO_APPLY_DEV` | int | `1` | Auto-apply in dev. |
| `SELFUPDATE_AUTO_APPLY_PROD` | int | `0` | Auto-apply in prod. |
| `SELFUPDATE_PATCH_DIR` | str | `/var/lib/agent/patches` | Patch state directory. |
| `SELFUPDATE_SMOKE_PROFILE` | str | `dev` | Smoke profile (`dev`/`prod`). |
| `SELFUPDATE_READYZ_URL` | str | `` | Readiness URL for apply watchdog. |
| `SELFUPDATE_READYZ_ATTEMPTS` | int | `3` | Readiness retry attempts. |

### Scheduler, Restart, and RabbitMQ Mgmt

| Variable | Type | Default | Description |
|---|---|---|---|
| `SCHEDULER_MAX_CATCHUP` | int | `10` | Global catch-up cap per schedule tick. |
| `RABBITMQ_MGMT_URL` | str | `` | Optional RabbitMQ mgmt endpoint. |
| `RABBITMQ_MGMT_USER` | str | `` | RabbitMQ mgmt username. |
| `RABBITMQ_MGMT_PASSWORD` | str | `` | RabbitMQ mgmt password. |
| `RESTART_DRAIN_TIMEOUT_SECONDS` | int | `20` | Drain timeout for controlled restart. |
| `RESTART_DRAIN_POLL_SECONDS` | int | `2` | Drain poll interval. |
| `RESTART_COMMAND` | str | `` | Host restart command. |

### Channel/Auth Providers

| Variable | Type | Default | Description |
|---|---|---|---|
| `WHATSAPP_VERIFY_TOKEN` | str | `dev-verify-token` | WhatsApp webhook verification token. |
| `WHATSAPP_ACCESS_TOKEN` | str | `` | WhatsApp API access token. |
| `WHATSAPP_PHONE_NUMBER_ID` | str | `` | WhatsApp phone number ID. |
| `WHATSAPP_INSTANCE` | str | `personal` | Evolution instance name. |
| `WHATSAPP_AUTO_CREATE_ON_STARTUP` | int | `0` | Auto-create Evolution instance on API startup. |
| `WHATSAPP_WEBHOOK_SECRET` | str | `` | Shared secret header required by WhatsApp webhook route when set. |
| `EVOLUTION_API_URL` | str | `` | Evolution API base URL for Baileys sidecar. |
| `EVOLUTION_API_KEY` | str | `` | Evolution API key header value. |
| `GOOGLE_OAUTH_CLIENT_ID` | str | `` | Google OAuth client ID. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | str | `` | Google OAuth client secret. |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | str | `` | OAuth refresh token. |
| `PRIMARY_PROVIDER` | str | `gemini` | Primary chat provider (`gemini` or `sglang`). |
| `GEMINI_MODEL` | str | `gemini-2.5-flash` | Default Gemini model. |
| `GEMINI_CODE_ASSIST_PLAN_TIER` | str | `free` | Gemini Code Assist tier (`free`, `pro`, `ultra`, `standard`, `enterprise`). |
| `GEMINI_CODE_ASSIST_REQUESTS_PER_MINUTE` | int | `0` | Local cap for Gemini requests per minute (`0` uses tier default). |
| `GEMINI_CODE_ASSIST_REQUESTS_PER_DAY` | int | `0` | Local cap for Gemini requests per day (`0` uses tier default). |
| `GEMINI_CLI_TIMEOUT_SECONDS` | int | `120` | Gemini CLI timeout. |
| `GEMINI_QUOTA_COOLDOWN_DEFAULT_SECONDS` | int | `60` | Fallback cooldown after quota errors when reset time is not provided. |
| `SGLANG_BASE_URL` | str | `http://localhost:30000/v1` | SGLang endpoint. |
| `SGLANG_MODEL` | str | `openai/gpt-oss-120b` | SGLang model name. |
| `SGLANG_TIMEOUT_SECONDS` | int | `600` | SGLang timeout. |

### Memory and Search

| Variable | Type | Default | Description |
|---|---|---|---|
| `OLLAMA_BASE_URL` | str | `http://localhost:11434` | Ollama endpoint. |
| `OLLAMA_EMBED_MODEL` | str | `nomic-embed-text` | Embedding model. |
| `MEMORY_EMBED_DIMS` | int | `768` | Embedding dimensions. |
| `SQLITE_VEC_EXTENSION_PATH` | str | `` | Optional sqlite-vec extension path. |
| `SEARXNG_BASE_URL` | str | `http://localhost:8080` | SearXNG base URL. |
| `SEARXNG_API_KEY` | str | `` | SearXNG API key. |
| `SEARXNG_API_KEY_HEADER` | str | `X-API-Key` | SearXNG API key header name. |
| `WEB_SEARCH_USER_AGENT` | str | `Mozilla/5.0 (compatible; Jarvis/1.0; +https://localhost)` | Outbound user agent for web search requests. |

### Admin and Backup

| Variable | Type | Default | Description |
|---|---|---|---|
| `ADMIN_WHATSAPP_IDS` | str | `` | Comma-separated admin external IDs. |
| `ADMIN_UNLOCK_CODE_PATH` | str | `/var/lib/agent/admin_unlock_code` | Lockdown unlock code path. |
| `ADMIN_UNLOCK_CODE_TTL_MINUTES` | int | `10` | Unlock code TTL. |
| `BACKUP_S3_ENDPOINT` | str | `` | S3-compatible endpoint. |
| `BACKUP_S3_BUCKET` | str | `` | Backup bucket name. |
| `BACKUP_S3_REGION` | str | `auto` | Backup region. |
| `BACKUP_S3_ACCESS_KEY_ID` | str | `` | Backup access key. |
| `BACKUP_S3_SECRET_ACCESS_KEY` | str | `` | Backup secret key. |
| `BACKUP_LOCAL_DIR` | str | `/tmp/jarvis_backups` | Local backup path. |
| `BACKUP_ENCRYPT_REMOTE` | int | `1` | Encrypt remote backup payloads. |
| `BACKUP_RETENTION_HOURLY` | int | `24` | Hourly retention count. |
| `BACKUP_RETENTION_DAILY` | int | `14` | Daily retention count. |
| `BACKUP_RETENTION_WEEKLY` | int | `8` | Weekly retention count. |
| `PAGERDUTY_ROUTING_KEY` | str | `` | PagerDuty events routing key. |
| `ALERT_SLACK_WEBHOOK_URL` | str | `` | Optional Slack mirror webhook. |

### GitHub Automation

| Variable | Type | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | str | `` | GitHub App installation token or PAT for API calls. |
| `GITHUB_WEBHOOK_SECRET` | str | `` | Secret used to verify `X-Hub-Signature-256`. |
| `GITHUB_API_BASE_URL` | str | `https://api.github.com` | GitHub API base URL. |
| `GITHUB_REPO_ALLOWLIST` | str | `` | Optional CSV allowlist (supports globs, e.g. `my-org/*`). |
| `GITHUB_BOT_LOGIN` | str | `jarvis` | Bot login used for `@mention` trigger matching and self-reply guard. |
| `GITHUB_PR_SUMMARY_ENABLED` | int | `0` | Enable PR summary comments for `pull_request` webhook events. |
| `GITHUB_ISSUE_SYNC_ENABLED` | int | `0` | Enable bug/feature request sync from Jarvis API into GitHub Issues. |
| `GITHUB_ISSUE_SYNC_REPO` | str | `` | Destination repo in `owner/repo` format for issue sync. |
| `GITHUB_ISSUE_LABELS_BUG` | str | `jarvis,bug` | CSV labels applied to synced bug issues. |
| `GITHUB_ISSUE_LABELS_FEATURE` | str | `jarvis,feature-request` | CSV labels applied to synced feature request issues. |

### Local Maintenance Loop

| Variable | Type | Default | Description |
|---|---|---|---|
| `MAINTENANCE_ENABLED` | int | `0` | Enable local maintenance task scheduling. |
| `MAINTENANCE_HEARTBEAT_INTERVAL_SECONDS` | int | `300` | Lightweight maintenance heartbeat interval (`0` disables). |
| `MAINTENANCE_INTERVAL_SECONDS` | int | `0` | Beat interval for maintenance task (`0` disables schedule). |
| `MAINTENANCE_COMMANDS` | str | `make lint\nmake typecheck` | Commands to run (newline-separated, `\n` supported). |
| `MAINTENANCE_TIMEOUT_SECONDS` | int | `1800` | Per-command timeout in seconds. |
| `MAINTENANCE_CREATE_BUGS` | int | `1` | Create bug reports on command failures. |
| `MAINTENANCE_WORKDIR` | str | `` | Optional override working directory for maintenance commands. |

### API and Web UI Security

| Variable | Type | Default | Description |
|---|---|---|---|
| `BIND_HOST` | str | `127.0.0.1` | API bind host (loopback default). |
| `BIND_PORT` | int | `8000` | API bind port. |
| `RATE_LIMIT_MESSAGES_PER_MINUTE` | int | `30` | Message API rate limit. |
| `RATE_LIMIT_WEBHOOKS_PER_MINUTE` | int | `60` | Webhook rate limit. |
| `WEB_AUTH_TOKEN_TTL_HOURS` | int | `720` | Session token TTL. |
| `WEB_CORS_ORIGINS` | str | `http://localhost:5173` | CSV list of allowed origins. |
| `WEB_AUTH_SETUP_PASSWORD` | str | `` | Initial web auth bootstrap password. |

### Exec Host Sandboxing

| Variable | Type | Default | Description |
|---|---|---|---|
| `EXEC_HOST_TIMEOUT_MAX_SECONDS` | int | `120` | Max command runtime. |
| `EXEC_HOST_LOG_DIR` | str | `/var/lib/agent/exec` | Exec-host log path. |
| `EXEC_HOST_ENV_ALLOWLIST` | str | `PATH,HOME,LANG,LC_ALL,TZ` | Allowed env pass-through list. |
| `EXEC_HOST_ALLOWED_CWD_PREFIXES` | str | `/srv/agent-framework,/tmp,/home/justin/jarvis` | Allowed working-directory prefixes. |
| `EXEC_HOST_SANDBOX` | str | `none` | Sandbox mode selector. |
| `EXEC_HOST_MAX_OUTPUT_BYTES` | int | `1000000` | Output cap per command. |
| `EXEC_HOST_MAX_MEMORY_MB` | int | `512` | Memory cap. |
| `EXEC_HOST_MAX_CPU_SECONDS` | int | `120` | CPU time cap. |

## Production Validation Rules

`validate_settings_for_env()` enforces additional checks in `APP_ENV=prod`:

- Required non-empty fields include DB/broker/provider/auth/admin/backup/PagerDuty values.
- `WHATSAPP_VERIFY_TOKEN` cannot remain default dev token.
- If `GITHUB_PR_SUMMARY_ENABLED=1`, `GITHUB_TOKEN` and `GITHUB_WEBHOOK_SECRET` are required.
- If `GITHUB_ISSUE_SYNC_ENABLED=1`, `GITHUB_TOKEN` and `GITHUB_ISSUE_SYNC_REPO` are required.
- `APP_DB` must be an absolute path.
- If `BIND_HOST=0.0.0.0` in prod, runtime emits a security warning.

## Related Docs

- `docs/README.md`
- `.env.example`
- `docs/local-development.md`
- `docs/change-safety.md`
- `docs/deploy-operations.md`
