CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'thread',
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_participants (
  session_id TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  role TEXT NOT NULL,
  PRIMARY KEY(session_id, actor_type, actor_id),
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_session_participants_actor
  ON session_participants(actor_type, actor_id);

CREATE VIEW IF NOT EXISTS v_session_timeline AS
SELECT
  t.id            AS session_id,
  m.created_at    AS created_at,
  m.role          AS role,
  NULL            AS event_type,
  NULL            AS component,
  NULL            AS actor_type,
  NULL            AS actor_id,
  m.id            AS message_id,
  NULL            AS event_id,
  m.content       AS content
FROM threads t
JOIN messages m ON m.thread_id = t.id
UNION ALL
SELECT
  e.thread_id     AS session_id,
  e.created_at    AS created_at,
  'event'         AS role,
  e.event_type    AS event_type,
  e.component     AS component,
  e.actor_type    AS actor_type,
  e.actor_id      AS actor_id,
  NULL            AS message_id,
  e.id            AS event_id,
  json_extract(e.payload_redacted_json, '$.text') AS content
FROM events e
WHERE e.thread_id IS NOT NULL;
