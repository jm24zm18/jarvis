ALTER TABLE system_state ADD COLUMN readyz_fail_streak INTEGER NOT NULL DEFAULT 0;
ALTER TABLE system_state ADD COLUMN rollback_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE system_state ADD COLUMN last_rollback_at TEXT;
ALTER TABLE system_state ADD COLUMN lockdown_reason TEXT NOT NULL DEFAULT '';
