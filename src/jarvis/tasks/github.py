"""GitHub webhook processing tasks."""

from __future__ import annotations

import asyncio
import fnmatch
import json
from collections.abc import Iterable

import httpx

from jarvis.celery_app import celery_app
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import now_iso
from jarvis.ids import new_id
from jarvis.providers.factory import build_primary_provider
from jarvis.providers.router import ProviderRouter
from jarvis.providers.sglang import SGLangProvider

SUMMARY_MARKER = "<!-- jarvis:pr-summary -->"
CHAT_MARKER = "<!-- jarvis:pr-chat -->"


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Jarvis-GitHub-Webhook/1.0",
    }


def _repo_allowed(full_name: str, allowlist_csv: str) -> bool:
    allowlist = [item.strip() for item in allowlist_csv.split(",") if item.strip()]
    if not allowlist:
        return True
    for pattern in allowlist:
        if fnmatch.fnmatch(full_name, pattern):
            return True
    return False


def _render_summary_comment(
    *,
    repo: str,
    number: int,
    title: str,
    base_ref: str,
    head_ref: str,
    commits: int,
    changed_files: int,
    additions: int,
    deletions: int,
    files: Iterable[dict[str, object]],
) -> str:
    top = list(files)[:15]
    file_lines: list[str] = []
    for item in top:
        filename = str(item.get("filename", "")).strip()
        status = str(item.get("status", "")).strip() or "modified"
        add = int(item.get("additions", 0) or 0)
        delete = int(item.get("deletions", 0) or 0)
        if filename:
            file_lines.append(f"- `{filename}` ({status}, +{add} / -{delete})")
    if not file_lines:
        file_lines.append("- No changed files returned by GitHub API.")

    migration_touched = any(
        str(item.get("filename", "")).startswith("src/jarvis/db/migrations/") for item in top
    )
    auth_touched = any(
        str(item.get("filename", "")).startswith("src/jarvis/auth/") for item in top
    )
    routes_touched = any(
        str(item.get("filename", "")).startswith("src/jarvis/routes/") for item in top
    )

    risk_notes = [
        f"- Migrations touched: {'yes' if migration_touched else 'no'}",
        f"- Auth/RBAC area touched: {'yes' if auth_touched else 'no'}",
        f"- API routes touched: {'yes' if routes_touched else 'no'}",
    ]

    return (
        f"{SUMMARY_MARKER}\n"
        "## Jarvis PR Summary (Stage 1)\n"
        f"- Repository: `{repo}`\n"
        f"- PR: #{number} - {title}\n"
        f"- Base/Head: `{base_ref}` <- `{head_ref}`\n"
        f"- Diffstat: {changed_files} files, +{additions} / -{deletions}, {commits} commits\n\n"
        "### Top Changed Files\n"
        f"{chr(10).join(file_lines)}\n\n"
        "### Quick Risk Flags\n"
        f"{chr(10).join(risk_notes)}\n\n"
        "_Automated summary only. Human review and approval policy still apply._"
    )


