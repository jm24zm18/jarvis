CREATE TABLE IF NOT EXISTS whatsapp_instances(
  instance TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  last_seen_at TEXT,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS whatsapp_thread_map(
  thread_id TEXT PRIMARY KEY,
  instance TEXT NOT NULL,
  remote_jid TEXT NOT NULL,
  participant_jid TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(instance, remote_jid),
  FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS whatsapp_media(
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  message_id TEXT,
  media_type TEXT NOT NULL,
  local_path TEXT NOT NULL,
  mime_type TEXT,
  bytes INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_thread_map_remote
  ON whatsapp_thread_map(instance, remote_jid);
CREATE INDEX IF NOT EXISTS idx_whatsapp_media_thread
  ON whatsapp_media(thread_id, created_at DESC);
