"""Task registration and singleton accessors."""

from __future__ import annotations

from jarvis.config import get_settings
from jarvis.tasks.periodic import PeriodicScheduler
from jarvis.tasks.runner import TaskRunner

_task_runner: TaskRunner | None = None
_periodic_scheduler: PeriodicScheduler | None = None


def _register_tasks(runner: TaskRunner) -> None:
    from jarvis.tasks import (
        agent,
        backup,
        channel,
        github,
        maintenance,
        memory,
        onboarding,
        scheduler,
        selfupdate,
        system,
    )

    runner.register("jarvis.tasks.agent.agent_step", agent.agent_step)
    runner.register("jarvis.tasks.backup.create_backup", backup.create_backup)
    runner.register("jarvis.tasks.channel.send_channel_message", channel.send_channel_message)
    runner.register("jarvis.tasks.channel.send_whatsapp_message", channel.send_whatsapp_message)
    runner.register(
        "jarvis.tasks.github.github_issue_sync_bug_report",
        github.github_issue_sync_bug_report,
    )
    runner.register("jarvis.tasks.github.github_pr_summary", github.github_pr_summary)
    runner.register("jarvis.tasks.github.github_pr_chat", github.github_pr_chat)
    runner.register(
        "jarvis.tasks.maintenance.run_local_maintenance",
        maintenance.run_local_maintenance,
    )
    runner.register(
        "jarvis.tasks.maintenance.maintenance_heartbeat",
        maintenance.maintenance_heartbeat,
    )
    runner.register("jarvis.tasks.memory.index_event", memory.index_event)
    runner.register("jarvis.tasks.memory.compact_thread", memory.compact_thread)
    runner.register("jarvis.tasks.memory.periodic_compaction", memory.periodic_compaction)
    runner.register("jarvis.tasks.onboarding.onboarding_step", onboarding.onboarding_step)
    runner.register("jarvis.tasks.scheduler.scheduler_tick", scheduler.scheduler_tick)
    runner.register("jarvis.tasks.selfupdate.self_update_propose", selfupdate.self_update_propose)
    runner.register("jarvis.tasks.selfupdate.self_update_validate", selfupdate.self_update_validate)
    runner.register("jarvis.tasks.selfupdate.self_update_test", selfupdate.self_update_test)
    runner.register("jarvis.tasks.selfupdate.self_update_apply", selfupdate.self_update_apply)
    runner.register("jarvis.tasks.selfupdate.self_update_rollback", selfupdate.self_update_rollback)
    runner.register("jarvis.tasks.system.rotate_unlock_code", system.rotate_unlock_code)
    runner.register("jarvis.tasks.system.system_restart", system.system_restart)
    runner.register("jarvis.tasks.system.reload_settings_cache", system.reload_settings_cache)
    runner.register("jarvis.tasks.system.db_optimize", system.db_optimize)
    runner.register("jarvis.tasks.system.db_integrity_check", system.db_integrity_check)
    runner.register("jarvis.tasks.system.db_vacuum", system.db_vacuum)


def get_task_runner() -> TaskRunner:
    global _periodic_scheduler, _task_runner
    if _task_runner is None or _task_runner._shutdown.is_set():  # type: ignore[attr-defined]
        settings = get_settings()
        _task_runner = TaskRunner(max_concurrent=int(settings.task_runner_max_concurrent))
        _register_tasks(_task_runner)
        _periodic_scheduler = None
    return _task_runner


def get_periodic_scheduler() -> PeriodicScheduler:
    global _periodic_scheduler
    if _periodic_scheduler is None:
        settings = get_settings()
        scheduler = PeriodicScheduler(get_task_runner())
        scheduler.add("jarvis.tasks.scheduler.scheduler_tick", 60)
        scheduler.add("jarvis.tasks.system.rotate_unlock_code", 600)
        scheduler.add("jarvis.tasks.backup.create_backup", 900)
        scheduler.add("jarvis.tasks.memory.periodic_compaction", 600)
        scheduler.add("jarvis.tasks.system.db_optimize", 86400)
        scheduler.add("jarvis.tasks.system.db_integrity_check", 604800)
        scheduler.add("jarvis.tasks.system.db_vacuum", 2592000)
        if settings.maintenance_enabled == 1 and settings.maintenance_interval_seconds > 0:
            scheduler.add(
                "jarvis.tasks.maintenance.run_local_maintenance",
                float(settings.maintenance_interval_seconds),
            )
        if settings.maintenance_heartbeat_interval_seconds > 0:
            scheduler.add(
                "jarvis.tasks.maintenance.maintenance_heartbeat",
                float(settings.maintenance_heartbeat_interval_seconds),
            )
        _periodic_scheduler = scheduler
    return _periodic_scheduler


def is_periodic_scheduler_configured() -> bool:
    return _periodic_scheduler is not None
