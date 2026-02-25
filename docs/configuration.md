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
| `LOG_LEVEL` | str | `INFO` | Logging level. |
| `TRACE_SAMPLE_RATE` | float | `1.0` | Event trace sampling fraction. |

### Prompt and Compaction

| Variable | Type | Default | Description |
|---|---|---|---|
| `COMPACTION_EVERY_N_EVENTS` | int | `25` | Trigger compaction every N events. |
| `COMPACTION_INTERVAL_SECONDS` | int | `600` | Min interval between compactions. |
| `PROMPT_BUDGET_OPENROUTER_TOKENS` | int | `200000` | Prompt budget for OpenRouter lane. |
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
| `SELFUPDATE_AUTO_APPLY_DEV` | int | `1` | When `1` (default), self-update patches apply without manual approval in dev/staging. Set to `0` to require admin approval in dev too. |
| `SELFUPDATE_AUTO_APPLY_PROD` | int | `0` | When `0` (default), prod requires explicit admin approval via `POST /api/v1/selfupdate/patches/{trace_id}/approve` before applying. Set to `1` to skip approval in prod (not recommended). |
| `SELFUPDATE_PATCH_DIR` | str | `/var/lib/agent/patches` | Patch state directory. |
| `SELFUPDATE_SMOKE_PROFILE` | str | `dev` | Smoke profile (`dev`/`prod`). |
| `SELFUPDATE_READYZ_URL` | str | `` | Readiness URL for apply watchdog. |
| `SELFUPDATE_READYZ_ATTEMPTS` | int | `3` | Readiness retry attempts. |
| `SELFUPDATE_SANDBOX_ENABLED` | int | `0` | When `1`, run smoke-gate checks inside Docker sandbox instead of host process. |
| `SELFUPDATE_SANDBOX_IMAGE` | str | `jarvis-sandbox:latest` | Docker image used for sandboxed smoke checks. |
| `SELFUPDATE_SANDBOX_TIMEOUT_SECONDS` | int | `300` | Timeout for each sandboxed smoke command. |

### Scheduler, Restart, and RabbitMQ Mgmt

