# API Reference

Generated from FastAPI OpenAPI via `scripts/generate_api_docs.py`.
Regenerate with `make docs-generate`.
For request/response semantics and operator workflows, see `docs/api-usage-guide.md` and `docs/channel-reply-approvals.md`.

Auth levels:
- `public`: no bearer token required
- `auth`: authenticated user token required
- `admin`: authenticated admin token required
- `ws-token`: token required in WebSocket query string

| Method | Path | Auth | Operation ID | Request | Responses |
| --- | --- | --- | --- | --- | --- |
| `GET` | `/api/v1/agents` | `auth` | `list_agents_api_v1_agents_get` | `-` | `200, 422` |
| `GET` | `/api/v1/agents/{agent_id}` | `auth` | `get_agent_api_v1_agents__agent_id__get` | `-` | `200, 422` |
| `GET` | `/api/v1/approvals` | `auth` | `list_approvals_endpoint_api_v1_approvals_get` | `-` | `200, 422` |
| `POST` | `/api/v1/approvals` | `auth` | `create_approval_endpoint_api_v1_approvals_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/approvals/{approval_id}/revoke` | `auth` | `revoke_approval_endpoint_api_v1_approvals__approval_id__revoke_post` | `-` | `200, 422` |
| `POST` | `/api/v1/auth/login` | `public` | `login_api_v1_auth_login_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/auth/logout` | `auth` | `logout_api_v1_auth_logout_post` | `-` | `200, 422` |
| `GET` | `/api/v1/auth/me` | `auth` | `me_api_v1_auth_me_get` | `-` | `200, 422` |
| `GET` | `/api/v1/auth/providers/config` | `auth` | `providers_config_api_v1_auth_providers_config_get` | `-` | `200, 422` |
| `POST` | `/api/v1/auth/providers/config` | `auth` | `update_providers_config_api_v1_auth_providers_config_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/auth/providers/models` | `auth` | `providers_models_api_v1_auth_providers_models_get` | `-` | `200, 422` |
| `GET` | `/api/v1/bugs` | `auth` | `list_bugs_api_v1_bugs_get` | `-` | `200, 422` |
| `POST` | `/api/v1/bugs` | `auth` | `create_bug_api_v1_bugs_post` | `application/json` | `200, 422` |
| `DELETE` | `/api/v1/bugs/{bug_id}` | `auth` | `delete_bug_api_v1_bugs__bug_id__delete` | `-` | `200, 422` |
| `PATCH` | `/api/v1/bugs/{bug_id}` | `auth` | `update_bug_api_v1_bugs__bug_id__patch` | `application/json` | `200, 422` |
| `GET` | `/api/v1/channel-reply-approvals` | `auth` | `list_channel_reply_approvals_api_v1_channel_reply_approvals_get` | `-` | `200, 422` |
| `POST` | `/api/v1/channel-reply-approvals/{request_id}/approve` | `auth` | `approve_channel_reply_api_v1_channel_reply_approvals__request_id__approve_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/channel-reply-approvals/{request_id}/reject` | `auth` | `reject_channel_reply_api_v1_channel_reply_approvals__request_id__reject_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/channel-reply-permissions` | `auth` | `list_channel_reply_permissions_api_v1_channel_reply_permissions_get` | `-` | `200, 422` |
| `POST` | `/api/v1/channel-reply-permissions/revoke` | `auth` | `revoke_channel_reply_permission_api_v1_channel_reply_permissions_revoke_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/channels/telegram/status` | `auth` | `telegram_status_api_v1_channels_telegram_status_get` | `-` | `200, 422` |
| `POST` | `/api/v1/channels/whatsapp/create` | `auth` | `whatsapp_create_api_v1_channels_whatsapp_create_post` | `-` | `200, 422` |
| `POST` | `/api/v1/channels/whatsapp/disconnect` | `auth` | `whatsapp_disconnect_api_v1_channels_whatsapp_disconnect_post` | `-` | `200, 422` |
| `POST` | `/api/v1/channels/whatsapp/pairing-code` | `auth` | `whatsapp_pairing_code_api_v1_channels_whatsapp_pairing_code_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/channels/whatsapp/qrcode` | `auth` | `whatsapp_qrcode_api_v1_channels_whatsapp_qrcode_get` | `-` | `200, 422` |
| `POST` | `/api/v1/channels/whatsapp/reset` | `auth` | `whatsapp_reset_api_v1_channels_whatsapp_reset_post` | `-` | `200, 422` |
| `POST` | `/api/v1/channels/whatsapp/restart` | `auth` | `whatsapp_restart_api_v1_channels_whatsapp_restart_post` | `-` | `200, 422` |
| `GET` | `/api/v1/channels/whatsapp/review-queue` | `auth` | `whatsapp_review_queue_api_v1_channels_whatsapp_review_queue_get` | `-` | `200, 422` |
| `POST` | `/api/v1/channels/whatsapp/review-queue/{review_id}/resolve` | `auth` | `whatsapp_resolve_review_item_api_v1_channels_whatsapp_review_queue__review_id__resolve_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/channels/whatsapp/status` | `auth` | `whatsapp_status_api_v1_channels_whatsapp_status_get` | `-` | `200, 422` |
| `GET` | `/api/v1/events` | `auth` | `search_events_api_v1_events_get` | `-` | `200, 422` |
| `GET` | `/api/v1/events/{event_id}` | `auth` | `get_event_api_v1_events__event_id__get` | `-` | `200, 422` |
| `GET` | `/api/v1/feature-requests` | `auth` | `list_feature_requests_api_v1_feature_requests_get` | `-` | `200, 422` |
| `POST` | `/api/v1/feature-requests` | `auth` | `create_feature_request_api_v1_feature_requests_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/feature-requests/build-runs/reconcile` | `auth` | `reconcile_feature_build_runs_endpoint_api_v1_feature_requests_build_runs_reconcile_post` | `-` | `200, 422` |
| `PATCH` | `/api/v1/feature-requests/{feature_id}/approval` | `auth` | `set_feature_approval_api_v1_feature_requests__feature_id__approval_patch` | `application/json` | `200, 422` |
| `POST` | `/api/v1/feature-requests/{feature_id}/build` | `auth` | `trigger_feature_build_api_v1_feature_requests__feature_id__build_post` | `-` | `200, 422` |
| `GET` | `/api/v1/feature-requests/{feature_id}/build-runs` | `auth` | `list_feature_build_runs_endpoint_api_v1_feature_requests__feature_id__build_runs_get` | `-` | `200, 422` |
| `POST` | `/api/v1/feature-requests/{feature_id}/build-runs/{run_id}/recover-children` | `auth` | `recover_feature_build_children_endpoint_api_v1_feature_requests__feature_id__build_runs__run_id__recover_children_post` | `-` | `200, 422` |
| `POST` | `/api/v1/feature-requests/{feature_id}/split` | `auth` | `split_feature_request_endpoint_api_v1_feature_requests__feature_id__split_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/followups/threads/{thread_id}` | `auth` | `get_followup_status_api_v1_followups_threads__thread_id__get` | `-` | `200, 422` |
| `POST` | `/api/v1/followups/threads/{thread_id}/disable` | `auth` | `disable_followups_api_v1_followups_threads__thread_id__disable_post` | `-` | `200, 422` |
| `POST` | `/api/v1/followups/threads/{thread_id}/enable` | `auth` | `enable_followups_api_v1_followups_threads__thread_id__enable_post` | `-` | `200, 422` |
| `GET` | `/api/v1/governance/agents` | `auth` | `list_agent_governance_api_v1_governance_agents_get` | `-` | `200, 422` |
| `GET` | `/api/v1/governance/audit` | `auth` | `memory_governance_audit_api_v1_governance_audit_get` | `-` | `200, 422` |
| `GET` | `/api/v1/governance/decision-timeline` | `auth` | `decision_timeline_api_v1_governance_decision_timeline_get` | `-` | `200, 422` |
| `GET` | `/api/v1/governance/dependency-steward` | `auth` | `dependency_steward_status_api_v1_governance_dependency_steward_get` | `-` | `200, 422` |
| `GET` | `/api/v1/governance/evolution/items` | `auth` | `evolution_items_api_v1_governance_evolution_items_get` | `-` | `200, 422` |
| `POST` | `/api/v1/governance/evolution/items/{item_id}/status` | `auth` | `evolution_item_set_status_api_v1_governance_evolution_items__item_id__status_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/governance/fitness/history` | `auth` | `fitness_history_api_v1_governance_fitness_history_get` | `-` | `200, 422` |
| `GET` | `/api/v1/governance/fitness/latest` | `auth` | `fitness_latest_api_v1_governance_fitness_latest_get` | `-` | `200, 422` |
| `GET` | `/api/v1/governance/learning-loop` | `auth` | `learning_loop_api_v1_governance_learning_loop_get` | `-` | `200, 422` |
| `GET` | `/api/v1/governance/patch-lifecycle/{trace_id}` | `auth` | `patch_lifecycle_api_v1_governance_patch_lifecycle__trace_id__get` | `-` | `200, 422` |
| `GET` | `/api/v1/governance/release-candidate` | `auth` | `release_candidate_status_api_v1_governance_release_candidate_get` | `-` | `200, 422` |
| `POST` | `/api/v1/governance/reload` | `auth` | `reload_governance_api_v1_governance_reload_post` | `-` | `200, 422` |
| `POST` | `/api/v1/governance/remediations/{remediation_id}/feedback` | `auth` | `remediation_feedback_api_v1_governance_remediations__remediation_id__feedback_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/governance/slo` | `auth` | `governance_slo_api_v1_governance_slo_get` | `-` | `200, 422` |
| `GET` | `/api/v1/governance/slo/history` | `auth` | `governance_slo_history_api_v1_governance_slo_history_get` | `-` | `200, 422` |
| `POST` | `/api/v1/media/upload` | `auth` | `upload_media_api_v1_media_upload_post` | `multipart/form-data` | `200, 422` |
| `GET` | `/api/v1/media/{attachment_id}` | `auth` | `download_media_api_v1_media__attachment_id__get` | `-` | `200, 422` |
| `GET` | `/api/v1/media/{attachment_id}/thumb` | `auth` | `download_thumbnail_api_v1_media__attachment_id__thumb_get` | `-` | `200, 422` |
| `GET` | `/api/v1/memory` | `auth` | `search_memory_api_v1_memory_get` | `-` | `200, 422` |
| `GET` | `/api/v1/memory/consistency` | `auth` | `get_consistency_api_v1_memory_consistency_get` | `-` | `200, 422` |
| `GET` | `/api/v1/memory/export` | `auth` | `memory_export_api_v1_memory_export_get` | `-` | `200, 422` |
| `GET` | `/api/v1/memory/kb` | `auth` | `search_kb_api_v1_memory_kb_get` | `-` | `200, 422` |
| `POST` | `/api/v1/memory/kb` | `auth` | `upsert_kb_api_v1_memory_kb_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/memory/maintenance/run` | `auth` | `memory_maintenance_run_api_v1_memory_maintenance_run_post` | `-` | `200, 422` |
| `GET` | `/api/v1/memory/state/consistency/report` | `auth` | `state_consistency_report_api_v1_memory_state_consistency_report_get` | `-` | `200, 422` |
| `GET` | `/api/v1/memory/state/failures` | `auth` | `state_failures_api_v1_memory_state_failures_get` | `-` | `200, 422` |
| `GET` | `/api/v1/memory/state/graph/{uid}` | `auth` | `state_graph_api_v1_memory_state_graph__uid__get` | `-` | `200, 422` |
| `GET` | `/api/v1/memory/state/review/conflicts` | `auth` | `state_review_conflicts_api_v1_memory_state_review_conflicts_get` | `-` | `200, 422` |
| `POST` | `/api/v1/memory/state/review/{uid}/resolve` | `auth` | `state_review_resolve_api_v1_memory_state_review__uid__resolve_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/memory/state/search` | `auth` | `state_search_api_v1_memory_state_search_get` | `-` | `200, 422` |
| `GET` | `/api/v1/memory/state/stats` | `auth` | `state_stats_api_v1_memory_state_stats_get` | `-` | `200, 422` |
| `GET` | `/api/v1/memory/stats` | `auth` | `memory_stats_api_v1_memory_stats_get` | `-` | `200, 422` |
| `GET` | `/api/v1/permissions` | `auth` | `get_permissions_api_v1_permissions_get` | `-` | `200, 422` |
| `DELETE` | `/api/v1/permissions/{principal_id}/{tool_name}` | `auth` | `delete_permission_api_v1_permissions__principal_id___tool_name__delete` | `-` | `200, 422` |
| `PUT` | `/api/v1/permissions/{principal_id}/{tool_name}` | `auth` | `set_permission_api_v1_permissions__principal_id___tool_name__put` | `-` | `200, 422` |
| `GET` | `/api/v1/repo/branches` | `auth` | `repo_branches_api_v1_repo_branches_get` | `-` | `200, 422` |
| `POST` | `/api/v1/repo/checkout` | `auth` | `repo_checkout_api_v1_repo_checkout_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/repo/commit` | `auth` | `repo_commit_api_v1_repo_commit_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/repo/diff` | `auth` | `repo_diff_api_v1_repo_diff_get` | `-` | `200, 422` |
| `GET` | `/api/v1/repo/log` | `auth` | `repo_log_api_v1_repo_log_get` | `-` | `200, 422` |
| `POST` | `/api/v1/repo/push` | `auth` | `repo_push_api_v1_repo_push_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/repo/stage` | `auth` | `repo_stage_api_v1_repo_stage_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/repo/status` | `auth` | `repo_status_api_v1_repo_status_get` | `-` | `200, 422` |
| `POST` | `/api/v1/repo/unstage` | `auth` | `repo_unstage_api_v1_repo_unstage_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/schedules` | `auth` | `list_schedules_api_v1_schedules_get` | `-` | `200, 422` |
| `POST` | `/api/v1/schedules` | `auth` | `create_schedule_api_v1_schedules_post` | `application/json` | `200, 422` |
| `PATCH` | `/api/v1/schedules/{schedule_id}` | `auth` | `update_schedule_api_v1_schedules__schedule_id__patch` | `application/json` | `200, 422` |
| `GET` | `/api/v1/schedules/{schedule_id}/dispatches` | `auth` | `list_dispatches_api_v1_schedules__schedule_id__dispatches_get` | `-` | `200, 422` |
| `GET` | `/api/v1/selfupdate/patches` | `auth` | `list_patches_api_v1_selfupdate_patches_get` | `-` | `200, 422` |
| `GET` | `/api/v1/selfupdate/patches/{trace_id}` | `auth` | `patch_detail_api_v1_selfupdate_patches__trace_id__get` | `-` | `200, 422` |
| `POST` | `/api/v1/selfupdate/patches/{trace_id}/approve` | `auth` | `approve_patch_api_v1_selfupdate_patches__trace_id__approve_post` | `-` | `200, 422` |
| `GET` | `/api/v1/selfupdate/patches/{trace_id}/checks` | `auth` | `patch_checks_api_v1_selfupdate_patches__trace_id__checks_get` | `-` | `200, 422` |
| `GET` | `/api/v1/selfupdate/patches/{trace_id}/sandbox` | `auth` | `patch_sandbox_api_v1_selfupdate_patches__trace_id__sandbox_get` | `-` | `200, 422` |
| `GET` | `/api/v1/selfupdate/patches/{trace_id}/timeline` | `auth` | `patch_timeline_api_v1_selfupdate_patches__trace_id__timeline_get` | `-` | `200, 422` |
| `POST` | `/api/v1/stories/run` | `auth` | `run_stories_api_v1_stories_run_post` | `-` | `200, 422` |
| `GET` | `/api/v1/stories/runs` | `auth` | `list_story_runs_api_v1_stories_runs_get` | `-` | `200, 422` |
| `GET` | `/api/v1/stories/runs/{run_id}` | `auth` | `get_story_run_api_v1_stories_runs__run_id__get` | `-` | `200, 422` |
| `GET` | `/api/v1/swarm/tasks` | `auth` | `list_swarm_tasks_api_v1_swarm_tasks_get` | `-` | `200, 422` |
| `POST` | `/api/v1/swarm/tasks` | `auth` | `create_swarm_task_api_v1_swarm_tasks_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/swarm/tasks/{task_id}/cleanup` | `auth` | `cleanup_swarm_task_api_v1_swarm_tasks__task_id__cleanup_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/swarm/tasks/{task_id}/nudge` | `auth` | `nudge_swarm_task_api_v1_swarm_tasks__task_id__nudge_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/system/lockdown` | `auth` | `toggle_lockdown_api_v1_system_lockdown_post` | `application/json` | `200, 422` |
| `POST` | `/api/v1/system/reload-agents` | `auth` | `reload_agents_api_v1_system_reload_agents_post` | `-` | `200, 422` |
| `GET` | `/api/v1/system/repo-index` | `auth` | `repo_index_api_v1_system_repo_index_get` | `-` | `200, 422` |
| `POST` | `/api/v1/system/reset-db` | `auth` | `reset_db_api_v1_system_reset_db_post` | `-` | `200, 422` |
| `GET` | `/api/v1/system/status` | `auth` | `system_status_api_v1_system_status_get` | `-` | `200, 422` |
| `GET` | `/api/v1/threads` | `auth` | `list_threads_api_v1_threads_get` | `-` | `200, 422` |
| `POST` | `/api/v1/threads` | `auth` | `create_web_thread_api_v1_threads_post` | `-` | `200, 422` |
| `GET` | `/api/v1/threads/export/bulk` | `auth` | `export_bulk_api_v1_threads_export_bulk_get` | `-` | `200, 422` |
| `GET` | `/api/v1/threads/{thread_id}` | `auth` | `get_thread_api_v1_threads__thread_id__get` | `-` | `200, 422` |
| `PATCH` | `/api/v1/threads/{thread_id}` | `auth` | `patch_thread_api_v1_threads__thread_id__patch` | `application/json` | `200, 422` |
| `GET` | `/api/v1/threads/{thread_id}/export` | `auth` | `export_thread_api_v1_threads__thread_id__export_get` | `-` | `200, 422` |
| `GET` | `/api/v1/threads/{thread_id}/messages` | `auth` | `list_messages_api_v1_threads__thread_id__messages_get` | `-` | `200, 422` |
| `POST` | `/api/v1/threads/{thread_id}/messages` | `auth` | `send_message_api_v1_threads__thread_id__messages_post` | `application/json` | `200, 422` |
| `GET` | `/api/v1/threads/{thread_id}/onboarding` | `auth` | `get_thread_onboarding_status_api_v1_threads__thread_id__onboarding_get` | `-` | `200, 422` |
| `POST` | `/api/v1/threads/{thread_id}/onboarding/start` | `auth` | `start_thread_onboarding_api_v1_threads__thread_id__onboarding_start_post` | `-` | `200, 422` |
| `GET` | `/api/v1/traces/{trace_id}` | `auth` | `get_trace_api_v1_traces__trace_id__get` | `-` | `200, 422` |
| `POST` | `/api/v1/webhooks/github` | `public` | `github_webhook_api_v1_webhooks_github_post` | `-` | `200, 400, 401, 409, 422` |
| `POST` | `/api/v1/webhooks/trigger/{hook_id}` | `public` | `trigger_webhook_api_v1_webhooks_trigger__hook_id__post` | `-` | `200, 422` |
| `GET` | `/api/v1/webhooks/triggers` | `auth` | `list_triggers_api_v1_webhooks_triggers_get` | `-` | `200, 422` |
| `POST` | `/api/v1/webhooks/triggers` | `auth` | `create_trigger_api_v1_webhooks_triggers_post` | `application/json` | `200, 422` |
| `GET` | `/healthz` | `public` | `healthz_healthz_get` | `-` | `200` |
| `GET` | `/metrics` | `public` | `metrics_metrics_get` | `-` | `200` |
| `GET` | `/readyz` | `public` | `readyz_readyz_get` | `-` | `200` |
| `POST` | `/webhooks/telegram` | `public` | `inbound_webhooks_telegram_post` | `-` | `200` |
| `GET` | `/webhooks/whatsapp` | `public` | `verify_webhooks_whatsapp_get` | `-` | `200` |
| `POST` | `/webhooks/whatsapp` | `public` | `inbound_webhooks_whatsapp_post` | `application/json` | `200, 422` |
| `POST` | `/webhooks/{channel_type}` | `public` | `generic_inbound_webhooks__channel_type__post` | `application/json` | `200, 422` |

## OpenAPI JSON

- Runtime endpoint: `GET /openapi.json`
- Human docs endpoint: `GET /docs`

## Spec Metadata

- `title`: `Jarvis Agent Framework`
- `version`: `0.1.0`
- `path_count`: `117`

```json
{
  "title": "Jarvis Agent Framework",
  "version": "0.1.0",
  "path_count": 117
}
```