def _fetch_pr_and_files(
    *,
    client: httpx.Client,
    base_url: str,
    owner: str,
    repo: str,
    number: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    pr_resp = client.get(f"{base_url}/repos/{owner}/{repo}/pulls/{number}")
    pr_resp.raise_for_status()
    pr = pr_resp.json()
    if not isinstance(pr, dict):
        raise RuntimeError("pull request payload is not an object")

    files: list[dict[str, object]] = []
    page = 1
    while page <= 10:
        files_resp = client.get(
            f"{base_url}/repos/{owner}/{repo}/pulls/{number}/files",
            params={"per_page": 100, "page": page},
        )
        files_resp.raise_for_status()
        payload = files_resp.json()
        if not isinstance(payload, list):
            raise RuntimeError("pull request files payload is not a list")
        chunk = [item for item in payload if isinstance(item, dict)]
        files.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return pr, files


def _upsert_summary_comment(
    *,
    client: httpx.Client,
    base_url: str,
    owner: str,
    repo: str,
    number: int,
    body: str,
) -> dict[str, object]:
    comments_resp = client.get(
        f"{base_url}/repos/{owner}/{repo}/issues/{number}/comments",
        params={"per_page": 100},
    )
    comments_resp.raise_for_status()
    comments = comments_resp.json()
    if not isinstance(comments, list):
        comments = []

    existing_id: int | None = None
    for item in comments:
        if not isinstance(item, dict):
            continue
        existing_body = item.get("body")
        if isinstance(existing_body, str) and SUMMARY_MARKER in existing_body:
            comment_id = item.get("id")
            if isinstance(comment_id, int):
                existing_id = comment_id
                break

    if existing_id is None:
        post_resp = client.post(
            f"{base_url}/repos/{owner}/{repo}/issues/{number}/comments",
            json={"body": body},
        )
        post_resp.raise_for_status()
        created = post_resp.json()
        return {"action": "created", "comment_id": int(created.get("id", 0) or 0)}

    patch_resp = client.patch(
        f"{base_url}/repos/{owner}/{repo}/issues/comments/{existing_id}",
        json={"body": body},
    )
    patch_resp.raise_for_status()
    return {"action": "updated", "comment_id": existing_id}


def _fetch_issue_comments(
    *,
    client: httpx.Client,
    base_url: str,
    owner: str,
    repo: str,
    number: int,
    limit: int = 20,
) -> list[dict[str, object]]:
    resp = client.get(
        f"{base_url}/repos/{owner}/{repo}/issues/{number}/comments",
        params={"per_page": max(1, min(limit, 100))},
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _render_prompt_context(
    *,
    owner: str,
    repo: str,
    number: int,
    pr: dict[str, object],
    files: list[dict[str, object]],
    recent_comments: list[dict[str, object]],
    user_message: str,
) -> str:
    title = str(pr.get("title", "")).strip()
    base_ref = ""
    head_ref = ""
    base = pr.get("base")
    if isinstance(base, dict):
        base_ref = str(base.get("ref", "")).strip()
    head = pr.get("head")
    if isinstance(head, dict):
        head_ref = str(head.get("ref", "")).strip()

    top_files: list[str] = []
    for item in files[:20]:
        filename = str(item.get("filename", "")).strip()
        if not filename:
            continue
        status = str(item.get("status", "")).strip() or "modified"
        add = int(item.get("additions", 0) or 0)
        delete = int(item.get("deletions", 0) or 0)
        top_files.append(f"- {filename} ({status}, +{add}/-{delete})")
    if not top_files:
        top_files.append("- no files listed")

    recent: list[str] = []
    for item in recent_comments[-12:]:
        body = str(item.get("body", "")).strip()
        if not body or SUMMARY_MARKER in body or CHAT_MARKER in body:
            continue
        user = item.get("user")
        login = ""
        if isinstance(user, dict):
            login = str(user.get("login", "")).strip()
        recent.append(f"- @{login}: {body[:500]}")
    if not recent:
        recent.append("- no recent human comments")

    return (
        f"Repository: {owner}/{repo}\n"
        f"PR: #{number}\n"
        f"Title: {title}\n"
        f"Base/Head: {base_ref} <- {head_ref}\n"
        f"Diffstat: {int(pr.get('changed_files', len(files)) or len(files))} files, "
        f"+{int(pr.get('additions', 0) or 0)} / -{int(pr.get('deletions', 0) or 0)}\n\n"
        f"Requester message:\n{user_message}\n\n"
        "Top changed files:\n"
        f"{chr(10).join(top_files)}\n\n"
        "Recent PR comments:\n"
        f"{chr(10).join(recent)}"
    )


def _mode_system_suffix(chat_mode: str) -> str:
    mode = chat_mode.strip().lower()
    if mode == "review":
        return (
            "Mode: review. Focus on correctness/regression/security/data risks. "
            "List findings by severity with file references when possible."
        )
    if mode == "summarize":
        return (
            "Mode: summarize. Provide concise summary of change intent, key files, "
            "and likely impact areas."
        )
    if mode == "risks":
        return (
            "Mode: risks. Focus only on risk flags, why each matters, and checks to run."
        )
    if mode == "tests":
        return (
            "Mode: tests. Recommend concrete tests to add/run, including targeted paths."
        )
    if mode == "help":
        return "Mode: help. Return command usage only."
    return (
        "Mode: chat. Answer directly with actionable guidance grounded in PR context."
    )


async def _generate_chat_reply_for_mode(prompt: str, chat_mode: str) -> str:
    mode_hint = _mode_system_suffix(chat_mode)
    settings = get_settings()
    router = ProviderRouter(
        build_primary_provider(settings),
        SGLangProvider(settings.sglang_model),
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are Jarvis helping in a GitHub PR thread. "
                "Be concise, concrete, and engineering-focused. "
                "Do not claim tests passed unless stated in input. "
                "Do not approve merges. "
                "Prefer bullet points and actionable next steps. "
                f"{mode_hint}"
            ),
        },
        {"role": "user", "content": prompt},
    ]
    response, lane, fallback_error = await router.generate(
        messages=messages,
        tools=None,
        temperature=0.2,
        max_tokens=700,
        priority="low",
    )
    text = response.text.strip()
    if not text:
        text = "I could not generate a reply from current context."
    if fallback_error:
        text = f"{text}\n\n_Provider lane: {lane}; primary fallback: {fallback_error}_"
    return text


