CREATE TABLE IF NOT EXISTS schedule_dispatches (
  schedule_id TEXT NOT NULL,
  due_at TEXT NOT NULL,
  dispatched_at TEXT NOT NULL,
  PRIMARY KEY(schedule_id, due_at),
  FOREIGN KEY(schedule_id) REFERENCES schedules(id)
);
