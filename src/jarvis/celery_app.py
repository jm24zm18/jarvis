"""Celery application and queue routing."""

from celery import Celery
from celery.signals import beat_init, worker_init

from jarvis.config import get_settings, validate_settings_for_env

settings = get_settings()
validate_settings_for_env(settings)

celery_app = Celery(
    "jarvis",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=[
        "jarvis.tasks.agent",
        "jarvis.tasks.backup",
        "jarvis.tasks.channel",
        "jarvis.tasks.github",
        "jarvis.tasks.memory",
        "jarvis.tasks.monitoring",
        "jarvis.tasks.onboarding",
        "jarvis.tasks.scheduler",
        "jarvis.tasks.selfupdate",
        "jarvis.tasks.system",
    ],
)

celery_app.conf.update(
    task_default_queue="agent_default",
    task_routes={
        "jarvis.tasks.agent.agent_step": {"queue": "agent_priority"},
        "jarvis.tasks.onboarding.onboarding_step": {"queue": "agent_priority"},
        "jarvis.tasks.channel.send_whatsapp_message": {"queue": "tools_io"},
        "jarvis.tasks.channel.send_channel_message": {"queue": "tools_io"},
        "jarvis.tasks.github.*": {"queue": "tools_io"},
        "jarvis.tasks.scheduler.scheduler_tick": {"queue": "agent_default"},
        "jarvis.tasks.selfupdate.*": {"queue": "agent_default"},
        "jarvis.tasks.memory.index_event": {"queue": "tools_io"},
        "jarvis.tasks.system.*": {"queue": "agent_default"},
        "jarvis.tasks.backup.*": {"queue": "tools_io"},
        "jarvis.tasks.monitoring.*": {"queue": "agent_default"},
    },
    beat_schedule={
        "scheduler-tick-60s": {
            "task": "jarvis.tasks.scheduler.scheduler_tick",
            "schedule": 60.0,
        },
        "rotate-unlock-code-10m": {
            "task": "jarvis.tasks.system.rotate_unlock_code",
            "schedule": 600.0,
        },
        "create-backup-15m": {
            "task": "jarvis.tasks.backup.create_backup",
            "schedule": 900.0,
        },
        "queue-backpressure-monitor-60s": {
            "task": "jarvis.tasks.monitoring.monitor_queue_backpressure",
            "schedule": 60.0,
        },
        "periodic-compaction-10m": {
            "task": "jarvis.tasks.memory.periodic_compaction",
            "schedule": 600.0,
        },
        "db-optimize-daily": {
            "task": "jarvis.tasks.system.db_optimize",
            "schedule": 86400.0,
        },
        "db-integrity-check-weekly": {
            "task": "jarvis.tasks.system.db_integrity_check",
            "schedule": 604800.0,
        },
        "db-vacuum-monthly": {
            "task": "jarvis.tasks.system.db_vacuum",
            "schedule": 2592000.0,
        },
    },
    task_acks_late=True,
)


def _validate_runtime_settings(**_: object) -> None:
    validate_settings_for_env(get_settings())


def _register_channels(**_: object) -> None:
    from jarvis.channels.registry import register_channel
    from jarvis.channels.whatsapp.adapter import WhatsAppAdapter

    register_channel(WhatsAppAdapter())


worker_init.connect(_validate_runtime_settings)
worker_init.connect(_register_channels)
beat_init.connect(_validate_runtime_settings)
