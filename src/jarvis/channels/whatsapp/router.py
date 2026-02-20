"""WhatsApp webhook routes."""

from __future__ import annotations

import hmac
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from jarvis.channels.registry import get_channel
from jarvis.channels.whatsapp.media_security import (
    MediaSecurityError,
    download_media_file,
    ensure_media_root,
    media_filename,
    parse_csv_set,
    resolve_media_output_path,
    validate_media_mime,
    validate_media_url,
)
from jarvis.channels.whatsapp.transcription import (
    VoiceTranscriptionError,
    build_voice_transcriber,
    transcribe_with_timeout,
)
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import (
    create_whatsapp_sender_review,
    ensure_channel,
    ensure_open_thread,
    ensure_user,
    get_system_state,
    get_thread_by_whatsapp_remote,
    get_whatsapp_sender_review_latest_decision,
    get_whatsapp_sender_review_open,
    insert_message,
    insert_whatsapp_media,
    record_external_message,
    upsert_whatsapp_thread_map,
)
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.tasks import get_task_runner

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])


def _safe_send_task(name: str, kwargs: dict[str, object], queue: str) -> bool:
    try:
        return bool(get_task_runner().send_task(name, kwargs=kwargs, queue=queue))
    except Exception:
        return False


def _emit_degraded_event(
    *,
    conn: Any,
    trace_id: str,
    thread_id: str,
    actor_id: str,
    reason: str,
    detail: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {"reason": reason}
    if detail:
        payload["detail"] = detail
    emit_event(
        conn,
        EventInput(
            trace_id=trace_id,
            span_id=new_id("spn"),
            parent_span_id=None,
            thread_id=thread_id,
            event_type="channel.inbound.degraded",
            component="channels.whatsapp",
            actor_type="system",
            actor_id=actor_id,
            payload_json=json.dumps(payload),
            payload_redacted_json=json.dumps(redact_payload(payload)),
        ),
    )


def _default_media_text(message_type: str, text: str) -> str:
    prefix = f"[{message_type}]"
    return f"{prefix} {text}".strip() if text else prefix


def _fallback_mime(message_type: str, mime_type: str) -> str:
    value = mime_type.strip().lower()
    if value:
        return value
    defaults = {
        "audio": "audio/ogg",
        "image": "image/jpeg",
        "video": "video/mp4",
        "document": "application/pdf",
        "sticker": "image/webp",
    }
    return defaults.get(message_type, "")


def _sender_candidates(value: str) -> set[str]:
    raw = value.strip().lower()
    if not raw:
        return set()
    parts = {raw}
    jid_base = raw.split("@", 1)[0].strip()
    if jid_base:
        parts.add(jid_base)
        if jid_base.startswith("+"):
            parts.add(jid_base[1:])
        else:
            parts.add(f"+{jid_base}")
    return {item for item in parts if item}


def _matches_sender_allowlist(sender_jid: str, allowlist: set[str]) -> bool:
    sender_parts = _sender_candidates(sender_jid)
    if not sender_parts:
        return False
    for allowed in allowlist:
        if sender_parts.intersection(_sender_candidates(allowed)):
            return True
    return False


def _sender_review_state(
    *,
    conn: Any,
    settings: Any,
    instance: str,
    sender_jid: str,
) -> str:
    mode = str(settings.whatsapp_review_mode or "").strip().lower()
    if mode in {"", "off", "disabled", "0"}:
        return "allow"
    sender_parts = _sender_candidates(sender_jid)
    if mode == "unknown_only":
        if sender_jid.strip().lower() == "unknown" or not sender_parts:
            return "review"
        if not any(char.isdigit() for char in sender_jid):
            return "review"
        return "allow"

    allowlist = parse_csv_set(settings.whatsapp_allowed_senders)
    allowlist.update(parse_csv_set(settings.admin_whatsapp_ids))
    if _matches_sender_allowlist(sender_jid, allowlist):
        return "allow"

    existing = get_whatsapp_sender_review_latest_decision(
        conn,
        instance=instance,
        sender_jid=sender_jid,
    )
    if existing == "allowed":
        return "allow"
    if existing == "denied":
        return "deny"
    return "review"


async def _process_media_payload(
    *,
    external_msg_id: str,
    message_type: str,
    text: str,
    media_url: str,
    mime_type: str,
    settings: Any,
) -> dict[str, object]:
    result: dict[str, object] = {
        "text": _default_media_text(message_type, text),
        "degraded": False,
        "reason": "",
        "mime_type": _fallback_mime(message_type, mime_type),
        "local_path": "",
        "bytes": 0,
        "transcription_status": "n/a",
        "transcript_backend": "",
    }
    if not media_url.strip():
        return result

    try:
        allowed_hosts = parse_csv_set(settings.whatsapp_media_allowed_hosts)
        allowed_mime_prefixes = parse_csv_set(settings.whatsapp_media_allowed_mime_prefixes)
        validate_media_url(media_url.strip(), allowed_hosts)
        validate_media_mime(str(result["mime_type"]), allowed_mime_prefixes)
        media_root = ensure_media_root(settings.whatsapp_media_dir)
        file_name = media_filename(external_msg_id, message_type, str(result["mime_type"]))
        target_path = resolve_media_output_path(media_root, file_name)
        total = await download_media_file(
            media_url=media_url.strip(),
            target_path=target_path,
            max_bytes=int(settings.whatsapp_media_max_bytes),
            timeout_seconds=int(settings.whatsapp_voice_transcribe_timeout_seconds),
        )
        result["local_path"] = str(target_path)
        result["bytes"] = total
    except MediaSecurityError as exc:
        result["degraded"] = True
        result["reason"] = exc.reason
        if message_type == "audio":
            result["text"] = "[voice note unavailable]"
            result["transcription_status"] = "failed"
        else:
            result["text"] = "[media blocked]"
        return result

    if message_type != "audio":
        return result

    if int(settings.whatsapp_voice_transcribe_enabled) != 1:
        result["transcription_status"] = "disabled"
        return result

    try:
        transcriber = build_voice_transcriber(settings)
        transcript = await transcribe_with_timeout(
            transcriber=transcriber,
            file_path=Path(str(result["local_path"])),
            mime_type=str(result["mime_type"]),
            timeout_seconds=int(settings.whatsapp_voice_transcribe_timeout_seconds),
        )
        result["text"] = f"[voice] {transcript.strip()}".strip()
        result["transcription_status"] = "ok"
        backend_name = settings.whatsapp_voice_transcribe_backend.strip().lower() or "stub"
        result["transcript_backend"] = backend_name
    except VoiceTranscriptionError as exc:
        result["degraded"] = True
        result["reason"] = exc.reason
        result["text"] = "[voice note unavailable]"
        result["transcription_status"] = "failed"
    return result


@router.get("")
async def verify(request: Request) -> Response:
    settings = get_settings()
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.whatsapp_verify_token and challenge:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="verification failed")


