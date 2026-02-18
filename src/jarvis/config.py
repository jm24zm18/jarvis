"""Application configuration contract."""

from functools import lru_cache

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
    prompt_budget_gemini_tokens: int = Field(alias="PROMPT_BUDGET_GEMINI_TOKENS", default=200000)
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
    task_runner_max_concurrent: int = Field(alias="TASK_RUNNER_MAX_CONCURRENT", default=20)
    task_runner_shutdown_timeout_seconds: int = Field(
        alias="TASK_RUNNER_SHUTDOWN_TIMEOUT_SECONDS",
        default=30,
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
        alias="WHATSAPP_AUTO_CREATE_ON_STARTUP", default=0
    )
    whatsapp_webhook_secret: str = Field(alias="WHATSAPP_WEBHOOK_SECRET", default="")
    evolution_api_url: str = Field(alias="EVOLUTION_API_URL", default="")
    evolution_api_key: str = Field(alias="EVOLUTION_API_KEY", default="")

    google_oauth_client_id: str = Field(alias="GOOGLE_OAUTH_CLIENT_ID", default="")
    google_oauth_client_secret: str = Field(alias="GOOGLE_OAUTH_CLIENT_SECRET", default="")
    primary_provider: str = Field(alias="PRIMARY_PROVIDER", default="gemini")
    gemini_model: str = Field(alias="GEMINI_MODEL", default="gemini-2.5-flash")
    gemini_code_assist_token_path: str = Field(
        alias="GEMINI_CODE_ASSIST_TOKEN_PATH",
        default="~/.config/gemini-cli-oauth/token.json",
    )
    gemini_cli_timeout_seconds: int = Field(alias="GEMINI_CLI_TIMEOUT_SECONDS", default=120)
    gemini_code_assist_plan_tier: str = Field(alias="GEMINI_CODE_ASSIST_PLAN_TIER", default="free")
    gemini_code_assist_requests_per_minute: int = Field(
        alias="GEMINI_CODE_ASSIST_REQUESTS_PER_MINUTE",
        default=0,
    )
    gemini_code_assist_requests_per_day: int = Field(
        alias="GEMINI_CODE_ASSIST_REQUESTS_PER_DAY",
        default=0,
    )
    gemini_quota_cooldown_default_seconds: int = Field(
        alias="GEMINI_QUOTA_COOLDOWN_DEFAULT_SECONDS",
        default=60,
    )

    sglang_base_url: str = Field(alias="SGLANG_BASE_URL", default="http://localhost:30000/v1")
    sglang_model: str = Field(alias="SGLANG_MODEL", default="openai/gpt-oss-120b")
    sglang_timeout_seconds: int = Field(alias="SGLANG_TIMEOUT_SECONDS", default=600)

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
        alias="STATE_EXTRACTION_TIMEOUT_SECONDS", default=15
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
    memory_tiers_enabled: int = Field(alias="MEMORY_TIERS_ENABLED", default=0)
    memory_importance_enabled: int = Field(alias="MEMORY_IMPORTANCE_ENABLED", default=0)
    memory_graph_enabled: int = Field(alias="MEMORY_GRAPH_ENABLED", default=0)
    memory_review_queue_enabled: int = Field(alias="MEMORY_REVIEW_QUEUE_ENABLED", default=1)
    memory_failure_bridge_enabled: int = Field(alias="MEMORY_FAILURE_BRIDGE_ENABLED", default=1)
    memory_sentence_transformers_model: str = Field(
        alias="MEMORY_SENTENCE_TRANSFORMERS_MODEL",
        default="all-MiniLM-L6-v2",
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
    exec_host_timeout_max_seconds: int = Field(alias="EXEC_HOST_TIMEOUT_MAX_SECONDS", default=120)
    exec_host_log_dir: str = Field(alias="EXEC_HOST_LOG_DIR", default="/var/lib/agent/exec")
    exec_host_env_allowlist: str = Field(
        alias="EXEC_HOST_ENV_ALLOWLIST", default="PATH,HOME,LANG,LC_ALL,TZ"
    )
    exec_host_allowed_cwd_prefixes: str = Field(
        alias="EXEC_HOST_ALLOWED_CWD_PREFIXES",
        default="/srv/agent-framework,/tmp,/home/justin/jarvis",
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
        "WHATSAPP_VERIFY_TOKEN": settings.whatsapp_verify_token,
        "WHATSAPP_ACCESS_TOKEN": settings.whatsapp_access_token,
        "WHATSAPP_PHONE_NUMBER_ID": settings.whatsapp_phone_number_id,
        "GOOGLE_OAUTH_CLIENT_ID": settings.google_oauth_client_id,
        "GOOGLE_OAUTH_CLIENT_SECRET": settings.google_oauth_client_secret,
        "PRIMARY_PROVIDER": settings.primary_provider,
        "GEMINI_MODEL": settings.gemini_model,
        "SGLANG_BASE_URL": settings.sglang_base_url,
        "SGLANG_MODEL": settings.sglang_model,
        "OLLAMA_BASE_URL": settings.ollama_base_url,
        "OLLAMA_EMBED_MODEL": settings.ollama_embed_model,
        "SEARXNG_BASE_URL": settings.searxng_base_url,
        "ADMIN_WHATSAPP_IDS": settings.admin_whatsapp_ids,
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
