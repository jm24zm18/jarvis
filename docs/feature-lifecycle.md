# Feature Lifecycle

Feature implementation is driven by the roadmap feature-request pipeline.

## Flow

1. Create a feature request through `/api/v1/feature-requests` or `create_feature_request`.
2. Approve the request (`approval_status=approved`).
3. Start the build run (`/api/v1/feature-requests/{id}/build`).
4. Broad-scope requests are decomposed into child feature builds:
   - RLM path when enabled (`FEATURE_BUILD_USE_RLM=1` + `RLM_ENABLED=1`), or
   - forced auto-decomposition when `FEATURE_BUILD_AUTO_DECOMPOSE=1`, with deterministic fallback split when `FEATURE_BUILD_DECOMPOSE_FALLBACK=1`.
5. Jarvis creates an isolated workspace in `/tmp/jarvis-feature-*` for each active build.
6. Jarvis validates dependencies in that clean workspace (`uv sync --frozen`).
7. Only validated runs continue to implementation execution.

## Build Routing

- `source_thread_id` captures where the feature originated.
- `thread_id` captures where active build updates are posted.
- `FEATURE_BUILD_THREAD_TARGET` controls target preference:
  - `reporter` (default): prefer source thread visibility.
  - `admin`: prefer admin-triggering web thread.

## Isolated Development

All feature builds are validated in ephemeral workspaces.

```bash
jarvis feature validate --id F-123
```

This command validates the isolated workspace contract for a feature build run.

## Validation Evidence

Each run records:

- workspace path and expiry metadata
- dependency snapshot hash payload
- validation status/log path/error details

When GitHub issue sync is enabled and the feature is linked to an issue, Jarvis posts an evidence
comment to the issue.

## Workspace Retention

Workspace artifacts are automatically cleaned up after 24 hours.