| Variable | Type | Default | Description |
|---|---|---|---|
| `SCHEDULER_MAX_CATCHUP` | int | `10` | Global catch-up cap per schedule tick. |
| `FOLLOWUP_HEARTBEAT_INTERVAL_SECONDS` | int | `300` | Interval for proactive follow-up heartbeat evaluation (`0` disables). |
| `FOLLOWUP_MAX_THREADS_PER_TICK` | int | `20` | Max enabled threads evaluated each follow-up heartbeat tick. |
| `FOLLOWUP_MIN_IDLE_SECONDS` | int | `300` | Minimum idle age for a thread before follow-up evaluation. |
| `FOLLOWUP_EMIT_IDLE_TICKS` | int | `0` | Emit `followup.tick.*` events even when no followups are enabled (`1` to keep idle telemetry). |
| `STALL_DETECT_ENABLED` | int | `1` | Enable periodic runtime stall watchdog and auto-recovery triggers. |
| `STALL_DETECT_THRESHOLD_SECONDS` | int | `90` | Age threshold for inbound-without-progress before declaring a stall. |
| `STALL_RECOVERY_COOLDOWN_SECONDS` | int | `600` | Minimum delay between consecutive stall-triggered recovery attempts. |
| `AGENT_STEP_MAX_ATTEMPTS` | int | `3` | Max in-process attempts for one `trace_id` before exhaustion. |
| `AGENT_STEP_RETRY_BASE_SECONDS` | int | `2` | Base backoff for retryable agent-step failures. |
| `AGENT_STEP_RETRY_MAX_SECONDS` | int | `20` | Max backoff cap for retryable agent-step failures. |
| `FEATURE_BUILD_RETRY_ON_DEGRADED` | int | `1` | When `1`, feature builds auto-retry retryable degraded terminal outcomes. |
| `FEATURE_BUILD_RETRY_MAX_ATTEMPTS` | int | `5` | Max total attempts per feature build run (initial attempt included). |
| `FEATURE_BUILD_RETRY_BACKOFF_SECONDS` | str | `30,120,300,600` | Comma-delimited retry delays (seconds) for scheduled feature-build retries. |
| `FEATURE_BUILD_RETRY_DISPATCH_INTERVAL_SECONDS` | int | `15` | Periodic interval for scanning and dispatching due scheduled feature-build retries. |
| `FEATURE_BUILD_ESCALATE_ON_EXHAUSTED` | int | `1` | When `1`, exhausted feature-build terminal failures trigger configured human escalation dispatch. |
| `FEATURE_BUILD_FAIL_FAST_PLACEHOLDER_REPEAT` | int | `1` | When `1`, repeated consecutive `placeholder_response_after_tool_loop` outcomes fail fast instead of re-scheduling retries. |
| `FEATURE_BUILD_DELIVERABLE_GATE_ENABLED` | int | `1` | When `1`, feature-build runs require deliverable evidence (diff/no-op blockers + safety checks) before success finalization. |
| `FEATURE_BUILD_LOOP_CAP_THRESHOLD` | int | `8` | Max repeated identical tool-call signature count per build attempt before forcing terminal synthesis fallback. |
| `FEATURE_BUILD_USE_RLM` | int | `0` | When `1`, enable pre-build RLM decomposition (requires `RLM_ENABLED=1`). |
| `FEATURE_ISOLATION_ENABLED` | int | `1` | When `1`, feature-build runs use isolated `/tmp` workspaces and enforce validation before execution. |
| `FEATURE_ISOLATION_TMP_PREFIX` | str | `/tmp/jarvis-feature` | Prefix used for per-feature ephemeral workspace paths. |
| `FEATURE_ISOLATION_MIN_DISK_GB` | int | `10` | Minimum required free disk in workspace volume before validation/build starts. |
| `FEATURE_ISOLATION_TTL_HOURS` | int | `24` | Workspace retention TTL before cleanup. |
| `FEATURE_ISOLATION_CLONE_REF` | str | `origin/dev` | Source ref metadata used for isolated clone provenance. |
| `RLM_ENABLED` | int | `0` | Toggles the RLM decomposition runtime (must match `FEATURE_BUILD_USE_RLM` to activate). |
| `RLM_CONTEXT_FILES_LIMIT` | int | `8` | Max number of source files injected as context for decomposition prompts. |
| `RLM_CONTEXT_TOKEN_LIMIT` | int | `4000` | Token budget for context injection (4 chars/token approximation). |
| `RLM_PROMPT_TOKEN_LIMIT` | int | `8000` | Max `max_tokens` passed to the provider when building prompts. |
| `RLM_VALIDATION_ATTEMPTS` | int | `2` | Total provider attempts (initial + repairs) before failing with human escalation. |
| `RLM_MAX_REFINEMENTS` | int | `3` | Max number of repair prompts allowed when validation errors occur. |
| `RLM_TIMEOUT_S` | int | `120` | Timeout (seconds) for each decomposition provider call. |
| `RLM_BUDGET_PER_1K_TOKENS` | float | `0.02` | Conservative cost estimate per 1,000 tokens for budgeting and logging. |
| `HUMAN_ESCALATION_CHANNEL_TYPE` | str | `whatsapp` | Outbound channel used for escalation dispatch (`whatsapp`, `telegram`, etc. as configured). |
| `HUMAN_ESCALATION_TARGETS` | str | `` | Comma-separated external channel IDs to notify when escalation is requested. |
| `HUMAN_ESCALATION_DEFAULT_PRIORITY` | str | `normal` | Default escalation priority when caller does not provide one. |
| `HUMAN_ESCALATION_DISPATCH_INTERVAL_SECONDS` | int | `15` | Periodic interval for dispatching queued human escalations (`0` disables periodic sweep). |
| `AGENT_RUN_REAPER_INTERVAL_SECONDS` | int | `30` | Periodic stale-attempt recovery scan interval. |
| `AGENT_RUN_MODEL_STALE_MIN_SECONDS` | int | `780` | Minimum stale cutoff while phase=`model.run`. |
| `AGENT_RUN_TOOL_STALE_MIN_SECONDS` | int | `240` | Minimum stale cutoff while phase=`tool.exec`. |
| `AGENT_RUN_FINALIZE_STALE_MIN_SECONDS` | int | `120` | Minimum stale cutoff while phase=`state.extract`/`finalize`. |
| `AGENT_RUN_STALE_HARD_CAP_SECONDS` | int | `2700` | Absolute per-attempt runtime cap before stale recovery. |
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
| `WHATSAPP_INSTANCE` | str | `personal` | Baileys sidecar instance name. |
| `BAILEYS_AUTO_CREATE_ON_STARTUP` | int | `0` | Auto-create Baileys connection on API startup. |
| `WHATSAPP_WEBHOOK_SECRET` | str | `` | Shared secret header required by WhatsApp webhook route when set. |
| `WHATSAPP_MEDIA_DIR` | str | `/tmp/jarvis/whatsapp-media` | Local media staging directory for inbound WhatsApp media/voice notes. |
| `WHATSAPP_MEDIA_MAX_BYTES` | int | `10485760` | Max bytes accepted per inbound media download; oversized payloads are blocked. |
| `WHATSAPP_MEDIA_ALLOWED_MIME_PREFIXES` | str | `audio/,image/,video/,application/pdf` | Comma-separated MIME prefixes allowed for inbound media persistence. |
| `WHATSAPP_MEDIA_ALLOWED_HOSTS` | str | `` | Optional comma-separated HTTPS host allowlist for inbound media URLs. |
| `MEDIA_STORAGE_DIR` | str | `/var/lib/jarvis/media` | Root directory for unified media attachment storage (`media_attachments`). |
| `MEDIA_MAX_UPLOAD_BYTES` | int | `20971520` | Maximum bytes accepted by `POST /api/v1/media/upload`. |
| `WHATSAPP_VOICE_TRANSCRIBE_ENABLED` | int | `1` | Enable voice-note transcript generation for inbound audio messages. |
| `WHATSAPP_VOICE_TRANSCRIBE_BACKEND` | str | `stub` | Voice-note transcription backend selector (`stub`, `faster_whisper`). |
| `WHATSAPP_VOICE_TRANSCRIBE_TIMEOUT_SECONDS` | int | `20` | Timeout for media download/transcription operations on voice notes. |
| `WHATSAPP_VOICE_MODEL` | str | `base` | Faster-Whisper model name when `WHATSAPP_VOICE_TRANSCRIBE_BACKEND=faster_whisper`. |
| `WHATSAPP_VOICE_DEVICE` | str | `cpu` | Faster-Whisper device target (for example `cpu`, `cuda`). |
| `WHATSAPP_VOICE_COMPUTE_TYPE` | str | `int8` | Faster-Whisper compute profile (for example `int8`, `float16`). |
| `WHATSAPP_VOICE_LANGUAGE` | str | `` | Optional fixed language code for transcription; empty enables auto-detect. |
| `WHATSAPP_REVIEW_MODE` | str | `unknown_only` | Sender review policy mode (`off`, `unknown_only`, `strict`) for WhatsApp ingress gating. |
| `WHATSAPP_ALLOWED_SENDERS` | str | `` | Comma-separated sender allowlist for strict sender review mode. |
| `WHATSAPP_TYPING_TTL_SECONDS` | int | `20` | TTL for stale WhatsApp typing markers before periodic auto-clear emits `paused`. |
| `BAILEYS_API_URL` | str | `http://127.0.0.1:8081` | Baileys sidecar API base URL. |
| `BAILEYS_WEBHOOK_URL` | str | `` | Callback URL sidecar forwards inbound events to (usually `/webhooks/whatsapp`). |
| `BAILEYS_WEBHOOK_BY_EVENTS` | int | `1` | Callback metadata flag for event-filtered delivery mode. |
| `BAILEYS_WEBHOOK_EVENTS` | str | `messages.upsert` | Comma-separated webhook event names expected from sidecar forwarding. |
| `BAILEYS_WEBHOOK_SECRET_HEADER` | str | `X-WhatsApp-Secret` | Header name sidecar uses to send webhook secret. |
| `PRIMARY_PROVIDER` | str | `openrouter` | Primary chat provider (`openrouter` or `sglang`). |
| `OPENROUTER_API_KEY` | str | `` | OpenRouter API key. |
| `OPENROUTER_MODEL` | str | `google/gemini-2.5-flash` | OpenRouter model name. |
| `OPENROUTER_BASE_URL` | str | `https://openrouter.ai/api/v1` | OpenRouter API base URL. |
| `OPENROUTER_TIMEOUT_SECONDS` | int | `120` | OpenRouter request timeout. |
| `SGLANG_BASE_URL` | str | `http://localhost:30000/v1` | SGLang endpoint. |
| `SGLANG_MODEL` | str | `openai/gpt-oss-120b` | SGLang model name. |
| `SGLANG_TIMEOUT_SECONDS` | int | `600` | SGLang timeout. |
| `SGLANG_PARALLEL_TOOL_CALLS` | int | `0` | When `0` (default), disables parallel tool calls for SGLang/OSS models that handle them poorly. Set to `1` to enable. |
| `SGLANG_TOOL_CHOICE` | str | `auto` | Tool choice mode for SGLang provider (`auto`, `none`, or a specific function). |
| `OPENROUTER_TOOL_CHOICE` | str | `auto` | Tool choice mode for OpenRouter provider (`auto`, `none`, or a specific function). |
| `OPENROUTER_PARALLEL_TOOL_CALLS` | int | `1` | When `1` (default), allows parallel tool calls for OpenRouter/frontier models. Set to `0` to disable. |

