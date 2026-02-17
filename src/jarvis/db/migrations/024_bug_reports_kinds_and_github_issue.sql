ALTER TABLE bug_reports ADD COLUMN kind TEXT NOT NULL DEFAULT 'bug';
ALTER TABLE bug_reports ADD COLUMN github_issue_number INTEGER;
ALTER TABLE bug_reports ADD COLUMN github_issue_url TEXT;
ALTER TABLE bug_reports ADD COLUMN github_synced_at TEXT;
ALTER TABLE bug_reports ADD COLUMN github_sync_error TEXT;

CREATE INDEX IF NOT EXISTS idx_bug_reports_kind ON bug_reports(kind);
CREATE INDEX IF NOT EXISTS idx_bug_reports_github_issue_number ON bug_reports(github_issue_number);
