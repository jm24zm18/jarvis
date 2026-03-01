CREATE TABLE IF NOT EXISTS devswarm_tasks (
  id TEXT PRIMARY KEY,
  task_type TEXT NOT NULL DEFAULT 'feature'
    CHECK (task_type IN ('feature', 'bugfix', 'refactor')),
  description TEXT NOT NULL,
  repo_path TEXT NOT NULL,
  worktree_path TEXT NOT NULL,
  branch TEXT NOT NULL,
  base_branch TEXT NOT NULL DEFAULT 'dev'
    CHECK (base_branch = 'dev'),
  tmux_session TEXT NOT NULL,
  status TEXT NOT NULL
    CHECK (status IN ('queued', 'running', 'needs_attention', 'ready_for_review', 'done', 'failed')),
  attempt INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  model TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT 'lmstudio'
    CHECK (provider = 'lmstudio'),
  pr_number INTEGER,
  pr_url TEXT,
  checks_json TEXT NOT NULL DEFAULT '{}',
  last_error TEXT,
  completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_devswarm_tasks_status_updated
  ON devswarm_tasks(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_devswarm_tasks_branch
  ON devswarm_tasks(branch);

CREATE INDEX IF NOT EXISTS idx_devswarm_tasks_repo
  ON devswarm_tasks(repo_path, created_at DESC);
