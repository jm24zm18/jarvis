-- Per-thread compaction threshold (NULL = use global default)
ALTER TABLE thread_settings ADD COLUMN compaction_threshold INTEGER DEFAULT NULL;
