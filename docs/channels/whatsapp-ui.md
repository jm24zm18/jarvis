# WhatsApp Admin UI

Path: `/admin/channels`

## Features

- Instance status polling every 3 seconds.
- Create/connect instance action.
- QR load action for pairing.
- Explicit `Force Re-pair` action for `401 loggedOut` and other relink-required states.
- Pairing code generation by phone number.
- Pairing code action is enabled only when WhatsApp status is `qr`; otherwise UI shows
  `QR not ready` with current state.
- Status view includes last disconnect diagnostics (`disconnect_code`, `disconnect_reason`) and
  relink diagnostics (`relink_required`, `can_reconnect`) when available.
- Disconnect action.
- Restart sidecar action.
- All channel actions require admin auth and are blocked for non-admin users.

## Troubleshooting

- `evolution_api_disabled`: set `EVOLUTION_API_URL` in `.env` and restart API.
- Empty QR: ensure the instance exists and Evolution sidecar is reachable.
- Pairing-code `503 qr_not_ready`: wait until status badge becomes `qr`, then retry generate.
- Status `close` with disconnect `401 (loggedOut)`: session auth was invalidated; use
  `Force Re-pair`, then scan a fresh QR.
- 401 webhook errors: confirm `X-WhatsApp-Secret` matches `WHATSAPP_WEBHOOK_SECRET`.
- Pairing code or QR should never appear in persisted event payloads; validate with redacted event views.
- `review_required` sender queue growth: inspect `/api/v1/channels/whatsapp/review-queue` and resolve pending allow/deny decisions.
- voice/media degraded markers (`[voice note unavailable]`, `[media blocked]`): inspect `channel.inbound.degraded` event reason and align media/voice env gates.
