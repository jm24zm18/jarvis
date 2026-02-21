-- Migration 060: durable agent run attempt lifecycle and recovery metadata

CREATE TABLE IF NOT EXISTS agent_run_attempts (
    trace_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT 'init',
    started_at TEXT NOT NULL,
    last_heartbeat_at TEXT NOT NULL,
    ended_at TEXT,
    failure_kind TEXT,
    failure_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    final_message_id TEXT,
    PRIMARY KEY(trace_id, attempt)
);

CREATE INDEX IF NOT EXISTS idx_agent_run_attempts_status_next_retry
    ON agent_run_attempts(status, next_retry_at);

CREATE INDEX IF NOT EXISTS idx_agent_run_attempts_status_phase_heartbeat
    ON agent_run_attempts(status, phase, last_heartbeat_at);

CREATE INDEX IF NOT EXISTS idx_agent_run_attempts_thread_status
    ON agent_run_attempts(thread_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_run_attempts_single_running
    ON agent_run_attempts(trace_id)
    WHERE status = 'running';