def _help_text() -> str:
    return (
        "Available `/jarvis` commands:\n"
        "- `/jarvis review <question>`: findings-first review mode.\n"
        "- `/jarvis summarize <question>`: concise summary mode.\n"
        "- `/jarvis risks <question>`: risk-focused mode.\n"
        "- `/jarvis tests <question>`: testing recommendations.\n"
        "- `/jarvis <question>`: general PR chat mode.\n"
        "- `@jarvis <question>`: mention-based general chat.\n"
        "- `/jarvis help`: show this help."
    )


def _post_issue_comment(
    *,
    client: httpx.Client,
    base_url: str,
    owner: str,
    repo: str,
    number: int,
    body: str,
) -> dict[str, object]:
    resp = client.post(
        f"{base_url}/repos/{owner}/{repo}/issues/{number}/comments",
        json={"body": body},
    )
    resp.raise_for_status()
    payload = resp.json()
    return {"comment_id": int(payload.get("id", 0) or 0)}


def _record_bug_report(title: str, details: dict[str, object], priority: str = "high") -> str:
    bug_id = new_id("bug")
    now = now_iso()
    with get_conn() as conn:
        conn.execute(
            (
                "INSERT INTO bug_reports(id, title, description, status, priority, "
                "reporter_id, assignee_agent, thread_id, trace_id, created_at, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            ),
            (
                bug_id,
                title,
                json.dumps(details, indent=2, sort_keys=True),
                "open",
                priority,
                None,
                "release_ops",
                None,
                None,
                now,
                now,
            ),
        )
    return bug_id


@celery_app.task(name="jarvis.tasks.github.github_pr_summary")
def github_pr_summary(
    *,
    owner: str,
    repo: str,
    pull_number: int,
    action: str,
    base_ref: str,
) -> dict[str, object]:
    settings = get_settings()
    if int(settings.github_pr_summary_enabled) != 1:
        return {"ok": True, "skipped": "github_pr_summary_disabled"}

    if action not in {"opened", "reopened", "synchronize", "ready_for_review"}:
        return {"ok": True, "skipped": f"unsupported_action:{action}"}
    if base_ref != "dev":
        return {"ok": True, "skipped": f"unsupported_base:{base_ref}"}

    full_name = f"{owner}/{repo}"
    if not _repo_allowed(full_name, settings.github_repo_allowlist):
        return {"ok": True, "skipped": "repo_not_allowlisted", "repo": full_name}

    token = settings.github_token.strip()
    if not token:
        return {"ok": False, "error": "missing GITHUB_TOKEN"}

    base_url = settings.github_api_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=10.0, headers=_github_headers(token)) as client:
            pr, files = _fetch_pr_and_files(
                client=client, base_url=base_url, owner=owner, repo=repo, number=int(pull_number)
            )
            title = str(pr.get("title", "")).strip() or "(untitled)"
            head = pr.get("head")
            head_ref = ""
            if isinstance(head, dict):
                head_ref = str(head.get("ref", "")).strip()
            commits = int(pr.get("commits", 0) or 0)
            changed_files = int(pr.get("changed_files", len(files)) or len(files))
            additions = int(pr.get("additions", 0) or 0)
            deletions = int(pr.get("deletions", 0) or 0)

            body = _render_summary_comment(
                repo=full_name,
                number=int(pull_number),
                title=title,
                base_ref=base_ref,
                head_ref=head_ref,
                commits=commits,
                changed_files=changed_files,
                additions=additions,
                deletions=deletions,
                files=files,
            )
            result = _upsert_summary_comment(
                client=client,
                base_url=base_url,
                owner=owner,
                repo=repo,
                number=int(pull_number),
                body=body,
            )
    except Exception as exc:
        bug_id = _record_bug_report(
            "GitHub PR summary automation failed",
            {
                "repo": full_name,
                "pull_number": int(pull_number),
                "action": action,
                "base_ref": base_ref,
                "error": repr(exc),
            },
            priority="high",
        )
        return {
            "ok": False,
            "repo": full_name,
            "pull_number": int(pull_number),
            "error": str(exc),
            "bug_id": bug_id,
        }
    return {
        "ok": True,
        "repo": full_name,
        "pull_number": int(pull_number),
        "result": result,
    }


