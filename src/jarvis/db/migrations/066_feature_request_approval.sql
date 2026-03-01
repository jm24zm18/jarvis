-- Feature request approval state columns on bug_reports.
-- Backfill: existing feature rows default to 'pending'.
ALTER TABLE bug_reports ADD COLUMN approval_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE bug_reports ADD COLUMN approval_note TEXT NOT NULL DEFAULT '';
ALTER TABLE bug_reports ADD COLUMN approved_by TEXT;
ALTER TABLE bug_reports ADD COLUMN approved_at TEXT;
ALTER TABLE bug_reports ADD COLUMN rejected_by TEXT;
ALTER TABLE bug_reports ADD COLUMN rejected_at TEXT;

CREATE INDEX IF NOT EXISTS idx_bug_reports_kind_approval
    ON bug_reports(kind, approval_status, status, created_at DESC);
