# WhatsApp Admin UI

Path: `/admin/channels`

## Features

- Instance status polling every 3 seconds.
- Create/connect instance action.
- QR load action for pairing.
- Pairing code generation by phone number.
- Disconnect action.
- All channel actions require admin auth and are blocked for non-admin users.

## Troubleshooting

- `evolution_api_disabled`: set `EVOLUTION_API_URL` in `.env` and restart API.
- Empty QR: ensure the instance exists and Evolution sidecar is reachable.
- 401 webhook errors: confirm `X-WhatsApp-Secret` matches `WHATSAPP_WEBHOOK_SECRET`.
- Pairing code or QR should never appear in persisted event payloads; validate with redacted event views.
- `review_required` sender queue growth: inspect `/api/v1/channels/whatsapp/review-queue` and resolve pending allow/deny decisions.
- voice/media degraded markers (`[voice note unavailable]`, `[media blocked]`): inspect `channel.inbound.degraded` event reason and align media/voice env gates.
