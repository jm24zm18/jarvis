"""Application configuration contract."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = Field(alias="APP_ENV", default="dev")
    app_db: str = Field(alias="APP_DB", default="/tmp/jarvis.db")
    log_level: str = Field(alias="LOG_LEVEL", default="INFO")
    trace_sample_rate: float = Field(alias="TRACE_SAMPLE_RATE", default=1.0)
    compaction_every_n_events: int = Field(alias="COMPACTION_EVERY_N_EVENTS", default=25)
    compaction_interval_seconds: int = Field(alias="COMPACTION_INTERVAL_SECONDS", default=600)
    prompt_budget_openrouter_tokens: int = Field(
        alias="PROMPT_BUDGET_OPENROUTER_TOKENS", default=200000
    )
    prompt_budget_sglang_tokens: int = Field(alias="PROMPT_BUDGET_SGLANG_TOKENS", default=110000)
    lockdown_default: int = Field(alias="LOCKDOWN_DEFAULT", default=0)
    selfupdate_auto_apply_dev: int = Field(alias="SELFUPDATE_AUTO_APPLY_DEV", default=1)
    selfupdate_auto_apply_prod: int = Field(alias="SELFUPDATE_AUTO_APPLY_PROD", default=0)
    selfupdate_patch_dir: str = Field(
        alias="SELFUPDATE_PATCH_DIR", default="/var/lib/agent/patches"
    )
    selfupdate_smoke_profile: str = Field(alias="SELFUPDATE_SMOKE_PROFILE", default="dev")
    selfupdate_readyz_url: str = Field(alias="SELFUPDATE_READYZ_URL", default="")
    selfupdate_readyz_attempts: int = Field(alias="SELFUPDATE_READYZ_ATTEMPTS", default=3)
    selfupdate_critical_paths: str = Field(
        alias="SELFUPDATE_CRITICAL_PATHS",
        default=(
            "src/jarvis/policy/**,src/jarvis/tools/runtime.py,src/jarvis/auth/**,"
            "src/jarvis/routes/api/**,src/jarvis/db/migrations/**"
        ),
    )
    selfupdate_pr_autoraise: int = Field(alias="SELFUPDATE_PR_AUTORAISE", default=0)
    selfupdate_fitness_gate_mode: str = Field(alias="SELFUPDATE_FITNESS_GATE_MODE", default="warn")
    selfupdate_test_gate_mode: str = Field(alias="SELFUPDATE_TEST_GATE_MODE", default="warn")
    selfupdate_max_files_per_patch: int = Field(alias="SELFUPDATE_MAX_FILES_PER_PATCH", default=20)
    selfupdate_max_risk_score: int = Field(alias="SELFUPDATE_MAX_RISK_SCORE", default=100)
    selfupdate_max_patch_attempts_per_day: int = Field(
        alias="SELFUPDATE_MAX_PATCH_ATTEMPTS_PER_DAY", default=10
    )
    selfupdate_max_prs_per_day: int = Field(alias="SELFUPDATE_MAX_PRS_PER_DAY", default=5)
    selfupdate_test_gate_min_coverage_pct: float = Field(
        alias="SELFUPDATE_TEST_GATE_MIN_COVERAGE_PCT", default=0.0
    )
    selfupdate_test_gate_require_critical_tests: int = Field(
        alias="SELFUPDATE_TEST_GATE_REQUIRE_CRITICAL_TESTS", default=1
    )
    selfupdate_fitness_max_age_minutes: int = Field(
        alias="SELFUPDATE_FITNESS_MAX_AGE_MINUTES", default=180
    )
    selfupdate_min_build_success_rate: float = Field(
        alias="SELFUPDATE_MIN_BUILD_SUCCESS_RATE", default=0.80
    )
    selfupdate_max_regression_frequency: float = Field(
        alias="SELFUPDATE_MAX_REGRESSION_FREQ", default=0.40
    )
    selfupdate_max_rollback_frequency: int = Field(
        alias="SELFUPDATE_MAX_ROLLBACK_FREQ", default=3
    )
    scheduler_max_catchup: int = Field(alias="SCHEDULER_MAX_CATCHUP", default=10)
    followup_heartbeat_interval_seconds: int = Field(
        alias="FOLLOWUP_HEARTBEAT_INTERVAL_SECONDS",
        default=300,
    )
    followup_max_threads_per_tick: int = Field(alias="FOLLOWUP_MAX_THREADS_PER_TICK", default=20)
    followup_min_idle_seconds: int = Field(alias="FOLLOWUP_MIN_IDLE_SECONDS", default=300)
    followup_emit_idle_ticks: int = Field(alias="FOLLOWUP_EMIT_IDLE_TICKS", default=0)
    task_runner_max_concurrent: int = Field(alias="TASK_RUNNER_MAX_CONCURRENT", default=20)
    task_runner_shutdown_timeout_seconds: int = Field(
        alias="TASK_RUNNER_SHUTDOWN_TIMEOUT_SECONDS",
        default=30,
    )
    agent_step_max_attempts: int = Field(alias="AGENT_STEP_MAX_ATTEMPTS", default=3)
    agent_step_retry_base_seconds: int = Field(alias="AGENT_STEP_RETRY_BASE_SECONDS", default=2)
    agent_step_retry_max_seconds: int = Field(alias="AGENT_STEP_RETRY_MAX_SECONDS", default=20)
    feature_build_retry_on_degraded: int = Field(
        alias="FEATURE_BUILD_RETRY_ON_DEGRADED",
        default=1,
    )
    feature_build_retry_max_attempts: int = Field(
        alias="FEATURE_BUILD_RETRY_MAX_ATTEMPTS",
        default=5,
    )
    feature_build_retry_backoff_seconds: str = Field(
        alias="FEATURE_BUILD_RETRY_BACKOFF_SECONDS",
        default="30,120,300,600",
    )
    feature_build_retry_dispatch_interval_seconds: int = Field(
        alias="FEATURE_BUILD_RETRY_DISPATCH_INTERVAL_SECONDS",
        default=15,
    )
    feature_build_escalate_on_exhausted: int = Field(
        alias="FEATURE_BUILD_ESCALATE_ON_EXHAUSTED",
        default=1,
    )
    feature_build_fail_fast_placeholder_repeat: int = Field(
        alias="FEATURE_BUILD_FAIL_FAST_PLACEHOLDER_REPEAT",
        default=1,
    )
    feature_build_deliverable_gate_enabled: int = Field(
        alias="FEATURE_BUILD_DELIVERABLE_GATE_ENABLED",
        default=1,
    )
    feature_build_loop_cap_threshold: int = Field(
        alias="FEATURE_BUILD_LOOP_CAP_THRESHOLD",
        default=8,
    )
    feature_build_attempt_capsules_enabled: int = Field(
        alias="FEATURE_BUILD_ATTEMPT_CAPSULES_ENABLED",
        default=1,
    )
    feature_build_repeat_limit: int = Field(
        alias="FEATURE_BUILD_REPEAT_LIMIT",
        default=2,
    )
    feature_build_use_rlm: int = Field(alias="FEATURE_BUILD_USE_RLM", default=0)
    rlm_enabled: int = Field(alias="RLM_ENABLED", default=0)
    rlm_context_files_limit: int = Field(alias="RLM_CONTEXT_FILES_LIMIT", default=8)
    rlm_context_token_limit: int = Field(alias="RLM_CONTEXT_TOKEN_LIMIT", default=4000)
    rlm_prompt_token_limit: int = Field(alias="RLM_PROMPT_TOKEN_LIMIT", default=8000)
    rlm_validation_attempts: int = Field(alias="RLM_VALIDATION_ATTEMPTS", default=2)
    rlm_max_attempts: int = Field(alias="RLM_MAX_ATTEMPTS", default=2)
    rlm_max_refinements: int = Field(alias="RLM_MAX_REFINEMENTS", default=3)
    rlm_timeout_s: int = Field(alias="RLM_TIMEOUT_S", default=120)
    rlm_budget_per_1k_tokens: float = Field(alias="RLM_BUDGET_PER_1K_TOKENS", default=0.02)
    feature_build_require_test_gates: int = Field(
        alias="FEATURE_BUILD_REQUIRE_TEST_GATES",
        default=1,
    )
    feature_isolation_enabled: int = Field(
        alias="FEATURE_ISOLATION_ENABLED",
        default=1,
    )
    feature_isolation_tmp_prefix: str = Field(
        alias="FEATURE_ISOLATION_TMP_PREFIX",
        default="/tmp/jarvis-feature",
    )
    feature_isolation_min_disk_gb: int = Field(
        alias="FEATURE_ISOLATION_MIN_DISK_GB",
        default=10,
    )
    feature_isolation_ttl_hours: int = Field(
        alias="FEATURE_ISOLATION_TTL_HOURS",
        default=24,
    )
    feature_isolation_clone_ref: str = Field(
        alias="FEATURE_ISOLATION_CLONE_REF",
        default="origin/dev",
    )
    orchestrator_max_tool_iterations: int = Field(
        alias="ORCHESTRATOR_MAX_TOOL_ITERATIONS",
        default=8,
    )
    orchestrator_fallback_only_retries: int = Field(
        alias="ORCHESTRATOR_FALLBACK_ONLY_RETRIES",
        default=2,
    )
    human_escalation_channel_type: str = Field(
        alias="HUMAN_ESCALATION_CHANNEL_TYPE",
        default="whatsapp",
    )
    human_escalation_targets: str = Field(
        alias="HUMAN_ESCALATION_TARGETS",
        default="",
    )
    human_escalation_default_priority: str = Field(
        alias="HUMAN_ESCALATION_DEFAULT_PRIORITY",
        default="normal",
    )
    human_escalation_dispatch_interval_seconds: int = Field(
        alias="HUMAN_ESCALATION_DISPATCH_INTERVAL_SECONDS",
        default=15,
    )
    agent_run_reaper_interval_seconds: int = Field(
        alias="AGENT_RUN_REAPER_INTERVAL_SECONDS", default=30
    )
    agent_run_model_stale_min_seconds: int = Field(
        alias="AGENT_RUN_MODEL_STALE_MIN_SECONDS", default=780
    )
    agent_run_tool_stale_min_seconds: int = Field(
        alias="AGENT_RUN_TOOL_STALE_MIN_SECONDS", default=240
    )
    agent_run_finalize_stale_min_seconds: int = Field(
        alias="AGENT_RUN_FINALIZE_STALE_MIN_SECONDS", default=120
    )
    agent_run_stale_hard_cap_seconds: int = Field(
        alias="AGENT_RUN_STALE_HARD_CAP_SECONDS", default=2700
    )
    restart_command: str = Field(alias="RESTART_COMMAND", default="")
    lockdown_readyz_fail_threshold: int = Field(alias="LOCKDOWN_READYZ_FAIL_THRESHOLD", default=3)
    lockdown_rollback_threshold: int = Field(alias="LOCKDOWN_ROLLBACK_THRESHOLD", default=2)
    lockdown_rollback_window_minutes: int = Field(
        alias="LOCKDOWN_ROLLBACK_WINDOW_MINUTES", default=30
    )
    lockdown_exec_host_fail_threshold: int = Field(
        alias="LOCKDOWN_EXEC_HOST_FAIL_THRESHOLD", default=5
    )
    lockdown_exec_host_fail_window_minutes: int = Field(
        alias="LOCKDOWN_EXEC_HOST_FAIL_WINDOW_MINUTES", default=10
    )

    whatsapp_verify_token: str = Field(alias="WHATSAPP_VERIFY_TOKEN", default="dev-verify-token")
    whatsapp_access_token: str = Field(alias="WHATSAPP_ACCESS_TOKEN", default="")
    whatsapp_phone_number_id: str = Field(alias="WHATSAPP_PHONE_NUMBER_ID", default="")
    whatsapp_instance: str = Field(alias="WHATSAPP_INSTANCE", default="personal")
    whatsapp_auto_create_on_startup: int = Field(
        alias="BAILEYS_AUTO_CREATE_ON_STARTUP", default=0
    )
    whatsapp_webhook_secret: str = Field(alias="WHATSAPP_WEBHOOK_SECRET", default="")
    whatsapp_media_dir: str = Field(
        alias="WHATSAPP_MEDIA_DIR",
        default="/tmp/jarvis/whatsapp-media",
    )
    whatsapp_media_max_bytes: int = Field(alias="WHATSAPP_MEDIA_MAX_BYTES", default=10_485_760)
    whatsapp_media_allowed_mime_prefixes: str = Field(
        alias="WHATSAPP_MEDIA_ALLOWED_MIME_PREFIXES",
        default="audio/,image/,video/,application/pdf",
    )
    whatsapp_media_allowed_hosts: str = Field(alias="WHATSAPP_MEDIA_ALLOWED_HOSTS", default="")
    whatsapp_voice_transcribe_enabled: int = Field(
        alias="WHATSAPP_VOICE_TRANSCRIBE_ENABLED",
        default=1,
    )
    whatsapp_voice_transcribe_backend: str = Field(
        alias="WHATSAPP_VOICE_TRANSCRIBE_BACKEND",
        default="stub",
    )
    whatsapp_voice_transcribe_timeout_seconds: int = Field(
        alias="WHATSAPP_VOICE_TRANSCRIBE_TIMEOUT_SECONDS",
        default=20,
    )
    whatsapp_voice_model: str = Field(
        alias="WHATSAPP_VOICE_MODEL",
        default="base",
    )
    whatsapp_voice_device: str = Field(
        alias="WHATSAPP_VOICE_DEVICE",
        default="cpu",
    )
    whatsapp_voice_compute_type: str = Field(
        alias="WHATSAPP_VOICE_COMPUTE_TYPE",
        default="int8",
    )
    whatsapp_voice_language: str = Field(
        alias="WHATSAPP_VOICE_LANGUAGE",
        default="",
    )
    whatsapp_review_mode: str = Field(alias="WHATSAPP_REVIEW_MODE", default="unknown_only")
    whatsapp_allowed_senders: str = Field(alias="WHATSAPP_ALLOWED_SENDERS", default="")
    whatsapp_typing_ttl_seconds: int = Field(alias="WHATSAPP_TYPING_TTL_SECONDS", default=20)
    baileys_api_url: str = Field(alias="BAILEYS_API_URL", default="http://127.0.0.1:8081")
    baileys_webhook_url: str = Field(alias="BAILEYS_WEBHOOK_URL", default="")
    baileys_webhook_by_events: int = Field(alias="BAILEYS_WEBHOOK_BY_EVENTS", default=1)
    baileys_webhook_events: str = Field(
        alias="BAILEYS_WEBHOOK_EVENTS",
        default="messages.upsert",
    )
    baileys_webhook_secret_header: str = Field(
        alias="BAILEYS_WEBHOOK_SECRET_HEADER",
        default="X-WhatsApp-Secret",
    )

    # Telegram
    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN", default="")
    telegram_allowed_chat_ids: str = Field(alias="TELEGRAM_ALLOWED_CHAT_IDS", default="")

    google_oauth_client_id: str = Field(alias="GOOGLE_OAUTH_CLIENT_ID", default="")
    google_oauth_client_secret: str = Field(alias="GOOGLE_OAUTH_CLIENT_SECRET", default="")
    primary_provider: str = Field(alias="PRIMARY_PROVIDER", default="openrouter")
    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY", default="")
    openrouter_model: str = Field(alias="OPENROUTER_MODEL", default="google/gemini-2.5-flash")
    openrouter_base_url: str = Field(
        alias="OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1"
    )
    openrouter_timeout_seconds: int = Field(alias="OPENROUTER_TIMEOUT_SECONDS", default=120, ge=10)

    sglang_base_url: str = Field(alias="SGLANG_BASE_URL", default="http://localhost:30000/v1")
    sglang_model: str = Field(alias="SGLANG_MODEL", default="openai/gpt-oss-120b")
    sglang_timeout_seconds: int = Field(alias="SGLANG_TIMEOUT_SECONDS", default=600)
    sglang_parallel_tool_calls: int = Field(alias="SGLANG_PARALLEL_TOOL_CALLS", default=0)
    sglang_tool_choice: str = Field(alias="SGLANG_TOOL_CHOICE", default="auto")
    openrouter_tool_choice: str = Field(alias="OPENROUTER_TOOL_CHOICE", default="auto")
    openrouter_parallel_tool_calls: int = Field(alias="OPENROUTER_PARALLEL_TOOL_CALLS", default=1)

    ollama_base_url: str = Field(alias="OLLAMA_BASE_URL", default="http://localhost:11434")
    ollama_embed_model: str = Field(alias="OLLAMA_EMBED_MODEL", default="nomic-embed-text")
    memory_embed_dims: int = Field(alias="MEMORY_EMBED_DIMS", default=768)
    sqlite_vec_extension_path: str = Field(alias="SQLITE_VEC_EXTENSION_PATH", default="")
    state_extraction_enabled: int = Field(alias="STATE_EXTRACTION_ENABLED", default=1)
    state_extraction_max_messages: int = Field(alias="STATE_EXTRACTION_MAX_MESSAGES", default=20)
    state_extraction_merge_threshold: float = Field(
        alias="STATE_EXTRACTION_MERGE_THRESHOLD", default=0.92
    )
    state_extraction_conflict_threshold: float = Field(
        alias="STATE_EXTRACTION_CONFLICT_THRESHOLD", default=0.85
    )
    state_max_active_items: int = Field(alias="STATE_MAX_ACTIVE_ITEMS", default=40)
    state_extraction_timeout_seconds: int = Field(
        alias="STATE_EXTRACTION_TIMEOUT_SECONDS", default=30
    )
    state_extraction_backoff_base_seconds: int = Field(
        alias="STATE_EXTRACTION_BACKOFF_BASE_SECONDS",
        default=30,
    )
    state_extraction_backoff_max_seconds: int = Field(
        alias="STATE_EXTRACTION_BACKOFF_MAX_SECONDS",
        default=600,
    )
    governance_enforce: int = Field(alias="GOVERNANCE_ENFORCE", default=1)
    approval_ttl_minutes: int = Field(alias="APPROVAL_TTL_MINUTES", default=30)
    dependency_steward_enabled: int = Field(alias="DEPENDENCY_STEWARD_ENABLED", default=0)
    dependency_steward_max_upgrades: int = Field(
        alias="DEPENDENCY_STEWARD_MAX_UPGRADES", default=10
    )
    release_candidate_agent_enabled: int = Field(
        alias="RELEASE_CANDIDATE_AGENT_ENABLED", default=0
    )
    user_simulator_enabled: int = Field(alias="USER_SIMULATOR_ENABLED", default=0)
    user_simulator_required_pack: str = Field(alias="USER_SIMULATOR_REQUIRED_PACK", default="p0")
    memory_secret_scan_enabled: int = Field(alias="MEMORY_SECRET_SCAN_ENABLED", default=1)
    memory_pii_redact_mode: str = Field(alias="MEMORY_PII_REDACT_MODE", default="mask")
    memory_retention_days: int = Field(alias="MEMORY_RETENTION_DAYS", default=180)
    event_retention_days: int = Field(alias="EVENT_RETENTION_DAYS", default=90)
    memory_tiers_enabled: int = Field(alias="MEMORY_TIERS_ENABLED", default=0)
    memory_importance_enabled: int = Field(alias="MEMORY_IMPORTANCE_ENABLED", default=0)
    memory_graph_enabled: int = Field(alias="MEMORY_GRAPH_ENABLED", default=0)
    memory_review_queue_enabled: int = Field(alias="MEMORY_REVIEW_QUEUE_ENABLED", default=1)
    memory_failure_bridge_enabled: int = Field(alias="MEMORY_FAILURE_BRIDGE_ENABLED", default=1)
    memory_sentence_transformers_model: str = Field(
        alias="MEMORY_SENTENCE_TRANSFORMERS_MODEL",
        default="all-MiniLM-L6-v2",
    )
    memory_reflection_enabled: int = Field(alias="MEMORY_REFLECTION_ENABLED", default=1)
    memory_reflection_interval_seconds: int = Field(
        alias="MEMORY_REFLECTION_INTERVAL_SECONDS",
        default=21600,
    )
    memory_reflection_batch_size: int = Field(alias="MEMORY_REFLECTION_BATCH_SIZE", default=10)
    memory_reflection_insight_limit: int = Field(alias="MEMORY_REFLECTION_INSIGHT_LIMIT", default=3)
    memory_reflection_prune_threshold: float = Field(
        alias="MEMORY_REFLECTION_PRUNE_THRESHOLD",
        default=0.35,
    )
    memory_reflection_prune_age_days: int = Field(
        alias="MEMORY_REFLECTION_PRUNE_AGE_DAYS",
        default=30,
    )

    searxng_base_url: str = Field(alias="SEARXNG_BASE_URL", default="http://localhost:8080")
    searxng_api_key: str = Field(alias="SEARXNG_API_KEY", default="")
    searxng_api_key_header: str = Field(alias="SEARXNG_API_KEY_HEADER", default="X-API-Key")
    web_search_user_agent: str = Field(
        alias="WEB_SEARCH_USER_AGENT",
        default="Mozilla/5.0 (compatible; Jarvis/1.0; +https://localhost)",
    )
    admin_whatsapp_ids: str = Field(alias="ADMIN_WHATSAPP_IDS", default="")
    admin_unlock_code_path: str = Field(
        alias="ADMIN_UNLOCK_CODE_PATH", default="/var/lib/agent/admin_unlock_code"
    )
    admin_unlock_code_ttl_minutes: int = Field(alias="ADMIN_UNLOCK_CODE_TTL_MINUTES", default=10)
    backup_s3_endpoint: str = Field(alias="BACKUP_S3_ENDPOINT", default="")
    backup_s3_bucket: str = Field(alias="BACKUP_S3_BUCKET", default="")
    backup_s3_region: str = Field(alias="BACKUP_S3_REGION", default="auto")
    backup_s3_access_key_id: str = Field(alias="BACKUP_S3_ACCESS_KEY_ID", default="")
    backup_s3_secret_access_key: str = Field(alias="BACKUP_S3_SECRET_ACCESS_KEY", default="")
    backup_local_dir: str = Field(alias="BACKUP_LOCAL_DIR", default="/tmp/jarvis_backups")
    backup_encrypt_remote: int = Field(alias="BACKUP_ENCRYPT_REMOTE", default=1)
    backup_retention_hourly: int = Field(alias="BACKUP_RETENTION_HOURLY", default=24)
    backup_retention_daily: int = Field(alias="BACKUP_RETENTION_DAILY", default=14)
    backup_retention_weekly: int = Field(alias="BACKUP_RETENTION_WEEKLY", default=8)
    pagerduty_routing_key: str = Field(alias="PAGERDUTY_ROUTING_KEY", default="")
    alert_slack_webhook_url: str = Field(alias="ALERT_SLACK_WEBHOOK_URL", default="")
    maintenance_enabled: int = Field(alias="MAINTENANCE_ENABLED", default=0)
    maintenance_heartbeat_interval_seconds: int = Field(
        alias="MAINTENANCE_HEARTBEAT_INTERVAL_SECONDS",
        default=300,
    )
    maintenance_interval_seconds: int = Field(alias="MAINTENANCE_INTERVAL_SECONDS", default=0)
    maintenance_commands: str = Field(
        alias="MAINTENANCE_COMMANDS",
        default="make lint\nmake typecheck",
    )
    maintenance_timeout_seconds: int = Field(alias="MAINTENANCE_TIMEOUT_SECONDS", default=1800)
    maintenance_create_bugs: int = Field(alias="MAINTENANCE_CREATE_BUGS", default=1)
    maintenance_workdir: str = Field(alias="MAINTENANCE_WORKDIR", default="")
    github_token: str = Field(alias="GITHUB_TOKEN", default="")
    github_webhook_secret: str = Field(alias="GITHUB_WEBHOOK_SECRET", default="")
    webhook_replay_window_minutes: int = Field(
        alias="WEBHOOK_REPLAY_WINDOW_MINUTES",
        default=15,
    )
    github_api_base_url: str = Field(alias="GITHUB_API_BASE_URL", default="https://api.github.com")
    github_repo_allowlist: str = Field(alias="GITHUB_REPO_ALLOWLIST", default="")
    github_bot_login: str = Field(alias="GITHUB_BOT_LOGIN", default="jarvis")
    github_pr_summary_enabled: int = Field(alias="GITHUB_PR_SUMMARY_ENABLED", default=0)
    github_issue_sync_enabled: int = Field(alias="GITHUB_ISSUE_SYNC_ENABLED", default=0)
    github_issue_sync_repo: str = Field(alias="GITHUB_ISSUE_SYNC_REPO", default="")
    github_issue_labels_bug: str = Field(alias="GITHUB_ISSUE_LABELS_BUG", default="jarvis,bug")
    github_issue_labels_feature: str = Field(
        alias="GITHUB_ISSUE_LABELS_FEATURE",
        default="jarvis,feature-request",
    )
    exec_host_timeout_max_seconds: int = Field(alias="EXEC_HOST_TIMEOUT_MAX_SECONDS", default=600)
    exec_host_log_dir: str = Field(alias="EXEC_HOST_LOG_DIR", default="/var/lib/agent/exec")
    exec_host_env_allowlist: str = Field(
        alias="EXEC_HOST_ENV_ALLOWLIST", default="PATH,HOME,LANG,LC_ALL,TZ"
    )
    exec_host_allowed_cwd_prefixes: str = Field(
        alias="EXEC_HOST_ALLOWED_CWD_PREFIXES",
        default="/srv/agent-framework,/tmp," + str(Path.cwd()),
    )
    web_auth_token_ttl_hours: int = Field(alias="WEB_AUTH_TOKEN_TTL_HOURS", default=720)
    web_cors_origins: str = Field(alias="WEB_CORS_ORIGINS", default="http://localhost:5173")
    web_auth_setup_password: str = Field(alias="WEB_AUTH_SETUP_PASSWORD", default="")

    # Security: bind host defaults to loopback
    bind_host: str = Field(alias="BIND_HOST", default="127.0.0.1")
    bind_port: int = Field(alias="BIND_PORT", default=8000)

    # Rate limiting
    rate_limit_messages_per_minute: int = Field(
        alias="RATE_LIMIT_MESSAGES_PER_MINUTE", default=30
    )
    rate_limit_webhooks_per_minute: int = Field(
        alias="RATE_LIMIT_WEBHOOKS_PER_MINUTE", default=60
    )

    # exec_host sandboxing
    exec_host_sandbox: str = Field(alias="EXEC_HOST_SANDBOX", default="none")
    exec_host_max_output_bytes: int = Field(alias="EXEC_HOST_MAX_OUTPUT_BYTES", default=1_000_000)
    exec_host_max_memory_mb: int = Field(alias="EXEC_HOST_MAX_MEMORY_MB", default=512)
    exec_host_max_cpu_seconds: int = Field(alias="EXEC_HOST_MAX_CPU_SECONDS", default=120)
    exec_host_full_log_max_bytes: int = Field(
        alias="EXEC_HOST_FULL_LOG_MAX_BYTES",
        default=262_144,
    )
    exec_host_log_retention_days: int = Field(alias="EXEC_HOST_LOG_RETENTION_DAYS", default=7)
    exec_host_log_retention_max_files: int = Field(
        alias="EXEC_HOST_LOG_RETENTION_MAX_FILES",
        default=1_000,
    )
    exec_host_log_retention_max_bytes: int = Field(
        alias="EXEC_HOST_LOG_RETENTION_MAX_BYTES",
        default=524_288_000,
    )
    stall_detect_enabled: int = Field(alias="STALL_DETECT_ENABLED", default=1)
    stall_detect_threshold_seconds: int = Field(
        alias="STALL_DETECT_THRESHOLD_SECONDS",
        default=90,
    )
    stall_recovery_cooldown_seconds: int = Field(
        alias="STALL_RECOVERY_COOLDOWN_SECONDS",
        default=600,
    )

    # Self-update smoke-gate sandboxing
    selfupdate_sandbox_enabled: int = Field(alias="SELFUPDATE_SANDBOX_ENABLED", default=0)
    selfupdate_sandbox_image: str = Field(
        alias="SELFUPDATE_SANDBOX_IMAGE", default="jarvis-sandbox:latest"
    )
    selfupdate_sandbox_timeout_seconds: int = Field(
        alias="SELFUPDATE_SANDBOX_TIMEOUT_SECONDS", default=300
    )

    # Media storage
    media_storage_dir: str = Field(alias="MEDIA_STORAGE_DIR", default="/var/lib/jarvis/media")
    media_max_upload_bytes: int = Field(alias="MEDIA_MAX_UPLOAD_BYTES", default=20_971_520)


def validate_settings_for_env(settings: Settings) -> None:
    import logging as _logging
    import warnings

    _logger = _logging.getLogger(__name__)

    # Warn if binding to 0.0.0.0 in production
    if settings.app_env == "prod" and settings.bind_host == "0.0.0.0":
        msg = (
            "SECURITY WARNING: BIND_HOST=0.0.0.0 in production. "
            "This exposes the API to all network interfaces. "
            "Set BIND_HOST=127.0.0.1 and use a reverse proxy."
        )
        _logger.warning(msg)
        warnings.warn(msg, stacklevel=2)

    if settings.app_env != "prod":
        return

    missing: list[str] = []
    required_non_empty = {
        "APP_DB": settings.app_db,
        "PRIMARY_PROVIDER": settings.primary_provider,
        "OPENROUTER_MODEL": settings.openrouter_model,
        "SGLANG_BASE_URL": settings.sglang_base_url,
        "SGLANG_MODEL": settings.sglang_model,
        "OLLAMA_BASE_URL": settings.ollama_base_url,
        "OLLAMA_EMBED_MODEL": settings.ollama_embed_model,
        "SEARXNG_BASE_URL": settings.searxng_base_url,

        "BACKUP_S3_ENDPOINT": settings.backup_s3_endpoint,
        "BACKUP_S3_BUCKET": settings.backup_s3_bucket,
        "BACKUP_S3_REGION": settings.backup_s3_region,
        "BACKUP_S3_ACCESS_KEY_ID": settings.backup_s3_access_key_id,
        "BACKUP_S3_SECRET_ACCESS_KEY": settings.backup_s3_secret_access_key,
        "PAGERDUTY_ROUTING_KEY": settings.pagerduty_routing_key,
    }
    for key, value in required_non_empty.items():
        if not value.strip():
            missing.append(key)

    if settings.whatsapp_verify_token == "dev-verify-token":
        missing.append("WHATSAPP_VERIFY_TOKEN(non-dev value)")
    if settings.whatsapp_access_token == "dev-token":
        missing.append("WHATSAPP_ACCESS_TOKEN(non-dev value)")
    if int(settings.github_pr_summary_enabled) == 1:
        if not settings.github_token.strip():
            missing.append("GITHUB_TOKEN")
        if not settings.github_webhook_secret.strip():
            missing.append("GITHUB_WEBHOOK_SECRET")
    if int(settings.github_issue_sync_enabled) == 1:
        if not settings.github_token.strip():
            missing.append("GITHUB_TOKEN")
        if not settings.github_issue_sync_repo.strip():
            missing.append("GITHUB_ISSUE_SYNC_REPO")
    if not settings.app_db.startswith("/"):
        missing.append("APP_DB(absolute path required)")

    if missing:
        keys = ", ".join(sorted(set(missing)))
        raise ValueError(f"invalid production configuration: {keys}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
