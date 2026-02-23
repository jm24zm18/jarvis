-- Migration 074: persist baseline dirty files snapshot per agent attempt

ALTER TABLE agent_run_attempts
    ADD COLUMN initial_dirty_files TEXT;
