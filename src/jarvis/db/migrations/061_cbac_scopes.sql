-- Add per-user and per-session CBAC scopes.
-- Admins keep ["*"] from column default.
-- Regular users are backfilled with a narrowed scope set.
-- Existing sessions are backfilled from their user row.

ALTER TABLE users ADD COLUMN scopes TEXT NOT NULL DEFAULT '["*"]';
ALTER TABLE web_sessions ADD COLUMN scopes TEXT NOT NULL DEFAULT '["*"]';

UPDATE users SET scopes='["self:read","self:write","memory:read","media:read","media:write"]'
  WHERE role='user';

UPDATE web_sessions SET scopes=(
  SELECT u.scopes FROM users u WHERE u.id=web_sessions.user_id
);
