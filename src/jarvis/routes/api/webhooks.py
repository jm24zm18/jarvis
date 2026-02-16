"""Webhook automation trigger routes."""

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from kombu.exceptions import OperationalError

from jarvis.auth.dependencies import UserContext, require_auth
from jarvis.celery_app import celery_app
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import insert_message, now_iso
from jarvis.ids import new_id

router = APIRouter(tags=["api-webhooks"])


@router.post("/webhooks/trigger/{hook_id}")
async def trigger_webhook(
    hook_id: str,
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
) -> dict[str, object]:
    """Trigger an agent step via webhook.

    Accepts arbitrary JSON payload, injects it as a user message
    using the hook's prompt template, then runs agent_step.
    """
    body = await request.body()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, thread_id, agent_id, prompt_template, hmac_secret, enabled "
            "FROM webhook_triggers WHERE id=?",
            (hook_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="webhook trigger not found")
        if not int(row["enabled"]):
            raise HTTPException(status_code=409, detail="webhook trigger is disabled")

        # HMAC verification
        secret = str(row["hmac_secret"]).strip()
        if secret:
            if not x_webhook_signature:
                raise HTTPException(status_code=401, detail="missing signature")
            expected = hmac.new(
                secret.encode(), body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, x_webhook_signature):
                raise HTTPException(status_code=401, detail="invalid signature")

        # Build message from template
        try:
            payload_json = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload_json = {"raw": body.decode("utf-8", errors="replace")}

        template = str(row["prompt_template"])
        message_text = template.replace("{{payload}}", json.dumps(payload_json))

        thread_id = str(row["thread_id"])
        agent_id = str(row["agent_id"])
        trace_id = new_id("trc")

        insert_message(conn, thread_id, "user", message_text)

    try:
        celery_app.send_task(
            "jarvis.tasks.agent.agent_step",
            kwargs={"trace_id": trace_id, "thread_id": thread_id, "actor_id": agent_id},
            queue="agent_priority",
        )
    except OperationalError:
        return {"accepted": True, "degraded": True, "thread_id": thread_id}

    return {"accepted": True, "degraded": False, "thread_id": thread_id}


