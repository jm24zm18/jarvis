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
- `WHATSAPP_INSTANCE`
- `WHATSAPP_AUTO_CREATE_ON_STARTUP`
- `WHATSAPP_WEBHOOK_SECRET`

If `EVOLUTION_API_URL` is unset, Jarvis falls back to WhatsApp Cloud send path for text outbound.

## Security

- Set `WHATSAPP_WEBHOOK_SECRET` and send as `X-WhatsApp-Secret` header.
- Pairing and lifecycle APIs are admin-only and rate-limited.
- QR payloads and pairing codes should not be logged.
