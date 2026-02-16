"""Application configuration contract."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = Field(alias="APP_ENV", default="dev")
    app_db: str = Field(alias="APP_DB", default="/tmp/jarvis.db")
    broker_url: str = Field(alias="BROKER_URL", default="amqp://guest:guest@localhost:5672//")
    result_backend: str = Field(alias="RESULT_BACKEND", default="rpc://")
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
    scheduler_max_catchup: int = Field(alias="SCHEDULER_MAX_CATCHUP", default=10)
    rabbitmq_mgmt_url: str = Field(alias="RABBITMQ_MGMT_URL", default="")
    rabbitmq_mgmt_user: str = Field(alias="RABBITMQ_MGMT_USER", default="")
    rabbitmq_mgmt_password: str = Field(alias="RABBITMQ_MGMT_PASSWORD", default="")
    restart_drain_timeout_seconds: int = Field(alias="RESTART_DRAIN_TIMEOUT_SECONDS", default=20)
    restart_drain_poll_seconds: int = Field(alias="RESTART_DRAIN_POLL_SECONDS", default=2)
    restart_command: str = Field(alias="RESTART_COMMAND", default="")
    lockdown_readyz_fail_threshold: int = Field(alias="LOCKDOWN_READYZ_FAIL_THRESHOLD", default=3)
    lockdown_rollback_threshold: int = Field(alias="LOCKDOWN_ROLLBACK_THRESHOLD", default=2)
    lockdown_rollback_window_minutes: int = Field(
        alias="LOCKDOWN_ROLLBACK_WINDOW_MINUTES", default=30
    )
    queue_threshold_agent_priority: int = Field(alias="QUEUE_THRESHOLD_AGENT_PRIORITY", default=200)
    queue_threshold_agent_default: int = Field(alias="QUEUE_THRESHOLD_AGENT_DEFAULT", default=500)
    queue_threshold_tools_io: int = Field(alias="QUEUE_THRESHOLD_TOOLS_IO", default=500)
    queue_threshold_local_llm: int = Field(alias="QUEUE_THRESHOLD_LOCAL_LLM", default=10)
    lockdown_exec_host_fail_threshold: int = Field(
        alias="LOCKDOWN_EXEC_HOST_FAIL_THRESHOLD", default=5
    )
    lockdown_exec_host_fail_window_minutes: int = Field(
        alias="LOCKDOWN_EXEC_HOST_FAIL_WINDOW_MINUTES", default=10
    )

    whatsapp_verify_token: str = Field(alias="WHATSAPP_VERIFY_TOKEN", default="dev-verify-token")
    whatsapp_access_token: str = Field(alias="WHATSAPP_ACCESS_TOKEN", default="")
    whatsapp_phone_number_id: str = Field(alias="WHATSAPP_PHONE_NUMBER_ID", default="")

    google_oauth_client_id: str = Field(alias="GOOGLE_OAUTH_CLIENT_ID", default="")
    google_oauth_client_secret: str = Field(alias="GOOGLE_OAUTH_CLIENT_SECRET", default="")
    google_oauth_refresh_token: str = Field(alias="GOOGLE_OAUTH_REFRESH_TOKEN", default="")
    gemini_provider: str = Field(alias="GEMINI_PROVIDER", default="google-gemini-cli")
    gemini_model: str = Field(alias="GEMINI_MODEL", default="gemini-3-flash-preview")
    gemini_cli_binary: str = Field(alias="GEMINI_CLI_BINARY", default="gemini")
    gemini_cli_home_dir: str = Field(alias="GEMINI_CLI_HOME_DIR", default="")
    gemini_cli_timeout_seconds: int = Field(alias="GEMINI_CLI_TIMEOUT_SECONDS", default=120)

    sglang_base_url: str = Field(alias="SGLANG_BASE_URL", default="http://localhost:30000/v1")
    sglang_model: str = Field(alias="SGLANG_MODEL", default="openai/gpt-oss-120b")
    sglang_timeout_seconds: int = Field(alias="SGLANG_TIMEOUT_SECONDS", default=600)

    ollama_base_url: str = Field(alias="OLLAMA_BASE_URL", default="http://localhost:11434")
    ollama_embed_model: str = Field(alias="OLLAMA_EMBED_MODEL", default="nomic-embed-text")
    memory_embed_dims: int = Field(alias="MEMORY_EMBED_DIMS", default=768)
    sqlite_vec_extension_path: str = Field(alias="SQLITE_VEC_EXTENSION_PATH", default="")

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
    github_token: str = Field(alias="GITHUB_TOKEN", default="")
    github_webhook_secret: str = Field(alias="GITHUB_WEBHOOK_SECRET", default="")
    github_api_base_url: str = Field(alias="GITHUB_API_BASE_URL", default="https://api.github.com")
    github_repo_allowlist: str = Field(alias="GITHUB_REPO_ALLOWLIST", default="")
    github_bot_login: str = Field(alias="GITHUB_BOT_LOGIN", default="jarvis")
    github_pr_summary_enabled: int = Field(alias="GITHUB_PR_SUMMARY_ENABLED", default=0)
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
        "BROKER_URL": settings.broker_url,
        "RESULT_BACKEND": settings.result_backend,
        "WHATSAPP_VERIFY_TOKEN": settings.whatsapp_verify_token,
        "WHATSAPP_ACCESS_TOKEN": settings.whatsapp_access_token,
        "WHATSAPP_PHONE_NUMBER_ID": settings.whatsapp_phone_number_id,
        "GOOGLE_OAUTH_CLIENT_ID": settings.google_oauth_client_id,
        "GOOGLE_OAUTH_CLIENT_SECRET": settings.google_oauth_client_secret,
        "GOOGLE_OAUTH_REFRESH_TOKEN": settings.google_oauth_refresh_token,
        "GEMINI_MODEL": settings.gemini_model,
        "SGLANG_BASE_URL": settings.sglang_base_url,
        "SGLANG_MODEL": settings.sglang_model,
        "OLLAMA_BASE_URL": settings.ollama_base_url,
        "OLLAMA_EMBED_MODEL": settings.ollama_embed_model,
        "SEARXNG_BASE_URL": settings.searxng_base_url,
        "ADMIN_WHATSAPP_IDS": settings.admin_whatsapp_ids,
        "RABBITMQ_MGMT_URL": settings.rabbitmq_mgmt_url,
        "RABBITMQ_MGMT_USER": settings.rabbitmq_mgmt_user,
        "RABBITMQ_MGMT_PASSWORD": settings.rabbitmq_mgmt_password,
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
    if not settings.app_db.startswith("/"):
        missing.append("APP_DB(absolute path required)")

    if missing:
        keys = ", ".join(sorted(set(missing)))
        raise ValueError(f"invalid production configuration: {keys}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
