"""Env var category definitions for the .env setup wizard."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EnvVarDef:
    name: str
    description: str
    default: str = ""
    secret: bool = False
    required_for_dev: bool = False


@dataclass(frozen=True, slots=True)
class EnvGroup:
    title: str
    description: str
    vars: list[EnvVarDef] = field(default_factory=list)
    required: bool = True


ENV_GROUPS: list[EnvGroup] = [
    EnvGroup(
        title="Core",
        description="Basic application settings.",
        required=True,
        vars=[
            EnvVarDef("APP_ENV", "Environment (dev/prod)", default="dev", required_for_dev=True),
            EnvVarDef(
                "APP_DB",
                "Absolute path to SQLite database file",
                default="/home/justin/jarvis/app.db",
                required_for_dev=True,
            ),
            EnvVarDef("LOG_LEVEL", "Logging level", default="INFO", required_for_dev=True),
        ],
    ),
    EnvGroup(
        title="Task Runner",
        description="In-process async task runner settings.",
        required=True,
        vars=[
            EnvVarDef(
                "TASK_RUNNER_MAX_CONCURRENT",
                "Maximum concurrent in-process background tasks",
                default="20",
                required_for_dev=True,
            ),
            EnvVarDef(
                "TASK_RUNNER_SHUTDOWN_TIMEOUT_SECONDS",
                "Shutdown drain timeout for in-flight tasks",
                default="30",
                required_for_dev=True,
            ),
        ],
    ),
    EnvGroup(
        title="WhatsApp",
        description="WhatsApp Business API credentials. Skip for local-only development.",
        required=False,
        vars=[
            EnvVarDef(
                "WHATSAPP_VERIFY_TOKEN",
                "Webhook verify token",
                default="dev-verify-token",
                secret=True,
            ),
            EnvVarDef("WHATSAPP_ACCESS_TOKEN", "Graph API access token", secret=True),
            EnvVarDef("WHATSAPP_PHONE_NUMBER_ID", "Phone number ID from Meta dashboard"),
        ],
    ),
    EnvGroup(
        title="Google / Gemini",
        description="Google OAuth + Gemini model. Skip for local-only development.",
        required=False,
        vars=[
            EnvVarDef(
                "PRIMARY_PROVIDER",
                "Primary model provider (gemini or sglang)",
                default="gemini",
            ),
            EnvVarDef("GOOGLE_OAUTH_CLIENT_ID", "OAuth client ID", secret=True),
            EnvVarDef("GOOGLE_OAUTH_CLIENT_SECRET", "OAuth client secret", secret=True),
            EnvVarDef("GEMINI_MODEL", "Gemini model name", default="gemini-2.5-flash"),
            EnvVarDef(
                "GEMINI_CODE_ASSIST_PLAN_TIER",
                "Plan tier (free, pro, ultra, standard, enterprise)",
                default="free",
            ),
            EnvVarDef(
                "GEMINI_CODE_ASSIST_REQUESTS_PER_MINUTE",
                "Override requests/minute (0 uses tier default)",
                default="0",
            ),
            EnvVarDef(
                "GEMINI_CODE_ASSIST_REQUESTS_PER_DAY",
                "Override requests/day (0 uses tier default)",
                default="0",
            ),
            EnvVarDef(
                "GEMINI_CODE_ASSIST_TOKEN_PATH",
                "Code Assist token cache path",
                default="~/.config/gemini-cli-oauth/token.json",
            ),
            EnvVarDef(
                "GEMINI_CLI_TIMEOUT_SECONDS",
                "Code Assist request timeout in seconds",
                default="120",
            ),
            EnvVarDef(
                "GEMINI_QUOTA_COOLDOWN_DEFAULT_SECONDS",
                "Fallback cooldown after quota errors when reset is unknown",
                default="60",
            ),
        ],
    ),
    EnvGroup(
        title="Local LLM (SGLang)",
        description="SGLang inference server for local model routing.",
        required=True,
        vars=[
            EnvVarDef(
                "SGLANG_BASE_URL",
                "SGLang OpenAI-compatible base URL",
                default="http://localhost:30000/v1",
                required_for_dev=True,
            ),
            EnvVarDef(
                "SGLANG_MODEL",
                "Model identifier for SGLang",
                default="openai/gpt-oss-120b",
                required_for_dev=True,
            ),
            EnvVarDef(
                "SGLANG_TIMEOUT_SECONDS",
                "SGLang request timeout in seconds",
                default="600",
                required_for_dev=True,
            ),
        ],
    ),
    EnvGroup(
        title="Embeddings (Ollama)",
        description="Ollama server for text embeddings used by the memory service.",
        required=True,
        vars=[
            EnvVarDef(
                "OLLAMA_BASE_URL",
                "Ollama server URL",
                default="http://localhost:11434",
                required_for_dev=True,
            ),
            EnvVarDef(
                "OLLAMA_EMBED_MODEL",
                "Embedding model name",
                default="nomic-embed-text",
                required_for_dev=True,
            ),
            EnvVarDef(
                "MEMORY_EMBED_DIMS",
                "Embedding vector dimensions",
                default="768",
                required_for_dev=True,
            ),
            EnvVarDef(
                "SQLITE_VEC_EXTENSION_PATH",
                "Path to sqlite-vec extension (.so/.dylib)",
            ),
        ],
    ),
    EnvGroup(
        title="Search (SearXNG)",
        description="SearXNG meta-search engine instance.",
        required=True,
        vars=[
            EnvVarDef(
                "SEARXNG_BASE_URL",
                "SearXNG instance URL",
                default="http://localhost:8080",
                required_for_dev=True,
            ),
            EnvVarDef(
                "SEARXNG_API_KEY",
                "Optional API key/header value for protected SearXNG deployments",
                secret=True,
            ),
            EnvVarDef(
                "SEARXNG_API_KEY_HEADER",
                "Header name used with SEARXNG_API_KEY",
                default="X-API-Key",
            ),
            EnvVarDef(
                "WEB_SEARCH_USER_AGENT",
                "User-Agent header used by web_search requests",
                default="Mozilla/5.0 (compatible; Jarvis/1.0; +https://localhost)",
            ),
        ],
    ),
    EnvGroup(
        title="Backup & Alerting",
        description="S3-compatible backup storage, PagerDuty, and Slack. Skip for dev.",
        required=False,
        vars=[
            EnvVarDef("BACKUP_S3_ENDPOINT", "S3-compatible endpoint URL"),
            EnvVarDef("BACKUP_S3_BUCKET", "Bucket name", default="jarvis-prod-backups"),
            EnvVarDef("BACKUP_S3_REGION", "Region", default="auto"),
            EnvVarDef("BACKUP_S3_ACCESS_KEY_ID", "S3 access key", secret=True),
            EnvVarDef("BACKUP_S3_SECRET_ACCESS_KEY", "S3 secret key", secret=True),
            EnvVarDef("BACKUP_LOCAL_DIR", "Local backup directory", default="/tmp/jarvis_backups"),
            EnvVarDef("PAGERDUTY_ROUTING_KEY", "PagerDuty routing key", secret=True),
            EnvVarDef("ALERT_SLACK_WEBHOOK_URL", "Slack webhook URL", secret=True),
        ],
    ),
    EnvGroup(
        title="GitHub PR Automation",
        description="Optional GitHub webhook + PR summary commenter integration.",
        required=False,
        vars=[
            EnvVarDef("GITHUB_TOKEN", "GitHub App installation token or PAT", secret=True),
            EnvVarDef("GITHUB_WEBHOOK_SECRET", "GitHub webhook signing secret", secret=True),
            EnvVarDef(
                "GITHUB_API_BASE_URL",
                "GitHub API base URL",
                default="https://api.github.com",
            ),
            EnvVarDef(
                "GITHUB_REPO_ALLOWLIST",
                "Optional CSV allowlist (supports wildcards, e.g. my-org/*)",
                default="",
            ),
            EnvVarDef(
                "GITHUB_BOT_LOGIN",
                "Bot login name to detect mentions and avoid self-replies",
                default="jarvis",
            ),
            EnvVarDef(
                "GITHUB_PR_SUMMARY_ENABLED",
                "Enable PR summary webhook task (0/1)",
                default="0",
            ),
            EnvVarDef(
                "GITHUB_ISSUE_SYNC_ENABLED",
                "Enable bug/feature sync to GitHub issues (0/1)",
                default="0",
            ),
            EnvVarDef(
                "GITHUB_ISSUE_SYNC_REPO",
                "GitHub repo for issue sync (owner/repo)",
                default="",
            ),
            EnvVarDef(
                "GITHUB_ISSUE_LABELS_BUG",
                "CSV labels for synced bug issues",
                default="jarvis,bug",
            ),
            EnvVarDef(
                "GITHUB_ISSUE_LABELS_FEATURE",
                "CSV labels for synced feature issues",
                default="jarvis,feature-request",
            ),
        ],
    ),
    EnvGroup(
        title="Advanced",
        description="Tuning thresholds, exec host, admin settings. Skip for defaults.",
        required=False,
        vars=[
            EnvVarDef("TRACE_SAMPLE_RATE", "Trace sample rate (0.0-1.0)", default="1.0"),
            EnvVarDef("MAINTENANCE_ENABLED", "Enable local maintenance loop (0/1)", default="0"),
            EnvVarDef(
                "MAINTENANCE_HEARTBEAT_INTERVAL_SECONDS",
                "Heartbeat schedule interval in seconds (0 disables heartbeat)",
                default="300",
            ),
            EnvVarDef(
                "MAINTENANCE_INTERVAL_SECONDS",
                "Maintenance schedule interval in seconds (0 disables schedule)",
                default="0",
            ),
            EnvVarDef(
                "MAINTENANCE_COMMANDS",
                "Maintenance commands separated by \\n (escaped) or real newlines",
                default="make lint\\nmake typecheck",
            ),
            EnvVarDef(
                "MAINTENANCE_TIMEOUT_SECONDS",
                "Per-command timeout for maintenance checks",
                default="1800",
            ),
            EnvVarDef(
                "MAINTENANCE_CREATE_BUGS",
                "Create bug records for maintenance failures (0/1)",
                default="1",
            ),
            EnvVarDef(
                "MAINTENANCE_WORKDIR",
                "Optional working directory for maintenance commands",
                default="",
            ),
            EnvVarDef("COMPACTION_EVERY_N_EVENTS", "Event compaction interval", default="25"),
            EnvVarDef(
                "COMPACTION_INTERVAL_SECONDS", "Compaction time interval", default="600"
            ),
            EnvVarDef(
                "PROMPT_BUDGET_GEMINI_TOKENS", "Gemini token budget", default="200000"
            ),
            EnvVarDef(
                "PROMPT_BUDGET_SGLANG_TOKENS", "SGLang token budget", default="110000"
            ),
            EnvVarDef("ADMIN_WHATSAPP_IDS", "Admin phone numbers (comma-separated)"),
            EnvVarDef(
                "ADMIN_UNLOCK_CODE_PATH",
                "Path for admin unlock code file",
                default="/tmp/jarvis_admin_unlock_code",
            ),
            EnvVarDef(
                "ADMIN_UNLOCK_CODE_TTL_MINUTES", "Unlock code TTL in minutes", default="10"
            ),
        ],
    ),
]
