# Feature Lifecycle

Feature implementation is driven by the roadmap feature-request pipeline.

## Flow

1. Create a feature request through `/api/v1/feature-requests` or `create_feature_request`.
2. Approve the request (`approval_status=approved`).
3. Start the build run (`/api/v1/feature-requests/{id}/build`).
4. Jarvis creates an isolated workspace in `/tmp/jarvis-feature-*`.
5. Jarvis validates dependencies in that clean workspace (`uv sync --frozen`).
6. Only validated runs continue to implementation execution.

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
