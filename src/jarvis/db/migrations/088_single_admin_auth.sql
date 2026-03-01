-- Collapse to a single authenticated root user and remove RBAC columns.

-- Ensure root user exists in pre-migration schema.
INSERT INTO users(id, external_id, role, created_at, scopes)
SELECT 'usr_root', 'system:root', 'admin', datetime('now'), '["*"]'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE external_id='system:root');

-- Reassign user-owned records to root user.
UPDATE channels
SET user_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE user_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE threads
SET user_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE user_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE web_sessions
SET user_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE user_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE onboarding_states
SET user_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE user_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE media_attachments
SET owner_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE owner_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE bug_reports
SET reporter_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE reporter_id IS NOT NULL
  AND reporter_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE skills
SET owner_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE owner_id IS NOT NULL
  AND owner_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE user_memory_items
SET user_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE user_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE user_profiles
SET user_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE user_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE user_profile_history
SET user_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE user_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE knowledge_graph
SET user_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE user_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE user_reflection_watermarks
SET user_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE user_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

UPDATE session_participants
SET actor_id=(SELECT id FROM users WHERE external_id='system:root' LIMIT 1)
WHERE actor_type='user'
  AND actor_id != (SELECT id FROM users WHERE external_id='system:root' LIMIT 1);

DELETE FROM users
WHERE external_id != 'system:root';

PRAGMA foreign_keys=OFF;

-- Rebuild users table without role/scopes columns.
DROP TRIGGER IF EXISTS trg_users_external_id_guard_insert;
DROP TRIGGER IF EXISTS trg_users_external_id_guard_update;

CREATE TABLE users_new (
  id TEXT PRIMARY KEY,
  external_id TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

INSERT INTO users_new(id, external_id, created_at)
SELECT id, external_id, created_at FROM users;

DROP TABLE users;
ALTER TABLE users_new RENAME TO users;

CREATE TRIGGER IF NOT EXISTS trg_users_external_id_guard_insert
BEFORE INSERT ON users
FOR EACH ROW
WHEN length(trim(COALESCE(NEW.external_id, ''))) < 1 OR length(COALESCE(NEW.external_id, '')) > 256
BEGIN
  SELECT RAISE(ABORT, 'users.external_id must be 1..256 chars');
END;

CREATE TRIGGER IF NOT EXISTS trg_users_external_id_guard_update
BEFORE UPDATE OF external_id ON users
FOR EACH ROW
WHEN length(trim(COALESCE(NEW.external_id, ''))) < 1 OR length(COALESCE(NEW.external_id, '')) > 256
BEGIN
  SELECT RAISE(ABORT, 'users.external_id must be 1..256 chars');
END;

-- Rebuild web_sessions table without role/scopes columns.
DROP INDEX IF EXISTS idx_web_sessions_token;

CREATE TABLE web_sessions_new (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id)
);

INSERT INTO web_sessions_new(id, user_id, token_hash, created_at, expires_at)
SELECT id, user_id, token_hash, created_at, expires_at FROM web_sessions;

DROP TABLE web_sessions;
ALTER TABLE web_sessions_new RENAME TO web_sessions;

CREATE INDEX IF NOT EXISTS idx_web_sessions_token ON web_sessions(token_hash);

PRAGMA foreign_keys=ON;
