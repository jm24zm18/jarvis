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

## Env

- `EVOLUTION_API_URL`
- `EVOLUTION_API_KEY`
- `EVOLUTION_WEBHOOK_URL`
- `EVOLUTION_WEBHOOK_BY_EVENTS`
- `EVOLUTION_WEBHOOK_EVENTS`
- `WHATSAPP_INSTANCE`
- `WHATSAPP_AUTO_CREATE_ON_STARTUP`
- `WHATSAPP_WEBHOOK_SECRET`

If `EVOLUTION_API_URL` is unset, Jarvis falls back to WhatsApp Cloud send path for text outbound.

## Security

- Set `WHATSAPP_WEBHOOK_SECRET` and send as `X-WhatsApp-Secret` header.
- Invalid/missing webhook secret returns `401` with `{"accepted": false, "error": "invalid_webhook_secret"}`.
- Pairing and lifecycle APIs are admin-only and rate-limited.
- QR payloads and pairing codes are redacted in event payloads/logs (`qrcode`, `qr_code`, `pairing_code`, `code` keys).
- Keep Evolution webhook payload compatibility tests for `messages.upsert` variants (text, extended text, reaction, media, group context).

## Callback Contract

- Jarvis can auto-configure Evolution callback settings via `EVOLUTION_WEBHOOK_*` vars.
- `/api/v1/channels/whatsapp/status` includes callback health state (`enabled`, `configured`, `events`, and last status/error).
- Non-`messages.upsert` events are accepted and ignored (`{"accepted": true, "degraded": false, "ignored": true}`) with no message/event writes.
