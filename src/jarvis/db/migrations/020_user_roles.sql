ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user';

UPDATE users
SET role='admin'
WHERE id=(SELECT id FROM users ORDER BY created_at ASC LIMIT 1);

ALTER TABLE web_sessions ADD COLUMN role TEXT NOT NULL DEFAULT 'user';

UPDATE web_sessions
SET role=(
  SELECT u.role
  FROM users u
  WHERE u.id=web_sessions.user_id
);