def _validate_github_signature(
    secret: str,
    body: bytes,
    signature_header: str | None,
) -> bool:
    if not secret:
        return False
    if not signature_header:
        return False
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    provided = signature_header[len(prefix) :].strip()
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def _extract_chat_trigger(body: str, bot_login: str) -> tuple[str, str] | None:
    text = body.strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered.startswith("/jarvis"):
        remainder = text[len("/jarvis") :].strip()
        if not remainder:
            return ("chat", "Please review this PR update.")
        parts = remainder.split(maxsplit=1)
        cmd = parts[0].strip().lower()
        prompt = parts[1].strip() if len(parts) > 1 else ""
        if cmd in {"review", "summarize", "risks", "tests", "help"}:
            return (cmd, prompt or "Please process this PR update.")
        return ("chat", remainder)
    mention = f"@{bot_login.strip().lower()}" if bot_login.strip() else "@jarvis"
    if mention in lowered:
        return ("chat", text)
    return None


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, object]:
    settings = get_settings()
    body = await request.body()
    if not _validate_github_signature(
        settings.github_webhook_secret.strip(),
        body,
        x_hub_signature_256,
    ):
        raise HTTPException(status_code=401, detail="invalid github signature")

    event_type = (x_github_event or "").strip()
    if event_type == "ping":
        return {"accepted": True, "event": "ping"}
    if event_type not in {"pull_request", "issue_comment", "pull_request_review_comment"}:
        return {"accepted": True, "ignored": True, "reason": f"unsupported_event:{event_type}"}

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid json payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid payload")
    action = str(payload.get("action", "")).strip()
    repository = payload.get("repository")
    if not isinstance(repository, dict):
        raise HTTPException(status_code=400, detail="missing repository payload")
    repo_name = str(repository.get("name", "")).strip()
    owner = repository.get("owner")
    owner_login = str(owner.get("login", "")).strip() if isinstance(owner, dict) else ""
    if not repo_name or not owner_login:
        raise HTTPException(status_code=400, detail="missing owner/repo")

    if event_type == "pull_request":
        pull_request = payload.get("pull_request")
        if not isinstance(pull_request, dict):
            raise HTTPException(status_code=400, detail="missing pull_request payload")
        number = int(pull_request.get("number", 0) or 0)
        base = pull_request.get("base")
        base_ref = str(base.get("ref", "")).strip() if isinstance(base, dict) else ""
        if not number:
            raise HTTPException(status_code=400, detail="missing pull number")
        try:
            celery_app.send_task(
                "jarvis.tasks.github.github_pr_summary",
                kwargs={
                    "owner": owner_login,
                    "repo": repo_name,
                    "pull_number": number,
                    "action": action,
                    "base_ref": base_ref,
                },
                queue="tools_io",
            )
        except OperationalError:
            return {
                "accepted": True,
                "degraded": True,
                "event": event_type,
                "action": action,
            }
        return {
            "accepted": True,
            "degraded": False,
            "event": event_type,
            "action": action,
        }

    bot_login = settings.github_bot_login.strip() or "jarvis"
    comment_body = ""
    commenter_login = ""
    pull_number = 0
    if event_type == "issue_comment":
        issue = payload.get("issue")
        comment = payload.get("comment")
        if not isinstance(issue, dict) or not isinstance(comment, dict):
            raise HTTPException(status_code=400, detail="missing issue/comment payload")
        if not isinstance(issue.get("pull_request"), dict):
            return {"accepted": True, "ignored": True, "reason": "issue_is_not_pr"}
        pull_number = int(issue.get("number", 0) or 0)
        comment_body = str(comment.get("body", "")).strip()
        user = comment.get("user")
        if isinstance(user, dict):
            commenter_login = str(user.get("login", "")).strip()
    else:
        pull_request = payload.get("pull_request")
        comment = payload.get("comment")
        if not isinstance(pull_request, dict) or not isinstance(comment, dict):
            raise HTTPException(status_code=400, detail="missing pull_request/comment payload")
        pull_number = int(pull_request.get("number", 0) or 0)
        comment_body = str(comment.get("body", "")).strip()
        user = comment.get("user")
        if isinstance(user, dict):
            commenter_login = str(user.get("login", "")).strip()

    trigger = _extract_chat_trigger(comment_body, bot_login)
    if not pull_number or trigger is None:
        return {"accepted": True, "ignored": True, "reason": "no_chat_trigger"}
    chat_mode, user_prompt = trigger

    try:
        celery_app.send_task(
            "jarvis.tasks.github.github_pr_chat",
            kwargs={
                "owner": owner_login,
                "repo": repo_name,
                "pull_number": pull_number,
                "comment_body": user_prompt,
                "chat_mode": chat_mode,
                "commenter_login": commenter_login,
            },
            queue="tools_io",
        )
    except OperationalError:
        return {
            "accepted": True,
            "degraded": True,
            "event": event_type,
            "action": action,
        }

    return {
        "accepted": True,
        "degraded": False,
        "event": event_type,
        "action": action,
    }


@router.post("/webhooks/triggers")
def create_trigger(
    payload: dict[str, object],
    ctx: UserContext = Depends(require_auth),
) -> dict[str, str]:
    """Create a new webhook trigger (admin only)."""
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin required")

    thread_id = str(payload.get("thread_id", "")).strip()
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id required")

    hook_id = new_id("whk")
    agent_id = str(payload.get("agent_id", "main")).strip() or "main"
    prompt_template = str(payload.get("prompt_template", "{{payload}}")).strip()
    hmac_secret = str(payload.get("hmac_secret", "")).strip()

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO webhook_triggers(id, thread_id, agent_id, prompt_template, "
            "hmac_secret, enabled, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (hook_id, thread_id, agent_id, prompt_template, hmac_secret, 1, now_iso(), now_iso()),
        )
    return {"id": hook_id}


@router.get("/webhooks/triggers")
def list_triggers(ctx: UserContext = Depends(require_auth)) -> dict[str, object]:
    """List all webhook triggers (admin only)."""
    if not ctx.is_admin:
        raise HTTPException(status_code=403, detail="admin required")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, thread_id, agent_id, prompt_template, enabled, created_at "
            "FROM webhook_triggers ORDER BY created_at DESC"
        ).fetchall()
    return {
        "items": [
            {
                "id": str(r["id"]),
                "thread_id": str(r["thread_id"]),
                "agent_id": str(r["agent_id"]),
                "prompt_template": str(r["prompt_template"]),
                "enabled": bool(int(r["enabled"])),
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ]
    }
