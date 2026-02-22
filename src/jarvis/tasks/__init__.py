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
        agent_recovery,
        backup,
        channel,
        dependency_steward,
        events,
        feature_build,
        followups,
        github,
        maintenance,
        memory,
        onboarding,
        release_candidate,
        scheduler,
        selfupdate,
        story_runner,
        system,
    )

    runner.register("jarvis.tasks.agent.agent_step", agent.agent_step)
    runner.register(
        "jarvis.tasks.agent_recovery.reap_stale_agent_runs",
        agent_recovery.reap_stale_agent_runs,
    )
    runner.register("jarvis.tasks.backup.create_backup", backup.create_backup)
    runner.register("jarvis.tasks.channel.send_channel_message", channel.send_channel_message)
    runner.register("jarvis.tasks.channel.send_whatsapp_message", channel.send_whatsapp_message)
    runner.register("jarvis.tasks.channel.cleanup_stale_typing", channel.cleanup_stale_typing)
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
    runner.register(
        "jarvis.tasks.maintenance.compute_system_fitness",
        maintenance.compute_system_fitness,
    )
    runner.register(
        "jarvis.tasks.followups.followup_heartbeat_tick",
        followups.followup_heartbeat_tick,
    )
    runner.register("jarvis.tasks.memory.index_event", memory.index_event)
    runner.register("jarvis.tasks.memory.compact_thread", memory.compact_thread)
    runner.register("jarvis.tasks.memory.extract_thread_state", memory.extract_thread_state)
    runner.register("jarvis.tasks.memory.periodic_compaction", memory.periodic_compaction)
    runner.register("jarvis.tasks.memory.migrate_tiers", memory.migrate_tiers)
    runner.register("jarvis.tasks.memory.prune_adaptive", memory.prune_adaptive)
    runner.register("jarvis.tasks.memory.sync_failure_capsules", memory.sync_failure_capsules)
    runner.register("jarvis.tasks.memory.evaluate_consistency", memory.evaluate_consistency)
    runner.register("jarvis.tasks.onboarding.onboarding_step", onboarding.onboarding_step)
    runner.register(
        "jarvis.tasks.dependency_steward.run_dependency_steward",
        dependency_steward.run_dependency_steward,
    )
    runner.register(
        "jarvis.tasks.release_candidate.build_release_candidate",
        release_candidate.build_release_candidate,
    )
    runner.register(
        "jarvis.tasks.feature_build.run_feature_build",
        feature_build.run_feature_build,
    )
    runner.register(
        "jarvis.tasks.feature_build.reconcile_stale_feature_build_runs",
        feature_build.reconcile_stale_feature_build_runs,
    )
    runner.register(
        "jarvis.tasks.feature_build.dispatch_due_feature_build_retries",
        feature_build.dispatch_due_feature_build_retries,
    )
    runner.register("jarvis.tasks.scheduler.scheduler_tick", scheduler.scheduler_tick)
    runner.register("jarvis.tasks.selfupdate.self_update_propose", selfupdate.self_update_propose)
    runner.register("jarvis.tasks.selfupdate.self_update_validate", selfupdate.self_update_validate)
    runner.register("jarvis.tasks.selfupdate.self_update_test", selfupdate.self_update_test)
    runner.register("jarvis.tasks.selfupdate.self_update_open_pr", selfupdate.self_update_open_pr)
    runner.register("jarvis.tasks.selfupdate.self_update_apply", selfupdate.self_update_apply)
    runner.register("jarvis.tasks.selfupdate.self_update_rollback", selfupdate.self_update_rollback)
    runner.register("jarvis.tasks.story_runner.run_story_pack", story_runner.run_story_pack)
    runner.register("jarvis.tasks.events.run_event_maintenance", events.run_event_maintenance)
    runner.register("jarvis.tasks.system.rotate_unlock_code", system.rotate_unlock_code)
    runner.register("jarvis.tasks.system.system_restart", system.system_restart)
    runner.register("jarvis.tasks.system.reload_settings_cache", system.reload_settings_cache)
    runner.register("jarvis.tasks.system.db_optimize", system.db_optimize)
    runner.register("jarvis.tasks.system.db_integrity_check", system.db_integrity_check)
    runner.register("jarvis.tasks.system.db_vacuum", system.db_vacuum)
    runner.register("jarvis.tasks.system.watchdog_stall_check", system.watchdog_stall_check)
    runner.register("jarvis.tasks.system.update_liveness_probe", system.update_liveness_probe)


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
        scheduler.add(
            "jarvis.tasks.agent_recovery.reap_stale_agent_runs",
            float(max(5, int(settings.agent_run_reaper_interval_seconds))),
        )
        scheduler.add("jarvis.tasks.scheduler.scheduler_tick", 60)
        scheduler.add("jarvis.tasks.system.rotate_unlock_code", 600)
        scheduler.add("jarvis.tasks.backup.create_backup", 900)
        scheduler.add("jarvis.tasks.memory.periodic_compaction", 600)
        scheduler.add("jarvis.tasks.memory.sync_failure_capsules", 1800)
        scheduler.add("jarvis.tasks.memory.migrate_tiers", 21600)
        scheduler.add("jarvis.tasks.memory.prune_adaptive", 86400)
        scheduler.add("jarvis.tasks.memory.evaluate_consistency", 86400)
        scheduler.add("jarvis.tasks.system.db_optimize", 86400)
        scheduler.add("jarvis.tasks.system.db_integrity_check", 604800)
        # Prune old events weekly (configurable via EVENT_RETENTION_DAYS).
        scheduler.add("jarvis.tasks.events.run_event_maintenance", 604800)
        scheduler.add("jarvis.tasks.system.db_vacuum", 2592000)
        scheduler.add("jarvis.tasks.channel.cleanup_stale_typing", 10)
        scheduler.add("jarvis.tasks.feature_build.reconcile_stale_feature_build_runs", 60)
        scheduler.add(
            "jarvis.tasks.feature_build.dispatch_due_feature_build_retries",
            float(max(5, int(settings.feature_build_retry_dispatch_interval_seconds))),
        )
        scheduler.add("jarvis.tasks.system.watchdog_stall_check", 30)
        scheduler.add("jarvis.tasks.system.update_liveness_probe", 5)
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
        if settings.followup_heartbeat_interval_seconds > 0:
            scheduler.add(
                "jarvis.tasks.followups.followup_heartbeat_tick",
                float(settings.followup_heartbeat_interval_seconds),
            )
        # Run fitness compute every 30 minutes so SLO gate is always current.
        scheduler.add("jarvis.tasks.maintenance.compute_system_fitness", 1800)
        if int(settings.dependency_steward_enabled) == 1:
            scheduler.add("jarvis.tasks.dependency_steward.run_dependency_steward", 604800)
        if int(settings.release_candidate_agent_enabled) == 1:
            scheduler.add("jarvis.tasks.release_candidate.build_release_candidate", 86400)
        _periodic_scheduler = scheduler
    return _periodic_scheduler


def is_periodic_scheduler_configured() -> bool:
    return _periodic_scheduler is not None


def stale_periodic_jobs(stale_multiplier: float = 2.5) -> list[dict[str, object]]:
    scheduler = _periodic_scheduler
    if scheduler is None:
        return []
    stale: list[dict[str, object]] = []
    for row in scheduler.status_snapshot():
        interval = float(row.get("interval_seconds") or 0.0)
        if interval <= 0:
            continue
        age = row.get("last_run_age_seconds")
        next_in = float(row.get("next_run_in_seconds") or 0.0)
        if age is None:
            if next_in < (-interval * stale_multiplier):
                stale.append(
                    {
                        "name": str(row.get("name", "")),
                        "reason": "never_ran",
                        "next_run_in_seconds": next_in,
                        "interval_seconds": interval,
                    }
                )
            continue
        age_f = float(age)
        if age_f > (interval * stale_multiplier):
            stale.append(
                {
                    "name": str(row.get("name", "")),
                    "reason": "late",
                    "last_run_age_seconds": age_f,
                    "interval_seconds": interval,
                }
            )
    return stale