Provider admin runtime note:
- Saving provider settings from the admin API/UI updates `.env` and applies provider keys (`PRIMARY_PROVIDER`, `OPENROUTER_MODEL`, `SGLANG_MODEL`, `OPENROUTER_API_KEY`) to the live API runtime immediately.
- OpenRouter API key reads are masked in API responses; raw key retrieval is not supported.

### Memory and Search

| Variable | Type | Default | Description |
|---|---|---|---|
| `OLLAMA_BASE_URL` | str | `http://localhost:11434` | Ollama endpoint. |
| `OLLAMA_EMBED_MODEL` | str | `nomic-embed-text` | Embedding model. |
| `MEMORY_EMBED_DIMS` | int | `768` | Embedding dimensions. |
| `SQLITE_VEC_EXTENSION_PATH` | str | `` | Optional sqlite-vec extension path. |
| `STATE_EXTRACTION_ENABLED` | int | `1` | Enable state extraction pipeline writes to `state_items`. |
| `STATE_EXTRACTION_MAX_MESSAGES` | int | `20` | Message window used for state extraction candidates. |
| `STATE_EXTRACTION_MERGE_THRESHOLD` | float | `0.92` | Similarity threshold for state merge decisions. |
| `STATE_EXTRACTION_CONFLICT_THRESHOLD` | float | `0.85` | Similarity threshold for conflict queue insertion. |
| `STATE_EXTRACTION_TIMEOUT_SECONDS` | int | `30` | Timeout for state extraction model operations. |
| `STATE_EXTRACTION_BACKOFF_BASE_SECONDS` | int | `30` | Base retry delay for per-thread extraction backoff after failures. |
| `STATE_EXTRACTION_BACKOFF_MAX_SECONDS` | int | `600` | Max retry delay for per-thread extraction backoff. |
| `STATE_MAX_ACTIVE_ITEMS` | int | `40` | Max active state items maintained per scope before archival pressure. |
| `MEMORY_SECRET_SCAN_ENABLED` | int | `1` | Enable secret-pattern scanning before persistence. |
| `MEMORY_PII_REDACT_MODE` | str | `mask` | PII handling mode for memory text persistence. |
| `MEMORY_RETENTION_DAYS` | int | `180` | Retention horizon for memory maintenance/archival decisions. |
| `MEMORY_TIERS_ENABLED` | int | `0` | Enable tiered memory lifecycle (`working/episodic/semantic`). |
| `MEMORY_IMPORTANCE_ENABLED` | int | `0` | Enable score-based promotion/demotion decisions. |
| `MEMORY_GRAPH_ENABLED` | int | `0` | Enable graph relation extraction and traversal surfaces. |
| `MEMORY_REVIEW_QUEUE_ENABLED` | int | `1` | Enable conflict queue generation in `memory_review_queue`. |
| `MEMORY_FAILURE_BRIDGE_ENABLED` | int | `1` | Enable failure capsule bridge into state memory. |
| `MEMORY_SENTENCE_TRANSFORMERS_MODEL` | str | `all-MiniLM-L6-v2` | Sentence-transformers model used by memory similarity operations. |
| `MEMORY_REFLECTION_ENABLED` | int | `1` | Enable periodic reflection job that synthesizes worldview/insights. |
| `MEMORY_REFLECTION_INTERVAL_SECONDS` | int | `21600` | Interval (seconds) between automatic reflection runs. |
| `MEMORY_REFLECTION_BATCH_SIZE` | int | `10` | Maximum open threads processed per reflection run. |
| `MEMORY_REFLECTION_INSIGHT_LIMIT` | int | `3` | Max insights synthesized per reflection execution. |
| `MEMORY_REFLECTION_PRUNE_THRESHOLD` | float | `0.35` | Importance score threshold for reflection-driven pruning. |
| `MEMORY_REFLECTION_PRUNE_AGE_DAYS` | int | `30` | Minimum age (days) for state items considered for pruning. |
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
| `EXEC_HOST_TIMEOUT_MAX_SECONDS` | int | `600` | Max command runtime. |
| `EXEC_HOST_LOG_DIR` | str | `/var/lib/agent/exec` | Exec-host log path. |
| `EXEC_HOST_ENV_ALLOWLIST` | str | `PATH,HOME,LANG,LC_ALL,TZ` | Allowed env pass-through list. |
| `EXEC_HOST_ALLOWED_CWD_PREFIXES` | str | `/srv/agent-framework,/tmp,/home/justin/jarvis` | Allowed working-directory prefixes. |
| `EXEC_HOST_SANDBOX` | str | `none` | Sandbox mode selector. |
| `EXEC_HOST_MAX_OUTPUT_BYTES` | int | `1000000` | Output cap per command. |
| `EXEC_HOST_MAX_MEMORY_MB` | int | `512` | Memory cap. |
| `EXEC_HOST_MAX_CPU_SECONDS` | int | `120` | CPU time cap. |
| `EXEC_HOST_FULL_LOG_MAX_BYTES` | int | `262144` | Max bytes persisted per full host-exec log file before truncation marker is appended. |
| `EXEC_HOST_LOG_RETENTION_DAYS` | int | `7` | Remove host-exec logs older than this age (`0` disables age-based pruning). |
| `EXEC_HOST_LOG_RETENTION_MAX_FILES` | int | `1000` | Max host-exec log files retained per directory (`0` disables file-count pruning). |
| `EXEC_HOST_LOG_RETENTION_MAX_BYTES` | int | `524288000` | Max total retained bytes per directory for host-exec logs (`0` disables size-based pruning). |