@router.post("")
async def inbound(
    payload: dict[str, Any],
    x_whatsapp_secret: str | None = Header(default=None),
) -> JSONResponse:
    settings = get_settings()
    required_secret = settings.whatsapp_webhook_secret.strip()
    provided_secret = str(x_whatsapp_secret or "").strip()
    if required_secret and (
        not provided_secret or not hmac.compare_digest(provided_secret, required_secret)
    ):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"accepted": False, "error": "invalid_webhook_secret"},
        )

    adapter = get_channel("whatsapp")
    if adapter is None:
        return JSONResponse(
            status_code=500,
            content={"accepted": False, "error": "adapter_missing"},
        )
    messages = adapter.parse_inbound(payload)
    if not messages:
        return JSONResponse(
            status_code=200,
            content={"accepted": True, "degraded": False, "ignored": True},
        )

    trace_id = new_id("trc")
    degraded = False
    queued_for_review = False
    blocked_sender = False
    instance = settings.whatsapp_instance.strip() or "personal"

    with get_conn() as conn:
        state = get_system_state(conn)
        if state["restarting"] == 1:
            return JSONResponse(status_code=200, content={"accepted": False})

        emit_event(
            conn,
            EventInput(
                trace_id=trace_id,
                span_id=new_id("spn"),
                parent_span_id=None,
                thread_id=None,
                event_type="channel.inbound.batch",
                component="channels.whatsapp",
                actor_type="channel",
                actor_id="whatsapp",
                payload_json=json.dumps(payload),
                payload_redacted_json=json.dumps(redact_payload(payload)),
            ),
        )

        for msg in messages:
            if not record_external_message(conn, "whatsapp", msg.external_msg_id, trace_id):
                continue

            user_id = ensure_user(conn, msg.sender_id)
            channel_id = ensure_channel(conn, user_id, "whatsapp")

            thread_id: str
            remote_jid = str(msg.thread_key or "").strip()
            if remote_jid:
                mapped = get_thread_by_whatsapp_remote(conn, instance, remote_jid)
                if mapped:
                    thread_id = mapped
                else:
                    thread_id = ensure_open_thread(conn, user_id, channel_id)
                    upsert_whatsapp_thread_map(
                        conn,
                        thread_id=thread_id,
                        instance=instance,
                        remote_jid=remote_jid,
                        participant_jid=str(msg.group_context.get("participant") or "") or None,
                    )
            else:
                thread_id = ensure_open_thread(conn, user_id, channel_id)

            sender_jid = str(msg.sender_id or "").strip() or remote_jid
            review_state = _sender_review_state(
                conn=conn,
                settings=settings,
                instance=instance,
                sender_jid=sender_jid,
            )
            participant_jid = str(msg.group_context.get("participant") or "").strip()
            if review_state == "review":
                existing_review = get_whatsapp_sender_review_open(
                    conn,
                    instance=instance,
                    sender_jid=sender_jid,
                )
                review_id = ""
                if existing_review is not None:
                    review_id = str(existing_review["id"])
                else:
                    review_id = create_whatsapp_sender_review(
                        conn,
                        instance=instance,
                        sender_jid=sender_jid,
                        remote_jid=remote_jid,
                        participant_jid=participant_jid,
                        thread_id=thread_id,
                        external_msg_id=msg.external_msg_id,
                        reason="unknown_sender",
                    )
                queued_for_review = True
                emit_event(
                    conn,
                    EventInput(
                        trace_id=trace_id,
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=thread_id,
                        event_type="channel.inbound.review_required",
                        component="channels.whatsapp",
                        actor_type="system",
                        actor_id="whatsapp",
                        payload_json=json.dumps(
                            {
                                "queue_id": review_id,
                                "reason": "unknown_sender",
                                "sender_jid": sender_jid,
                                "remote_jid": remote_jid,
                                "participant_jid": participant_jid,
                            }
                        ),
                        payload_redacted_json=json.dumps(
                            redact_payload(
                                {
                                    "queue_id": review_id,
                                    "reason": "unknown_sender",
                                    "sender_jid": sender_jid,
                                    "remote_jid": remote_jid,
                                    "participant_jid": participant_jid,
                                }
                            )
                        ),
                    ),
                )
                continue
            if review_state == "deny":
                blocked_sender = True
                emit_event(
                    conn,
                    EventInput(
                        trace_id=trace_id,
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=thread_id,
                        event_type="channel.inbound.blocked",
                        component="channels.whatsapp",
                        actor_type="system",
                        actor_id="whatsapp",
                        payload_json=json.dumps(
                            {
                                "reason": "sender_denied",
                                "sender_jid": sender_jid,
                                "remote_jid": remote_jid,
                                "participant_jid": participant_jid,
                            }
                        ),
                        payload_redacted_json=json.dumps(
                            redact_payload(
                                {
                                    "reason": "sender_denied",
                                    "sender_jid": sender_jid,
                                    "remote_jid": remote_jid,
                                    "participant_jid": participant_jid,
                                }
                            )
                        ),
                    ),
                )
                continue

            text = (msg.text or "").strip()
            if msg.message_type == "reaction":
                emoji = str(msg.reaction.get("emoji") or "")
                target = ""
                reaction_key = msg.reaction.get("key")
                if isinstance(reaction_key, dict):
                    target = str(reaction_key.get("id") or "")
                text = f"[reaction] {emoji} {target}".strip()
            elif msg.message_type in {"image", "video", "document", "audio", "sticker"}:
                # For audio messages from Baileys, download via Baileys server
                # (handles decryption of encrypted WhatsApp CDN media)
                baileys_downloaded = False
                if msg.message_type == "audio" and isinstance(msg.raw, dict):
                    raw_data = msg.raw.get("data", msg.raw)
                    raw_messages = []
                    if isinstance(raw_data, dict):
                        raw_messages = raw_data.get("messages", [])
                    # Find the matching message in the raw payload
                    raw_message_obj = None
                    for rm in raw_messages:
                        if isinstance(rm, dict) and isinstance(rm.get("message"), dict):
                            raw_message_obj = rm.get("message")
                            break
                    if raw_message_obj and "audioMessage" in raw_message_obj:
                        from jarvis.channels.whatsapp.baileys_client import BaileysClient
                        from jarvis.channels.whatsapp.media_security import (
                            ensure_media_root,
                            media_filename,
                            resolve_media_output_path,
                        )
                        try:
                            baileys = BaileysClient()
                            if baileys.enabled:
                                media_root = ensure_media_root(settings.whatsapp_media_dir)
                                file_name = media_filename(
                                    msg.external_msg_id, "audio",
                                    str(raw_message_obj["audioMessage"].get("mimetype", "audio/ogg")),
                                )
                                target_path = resolve_media_output_path(media_root, file_name)
                                total = await baileys.download_media(
                                    message=raw_message_obj,
                                    target_path=str(target_path),
                                )
                                if total > 0:
                                    baileys_downloaded = True
                                    mime_type = str(
                                        raw_message_obj["audioMessage"].get("mimetype", "audio/ogg")
                                    )
                                    media_result = {
                                        "text": "",
                                        "degraded": False,
                                        "reason": "",
                                        "mime_type": mime_type,
                                        "local_path": str(target_path),
                                        "bytes": total,
                                        "transcription_status": "n/a",
                                        "transcript_backend": "",
                                    }
                                    # Run transcription if enabled
                                    if int(settings.whatsapp_voice_transcribe_enabled) == 1:
                                        try:
                                            transcriber = build_voice_transcriber(settings)
                                            transcript = await transcribe_with_timeout(
                                                transcriber=transcriber,
                                                file_path=target_path,
                                                mime_type=mime_type,
                                                timeout_seconds=int(
                                                    settings.whatsapp_voice_transcribe_timeout_seconds
                                                ),
                                            )
                                            media_result["text"] = f"[voice] {transcript.strip()}"
                                            media_result["transcription_status"] = "ok"
                                            backend_name = (
                                                settings.whatsapp_voice_transcribe_backend.strip().lower()
                                                or "stub"
                                            )
                                            media_result["transcript_backend"] = backend_name
                                        except VoiceTranscriptionError as exc:
                                            media_result["degraded"] = True
                                            media_result["reason"] = exc.reason
                                            media_result["text"] = "[voice note unavailable]"
                                            media_result["transcription_status"] = "failed"
                                    else:
                                        media_result["text"] = "[voice note]"
                                        media_result["transcription_status"] = "disabled"
                        except Exception:
                            pass  # Fall back to regular media download

                if not baileys_downloaded:
                    media_result = await _process_media_payload(
                        external_msg_id=msg.external_msg_id,
                        message_type=msg.message_type,
                        text=text,
                        media_url=str(msg.media_url or msg.media.get("url") or ""),
                        mime_type=str(msg.media.get("mime_type") or ""),
                        settings=settings,
                    )
                text = str(media_result["text"])
                if bool(media_result["degraded"]):
                    degraded = True
                    _emit_degraded_event(
                        conn=conn,
                        trace_id=trace_id,
                        thread_id=thread_id,
                        actor_id="media",
                        reason=str(media_result["reason"] or "media_download_failed"),
                        detail={
                            "message_type": msg.message_type,
                            "external_msg_id": msg.external_msg_id,
                        },
                    )
            elif msg.message_type == "unknown" and not text:
                text = "[unsupported message]"

            message_id = insert_message(conn, thread_id, "user", text)

            media_id = ""
            if msg.message_type in {"image", "video", "document", "audio", "sticker"}:
                local_path = str(media_result.get("local_path", "")).strip()
                if local_path:
                    bytes_value = media_result.get("bytes", 0)
                    num_bytes = int(bytes_value) if isinstance(bytes_value, int | str) else 0
                    try:
                        media_id = insert_whatsapp_media(
                            conn,
                            thread_id=thread_id,
                            message_id=message_id,
                            media_type=msg.message_type,
                            local_path=local_path,
                            mime_type=str(media_result.get("mime_type", "")),
                            num_bytes=num_bytes,
                        )
                    except Exception:
                        degraded = True
                        _emit_degraded_event(
                            conn=conn,
                            trace_id=trace_id,
                            thread_id=thread_id,
                            actor_id="media",
                            reason="media_persist_failed",
                            detail={
                                "message_type": msg.message_type,
                                "external_msg_id": msg.external_msg_id,
                            },
                        )

            event_payload = {
                "text": text,
                "message_type": msg.message_type,
                "mentions": msg.mentions,
                "group_context": msg.group_context,
                "media_id": media_id or None,
                "transcription_status": (
                    str(media_result.get("transcription_status", "n/a"))
                    if msg.message_type in {"image", "video", "document", "audio", "sticker"}
                    else "n/a"
                ),
            }
            emit_event(
                conn,
                EventInput(
                    trace_id=trace_id,
                    span_id=new_id("spn"),
                    parent_span_id=None,
                    thread_id=thread_id,
                    event_type="channel.inbound",
                    component="channels.whatsapp",
                    actor_type="user",
                    actor_id=user_id,
                    payload_json=json.dumps(event_payload),
                    payload_redacted_json=json.dumps(redact_payload(event_payload)),
                ),
            )

            index_ok = _safe_send_task(
                "jarvis.tasks.memory.index_event",
                {
                    "trace_id": trace_id,
                    "thread_id": thread_id,
                    "text": text,
                        "metadata": {
                            "channel": "whatsapp",
                            "message_type": msg.message_type,
                            "mentions": msg.mentions,
                            "group_context": msg.group_context,
                            "media_id": media_id or None,
                            "transcription_status": (
                                str(media_result.get("transcription_status", "n/a"))
                                if msg.message_type
                                in {"image", "video", "document", "audio", "sticker"}
                                else "n/a"
                            ),
                            "transcript_backend": (
                                str(media_result.get("transcript_backend", ""))
                                if msg.message_type == "audio"
                                else ""
                            ),
                        },
                    },
                    "tools_io",
                )
            # Send typing indicator ("composing") to show Jarvis is thinking
            try:
                await adapter.send_presence(
                    recipient=str(msg.sender_id or remote_jid),
                    presence="composing",
                )
            except Exception:
                pass  # Typing indicator is best-effort, don't block on failure

            step_ok = _safe_send_task(
                "jarvis.tasks.agent.agent_step",
                {"trace_id": trace_id, "thread_id": thread_id},
                "agent_priority",
            )
            if not index_ok or not step_ok:
                degraded = True
                _emit_degraded_event(
                    conn=conn,
                    trace_id=trace_id,
                    thread_id=thread_id,
                    actor_id="broker",
                    reason="broker_enqueue_failed",
                    detail={
                        "index_enqueued": index_ok,
                        "agent_step_enqueued": step_ok,
                    },
                )

    status_code = 202 if degraded else 200
    response_payload: dict[str, object] = {"accepted": True, "degraded": degraded}
    if queued_for_review:
        response_payload["queued_for_review"] = True
    if blocked_sender:
        response_payload["blocked_sender"] = True
    return JSONResponse(status_code=status_code, content=response_payload)