@celery_app.task(name="jarvis.tasks.github.github_pr_chat")
def github_pr_chat(
    *,
    owner: str,
    repo: str,
    pull_number: int,
    comment_body: str,
    chat_mode: str = "chat",
    commenter_login: str,
) -> dict[str, object]:
    settings = get_settings()
    if int(settings.github_pr_summary_enabled) != 1:
        return {"ok": True, "skipped": "github_pr_summary_disabled"}

    full_name = f"{owner}/{repo}"
    if not _repo_allowed(full_name, settings.github_repo_allowlist):
        return {"ok": True, "skipped": "repo_not_allowlisted", "repo": full_name}

    bot_login = settings.github_bot_login.strip().lower()
    if bot_login and commenter_login.strip().lower() == bot_login:
        return {"ok": True, "skipped": "self_comment"}

    token = settings.github_token.strip()
    if not token:
        return {"ok": False, "error": "missing GITHUB_TOKEN"}

    base_url = settings.github_api_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=15.0, headers=_github_headers(token)) as client:
            if chat_mode.strip().lower() == "help":
                body = (
                    f"{CHAT_MARKER}\n"
                    f"@{commenter_login} {_help_text()}\n\n"
                    "_Automated PR chat response; human review/approval policy still applies._"
                )
                result = _post_issue_comment(
                    client=client,
                    base_url=base_url,
                    owner=owner,
                    repo=repo,
                    number=int(pull_number),
                    body=body,
                )
                return {
                    "ok": True,
                    "repo": full_name,
                    "pull_number": int(pull_number),
                    "result": result,
                }
            pr, files = _fetch_pr_and_files(
                client=client,
                base_url=base_url,
                owner=owner,
                repo=repo,
                number=int(pull_number),
            )
            comments = _fetch_issue_comments(
                client=client,
                base_url=base_url,
                owner=owner,
                repo=repo,
                number=int(pull_number),
                limit=50,
            )
            prompt = _render_prompt_context(
                owner=owner,
                repo=repo,
                number=int(pull_number),
                pr=pr,
                files=files,
                recent_comments=comments,
                user_message=comment_body,
            )
            reply = asyncio.run(_generate_chat_reply_for_mode(prompt, chat_mode))
            body = (
                f"{CHAT_MARKER}\n"
                f"@{commenter_login} {reply}\n\n"
                "_Automated PR chat response; human review/approval policy still applies._"
            )
            result = _post_issue_comment(
                client=client,
                base_url=base_url,
                owner=owner,
                repo=repo,
                number=int(pull_number),
                body=body,
            )
    except Exception as exc:
        bug_id = _record_bug_report(
            "GitHub PR chat automation failed",
            {
                "repo": full_name,
                "pull_number": int(pull_number),
                "chat_mode": chat_mode,
                "commenter_login": commenter_login,
                "error": repr(exc),
            },
            priority="high",
        )
        return {
            "ok": False,
            "repo": full_name,
            "pull_number": int(pull_number),
            "error": str(exc),
            "bug_id": bug_id,
        }
    return {
        "ok": True,
        "repo": full_name,
        "pull_number": int(pull_number),
        "result": result,
    }
