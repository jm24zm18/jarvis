# Feature Roadmap From `docs/PLAN.md` (WhatsApp First, Memory Next)

## Summary

Ship feature work in two waves:
1. Wave 1: WhatsApp Core + Voice (production-ready channel features).
2. Wave 2: Memory Product Features (retrieval quality + admin visibility).

## Wave 1 (WhatsApp Core + Voice)

### Scope (Backlog IDs)
- BK-022
- BK-023
- BK-024
- BK-025
- BK-027
- BK-028
- BK-014

### Implementation Plan
1. Webhook normalization + mapping completion
- Update `src/jarvis/channels/whatsapp/adapter.py` to normalize all `messages.upsert` variants (text, extended text, reaction, image/video/document/audio/sticker, unknown fallback).
- Preserve stable `thread_key` for DMs/groups and keep `participant` context for groups.
- Keep idempotency via `record_external_message` in `src/jarvis/channels/whatsapp/router.py`.

2. Media/voice ingestion pipeline
- Add media download + persistence flow in `src/jarvis/channels/whatsapp/router.py`.
- Add DB helpers in `src/jarvis/db/queries.py` for inserts/reads on `whatsapp_media`.
- Store downloaded media under controlled runtime directory (`/tmp/jarvis/whatsapp-media` default), enforce size/type limits.
- For voice notes (`audioMessage`/PTT): create transcript text and insert transcript as user message linked to same thread.
- If transcription fails: store `[voice note unavailable]` marker and emit degraded event, but do not drop the inbound message.

3. Admin pairing API completeness
- Keep existing endpoints in `src/jarvis/routes/api/channels.py`, but tighten payload/error contracts:
  - deterministic `ok/error/status_code`
  - sanitized responses (no secret leakage)
  - explicit rate-limit responses for create/pair endpoints.

4. Security controls
- Enforce webhook secret checks (already present) + strict media path/mime/size validation.
- Redact QR/pairing/media-sensitive values in events/logs.
- Add unknown/risky sender review queue (`BK-014`) with explicit allow/deny command handling before agent step execution.

5. Admin UI completion
- Extend `web/src/pages/admin/channels/index.tsx` to show:
  - connection state timeline (latest status + last refresh)
  - pairing errors with actionable text
  - safe rendering of QR/pair code states.
- Keep API contract usage in `web/src/api/endpoints.ts`.

## Wave 2 (Memory Feature Wave)

### Scope (Backlog IDs)
- BK-016
- BK-020
- BK-036
- BK-021

### Implementation Plan
1. Retrieval fusion completion
- Finish RRF + tier-prior weighting in memory retrieval path.
- Add latency/correctness benchmark assertions in unit/integration tests.

2. Consistency evaluator productization
- Expose queryable consistency endpoint data in API and admin UI.
- Add filters/history views in `web/src/pages/admin/memory/index.tsx`.

3. Memory admin UI completion
- Complete conflicts, archive/tier stats, failure lookup, and graph preview sections.
- Ensure ownership/admin boundaries remain enforced.

## Public API / Interface Changes

- Keep existing WhatsApp admin endpoints:
  - `/api/v1/channels/whatsapp/status|create|qrcode|pairing-code|disconnect`
- Add deterministic response schema fields (no breaking path changes).
- Keep webhook entrypoint `/webhooks/whatsapp`; expand accepted payload normalization internally.
- Add internal media/transcript persistence interfaces in DB query layer (no external API break).
- If needed for review queue (`BK-014`), add explicit admin review endpoints under `src/jarvis/routes/api/channels.py` with admin auth only.

## Test Cases and Scenarios

1. WhatsApp inbound matrix
- `tests/integration/test_whatsapp_webhook.py`:
  - text, reaction, group messages, media, voice note
  - duplicate delivery idempotency
  - secret enforcement and degraded broker behavior.

2. Admin API + auth
- Extend `tests/integration/test_admin_api.py` and `tests/integration/test_authorization.py`:
  - all pairing lifecycle routes
  - non-admin denial
  - rate-limit behavior.

3. Channel abstraction
- Extend `tests/unit/test_channel_abstraction.py`:
  - `messages.upsert` payload variants
  - unknown message fallback behavior.

4. Security regressions
- negative tests for oversized media, invalid mime, unsafe path handling, QR/pair-code redaction.

5. Memory wave tests
- Retrieval fusion correctness/latency tests.
- Admin memory UI/API tests for consistency history and conflict surfaces.
- RBAC regressions for memory routes (`BK-021` acceptance paths).

## Acceptance Gates Per Wave

- `make lint`
- `make typecheck`
- targeted WhatsApp/memory tests above
- `make test-gates`
- `make docs-check`
- docs updated in same PR (`docs/PLAN.md`, WhatsApp docs, API docs, runbook/config docs as touched)

## Assumptions and Defaults

- Default sequence: Wave 1 then Wave 2.
- Voice-note transcription is required in Wave 1; if transcript generation fails, inbound still succeeds with degraded marker/event.
- No bypass of policy engine, RBAC, or ownership checks.
- DB changes remain append-only migrations only.
- All feature PRs target `dev` branch per repo policy.
