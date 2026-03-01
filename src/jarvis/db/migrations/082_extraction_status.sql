ALTER TABLE state_extraction_watermarks
  ADD COLUMN extraction_status TEXT NOT NULL DEFAULT 'idle';

ALTER TABLE state_extraction_watermarks
  ADD COLUMN status_updated_at TEXT;

ALTER TABLE state_extraction_watermarks
  ADD COLUMN last_error TEXT;

CREATE INDEX IF NOT EXISTS idx_state_extraction_status
ON state_extraction_watermarks(extraction_status, status_updated_at);
