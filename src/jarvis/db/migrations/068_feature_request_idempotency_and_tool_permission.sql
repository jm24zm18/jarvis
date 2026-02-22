-- Speed up idempotent feature-request create lookups by trace/thread/reporter/title.
CREATE INDEX IF NOT EXISTS idx_bug_reports_feature_idempotency
ON bug_reports(kind, reporter_id, thread_id, trace_id, title, created_at);

-- Ensure main can execute the typed roadmap creation tool.
INSERT OR IGNORE INTO tool_permissions(principal_id, tool_name, effect)
VALUES ('main', 'create_feature_request', 'allow');
