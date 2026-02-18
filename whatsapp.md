# WhatsApp (Baileys) Integration Plan — Jarvis + Evolution API

**Purpose:** Implement full personal-number WhatsApp integration (no Meta Business / Cloud API) using Evolution API sidecar with complete bidirectional messaging, media, voice notes, reactions, groups, governance, and admin pairing UI.

---

# 0. Goals & Constraints

## Goal
Provide **pure Baileys power** WhatsApp channel for Jarvis with:

- Text
- Media (image/video/doc)
- Voice notes (auto-transcribe)
- Reactions
- Stickers
- Groups
- Mentions
- Read receipts
- Typing indicators

All messages flow through Jarvis memory + governance.

---

## Constraints

- ❌ No Meta Business Account
- ❌ No WhatsApp Cloud API
- ✅ Personal WhatsApp number
- ✅ Multi-device session
- ✅ Python-only main stack
- ✅ Evolution API runs in sidecar container

---

# 1. Final Architecture

## Containers
jarvis → FastAPI + agents + memory + governance
evolution → Baileys wrapper + REST + Webhooks


---

## Data Flow

### Outbound
Jarvis → Evolution REST → WhatsApp


### Inbound
WhatsApp → Evolution webhook → Jarvis webhook → Orchestrator → Memory


### Admin Pairing
Web UI → Jarvis Admin API → Evolution instance API


---

# 2. Phase 0 — Repository Prep

## Folder Structure

src/jarvis/channels/
init.py
base.py
registry.py
whatsapp_evolution.py

src/jarvis/routes/
webhook.py
api/
channels.py

web/src/pages/admin/channels/
WhatsAppPairing.tsx
ChannelsDashboard.tsx


---

## Environment Variables

EVOLUTION_API_URL
EVOLUTION_API_KEY
WHATSAPP_INSTANCE=personal
WHATSAPP_AUTO_CREATE_ON_STARTUP=false


---

## jarvis.toml

```toml
[channels.whatsapp]
enabled = true
instance = "personal"
auto_create_on_startup = false
3. Phase 1 — Docker Sidecar
Add Evolution container.

Requirements:

persistent auth volumes

API key auth

webhook URL → Jarvis

Acceptance
container boots

instance/create returns QR

webhook returns 200

4. Phase 2 — Channel Implementation
4.1 BaseChannel Interface
Required methods:

send_message(thread_id, content)
parse_inbound(payload)
download_media(...)
4.2 WhatsAppEvolutionChannel
Responsibilities:

map thread ↔ JID

send message types:

Type	Endpoint
text	sendText
media	sendMedia
reaction	sendReaction
Thread Format
whatsapp:{instance}:{remoteJid}
4.3 Media Pipeline
Inbound logic:

Message	Action
image/video	download file
audio	save + transcribe
document	store
sticker	store
reaction	event
Voice notes:

save ogg

enqueue whisper

store transcript + audio reference

4.4 Groups
Detect:

group JID

sender participant

mentions list

Thread id = group JID

Acceptance
Must work:

send/receive text

send/receive media

voice notes → transcription

reactions

groups

5. Phase 3 — Webhook + Governance
Endpoint
POST /webhooks/whatsapp
Validation:

API key

payload shape

Processing
If event = messages.upsert:

extract message

build thread id

normalize event

orchestrator.handle_inbound()

MemoryService.store_structured()

Governance Rules
If:

unknown sender

risky action

→ push to review queue

Queue record:

channel
sender
message
proposed action
In-Chat Commands
/review
/approve <id>
/deny <id>
/compact
Acceptance
unknown sender gated

approvals unblock actions

6. Phase 4 — Admin Web UI Pairing
Backend Endpoints
Method	Route
GET	/api/channels/whatsapp/status
POST	/api/channels/whatsapp/create
GET	/api/channels/whatsapp/qrcode
POST	/api/channels/whatsapp/pairing-code
POST	/api/channels/whatsapp/disconnect
Security:

admin auth

rate limit create + pairing

never log QR or codes

React Page
Features:

Connect button

QR display

Pairing code generator

Status indicator

Polling:

status every 3 seconds
Acceptance
From UI:

create instance

scan QR

connected indicator

disconnect works

7. Phase 5 — Reliability & Testing
Observability
Log:

REST calls

webhook events

media downloads

Metrics:

inbound count

outbound count

transcription queue

webhook latency

Tests
Unit
thread mapping

parsing

message types

Integration
Mock Evolution:

Fixtures:

text

image

audio

reaction

group

Security Checklist
secrets in env only

admin endpoints protected

webhook auth

file size limits

safe media paths

no pairing code persistence

Acceptance
tests pass

secrets hidden

invalid webhook rejected

8. Phase 6 — Documentation
Write:

docs/channels/whatsapp.md
docs/channels/whatsapp-ui.md
Include troubleshooting:

QR not loading

container networking

relink session

media failures

group mentions

9. Deliverables Checklist
Claude Code should generate:

docker compose snippet

base channel class

whatsapp channel class

webhook handler

admin endpoints

React UI page

config files

tests

docs

10. Definition of Done
From clean machine:

docker compose up -d
Flow:

open admin UI

connect WhatsApp

scan QR

send message

Jarvis replies

send voice → transcript stored

send media → stored

reactions work

risky request → review queue

Result
You now have:

Personal WhatsApp agent interface
with

full Baileys capability

structured memory

governance

review queue

multi-agent routing
