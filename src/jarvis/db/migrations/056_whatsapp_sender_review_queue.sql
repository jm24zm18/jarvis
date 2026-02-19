CREATE TABLE IF NOT EXISTS whatsapp_sender_review_queue(
  id TEXT PRIMARY KEY,
  instance TEXT NOT NULL,
  sender_jid TEXT NOT NULL,
  remote_jid TEXT,
  participant_jid TEXT,
  thread_id TEXT,
  external_msg_id TEXT,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,
  reviewer_id TEXT,
  resolution_note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_sender_review_status_created
  ON whatsapp_sender_review_queue(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_whatsapp_sender_review_sender
  ON whatsapp_sender_review_queue(instance, sender_jid, updated_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_whatsapp_sender_review_open_sender
  ON whatsapp_sender_review_queue(instance, sender_jid)
  WHERE status='open';
