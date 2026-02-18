# GitHub PR Automation

This repo supports GitHub automation in three stages:

- Verify inbound GitHub webhook signatures.
- Receive `pull_request` events.
- Queue an in-process task that posts or updates a single PR summary comment.
- Receive PR comment events and reply when triggered by `/jarvis ...` or `@jarvis`.
- Sync bug/feature requests from Jarvis into GitHub Issues when requested.
- Auto-create a bug report in `/api/v1/bugs` storage if PR automation fails.

## What This Does

- Endpoint: `POST /api/v1/webhooks/github`
- Events handled:
  - `ping` (connectivity test)
  - `pull_request` actions: `opened`, `reopened`, `synchronize`, `ready_for_review`
  - `issue_comment` (PR comments only)
  - `pull_request_review_comment`
- Scope:
  - Only PRs targeting `dev` are summarized.
  - No approve/merge/write-to-branches behavior is performed.

## Required Setup

1. Configure `.env`:

```bash
GITHUB_PR_SUMMARY_ENABLED=1
GITHUB_WEBHOOK_SECRET=<long-random-secret>
GITHUB_TOKEN=<github-app-installation-token-or-pat>
# optional hardening:
GITHUB_REPO_ALLOWLIST=my-org/my-repo,my-org/another-repo
GITHUB_API_BASE_URL=https://api.github.com
GITHUB_BOT_LOGIN=jarvis
GITHUB_ISSUE_SYNC_ENABLED=1
GITHUB_ISSUE_SYNC_REPO=my-org/my-repo
GITHUB_ISSUE_LABELS_BUG=jarvis,bug
GITHUB_ISSUE_LABELS_FEATURE=jarvis,feature-request
```

2. Restart API:

```bash
make api
```

3. Configure GitHub webhook in repository settings:
   - Payload URL: `https://<your-host>/api/v1/webhooks/github`
   - Content type: `application/json`
   - Secret: same value as `GITHUB_WEBHOOK_SECRET`
   - Events: `Pull requests` (and `Ping` for test)
   - Also enable `Issue comments` and `Pull request review comments` for Stage 2 chat.

4. If using GitHub App (recommended):
   - Grant repo permissions:
     - `Pull requests: Read`
     - `Issues: Read and write` (for issue comments on PRs)
     - `Metadata: Read`
   - Install app on target repos.
   - Provide installation token via `GITHUB_TOKEN`.

## Branch Access and Safety

- Keep workflow in `docs/git-workflow.md`:
  - work branch -> `dev`
  - `dev` -> `master` promotion via PR only
- Existing branch policy checks still apply (`.github/workflows/branch-policy.yml`).
- This automation does not bypass approvals or branch protections.

## Bug and Feature Sync to GitHub Issues

When enabled, users (or agents) can create local records and request GitHub sync in the same API call:

- `POST /api/v1/bugs`
- `POST /api/v1/feature-requests`

Example payload:

```json
{
  "title": "Webhook retries fail on 403",
  "description": "Observed in dev after token rotation.",
  "priority": "high",
  "sync_to_github": true
}
```

Expected behavior:

- Jarvis stores the local row first (`kind=bug` or `kind=feature`).
- An in-process task creates a GitHub Issue in `GITHUB_ISSUE_SYNC_REPO`.
- On success, local row is updated with `github_issue_number`, `github_issue_url`, `github_synced_at`.
- On failure, local row stores `github_sync_error`.

## Stage 2 Commands

Use these in PR comments:

- `/jarvis review <question>`: findings-first review mode.
- `/jarvis summarize <question>`: concise change summary mode.
- `/jarvis risks <question>`: risk-focused mode.
- `/jarvis tests <question>`: testing recommendations mode.
- `/jarvis help`: show available commands.
- `/jarvis <question>` or `@jarvis <question>`: general PR chat mode.

## Failure Handling via Bug Feature

When PR summary or PR chat automation fails (auth, API errors, payload issues), Jarvis writes a bug row in `bug_reports`:

- Title: `GitHub PR summary automation failed` or `GitHub PR chat automation failed`
- Priority: `high`
- Assignee: `release_ops`
- Description: serialized error context (`repo`, PR number, action, error)

You can inspect these in:

- `GET /api/v1/bugs` (admin sees all; non-admin sees own reports)

## Verify

1. Trigger webhook test from GitHub (`ping`) and confirm `200`.
2. Open a PR from `agent/<topic>` (or any work branch) into `dev`.
3. Confirm a `Jarvis PR Summary (Stage 1)` comment appears.
4. Add a PR comment with `/jarvis summarize this PR` or `/jarvis review migration risks`.
5. Confirm Jarvis posts a reply comment in the same PR.
6. If token/permissions are wrong, confirm a bug report is created.
