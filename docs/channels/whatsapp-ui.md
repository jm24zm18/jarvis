# WhatsApp Admin UI

Path: `/admin/channels`

## Features

- Instance status polling every 3 seconds.
- Create/connect instance action.
- QR load action for pairing.
- Pairing code generation by phone number.
- Disconnect action.

## Troubleshooting

- `evolution_api_disabled`: set `EVOLUTION_API_URL` in `.env` and restart API.
- Empty QR: ensure the instance exists and Evolution sidecar is reachable.
- 401 webhook errors: confirm `X-WhatsApp-Secret` matches `WHATSAPP_WEBHOOK_SECRET`.