## Production Validation Rules

`validate_settings_for_env()` enforces additional checks in `APP_ENV=prod`:

- Required non-empty fields include DB/broker/provider/auth/admin/backup/PagerDuty values.
- `WHATSAPP_VERIFY_TOKEN` cannot remain default dev token.
- If `GITHUB_PR_SUMMARY_ENABLED=1`, `GITHUB_TOKEN` and `GITHUB_WEBHOOK_SECRET` are required.
- If `GITHUB_ISSUE_SYNC_ENABLED=1`, `GITHUB_TOKEN` and `GITHUB_ISSUE_SYNC_REPO` are required.
- `APP_DB` must be an absolute path.
- If `BIND_HOST=0.0.0.0` in prod, runtime emits a security warning.

## Runtime Metrics

`GET /metrics` exposes JSON counters/gauges including memory lifecycle KPIs:

- `memory_items_count`: current `memory_items` row count.
- `memory_avg_tokens_saved`: average `state_reconciliation_runs.tokens_saved` over the last 7 days.
- `memory_reconciliation_rate`: fraction of reconciliation runs with non-zero updates/supersessions/dedupes/prunes (7-day window).
- `memory_hallucination_incidents`: failure capsule count tagged/detected as hallucination.

## Related Docs

- `docs/README.md`
- `.env.example`
- `docs/local-development.md`
- `docs/change-safety.md`
- `docs/deploy-operations.md`
