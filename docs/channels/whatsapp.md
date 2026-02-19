# WhatsApp Channel (Evolution API)

Jarvis uses Evolution API (Baileys) as the preferred WhatsApp transport when `EVOLUTION_API_URL` is configured.

## Runtime

- Inbound webhook: `POST /webhooks/whatsapp`
- Admin control APIs:
  - `GET /api/v1/channels/whatsapp/status`
  - `POST /api/v1/channels/whatsapp/create`
  - `GET /api/v1/channels/whatsapp/qrcode`
  - `POST /api/v1/channels/whatsapp/pairing-code`
  - `POST /api/v1/channels/whatsapp/disconnect`
  - `GET /api/v1/channels/whatsapp/review-queue`
  - `POST /api/v1/channels/whatsapp/review-queue/{review_id}/resolve`

## Env

- `EVOLUTION_API_URL`
- `EVOLUTION_API_KEY`
- `EVOLUTION_WEBHOOK_URL`
- `EVOLUTION_WEBHOOK_BY_EVENTS`
- `EVOLUTION_WEBHOOK_EVENTS`
- `WHATSAPP_INSTANCE`
- `WHATSAPP_AUTO_CREATE_ON_STARTUP`
- `WHATSAPP_WEBHOOK_SECRET`
- `WHATSAPP_MEDIA_DIR`
- `WHATSAPP_MEDIA_MAX_BYTES`
- `WHATSAPP_MEDIA_ALLOWED_MIME_PREFIXES`
- `WHATSAPP_MEDIA_ALLOWED_HOSTS`
- `WHATSAPP_VOICE_TRANSCRIBE_ENABLED`
- `WHATSAPP_VOICE_TRANSCRIBE_BACKEND`
- `WHATSAPP_VOICE_TRANSCRIBE_TIMEOUT_SECONDS`
- `WHATSAPP_VOICE_MODEL`
- `WHATSAPP_VOICE_DEVICE`
- `WHATSAPP_VOICE_COMPUTE_TYPE`
- `WHATSAPP_VOICE_LANGUAGE`
- `WHATSAPP_REVIEW_MODE`
- `WHATSAPP_ALLOWED_SENDERS`

If `EVOLUTION_API_URL` is unset, Jarvis falls back to WhatsApp Cloud send path for text outbound.

## Security

- Set `WHATSAPP_WEBHOOK_SECRET` and send as `X-WhatsApp-Secret` header.
- Invalid/missing webhook secret returns `401` with `{"accepted": false, "error": "invalid_webhook_secret"}`.
- Pairing and lifecycle APIs are admin-only and rate-limited.
- Sender review queue APIs are admin-only and enforce explicit allow/deny decisions.
- QR payloads and pairing codes are redacted in event payloads/logs (`qrcode`, `qr_code`, `pairing_code`, `code` keys).
- Keep Evolution webhook payload compatibility tests for `messages.upsert` variants (text, extended text, reaction, media, group context).
- Media URL policy is HTTPS-only and supports optional host allowlisting (`WHATSAPP_MEDIA_ALLOWED_HOSTS`).
- Inbound media enforces MIME and size gates (`WHATSAPP_MEDIA_ALLOWED_MIME_PREFIXES`, `WHATSAPP_MEDIA_MAX_BYTES`).
- On blocked/failed media safety checks, inbound remains accepted but degraded, with marker messages (`[media blocked]` / `[voice note unavailable]`) and `channel.inbound.degraded` reason codes.

## Voice Notes

- Inbound `audioMessage` payloads are staged under `WHATSAPP_MEDIA_DIR` and linked to thread messages.
- When transcription is enabled, backends:
  - `stub`: deterministic placeholder transcript for local smoke/dev.
  - `faster_whisper`: local model transcription (requires `faster-whisper` runtime dependency).
- If transcription fails or times out, Jarvis writes `[voice note unavailable]`, emits degraded telemetry, and continues processing.

## Callback Contract

- Jarvis can auto-configure Evolution callback settings via `EVOLUTION_WEBHOOK_*` vars.
- `/api/v1/channels/whatsapp/status` includes callback health state (`enabled`, `configured`, `events`, and last status/error).
- Non-`messages.upsert` events are accepted and ignored (`{"accepted": true, "degraded": false, "ignored": true}`) with no message/event writes.

## Sender Review Gate

- `WHATSAPP_REVIEW_MODE=unknown_only` reviews only malformed/unknown sender IDs.
- `WHATSAPP_REVIEW_MODE=strict` requires sender allowlist or prior allow decision; unknown senders are queued.
- `WHATSAPP_ALLOWED_SENDERS` is a comma-separated sender allowlist (`1555...` or `...@s.whatsapp.net` forms accepted).
- Queued inbound emits `channel.inbound.review_required` and returns `{"accepted": true, "queued_for_review": true}` without message insertion.
- Previously denied senders emit `channel.inbound.blocked` and return `{"accepted": true, "blocked_sender": true}`.
- In-chat review commands (admin WhatsApp IDs only): `/wa-review list [open|allowed|denied]`, `/wa-review allow <queue_id> [reason]`, `/wa-review deny <queue_id> [reason]`.
