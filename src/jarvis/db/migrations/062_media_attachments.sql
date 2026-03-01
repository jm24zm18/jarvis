-- Media attachments table for unified cross-channel media storage.
-- ID prefix: mda_
-- Keeps messages.media_path and mime_type columns (migration 058) intact.

CREATE TABLE IF NOT EXISTS media_attachments (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES users(id),
  message_id TEXT REFERENCES messages(id),
  event_id TEXT REFERENCES events(id),
  file_path TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  thumbnail_path TEXT,
  original_filename TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_media_attachments_owner
  ON media_attachments(owner_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_media_attachments_message
  ON media_attachments(message_id) WHERE message_id IS NOT NULL;
