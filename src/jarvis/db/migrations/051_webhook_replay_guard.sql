CREATE TABLE IF NOT EXISTS webhook_delivery_receipts (
  source TEXT NOT NULL,
  delivery_id TEXT NOT NULL,
  received_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  PRIMARY KEY (source, delivery_id)
);

CREATE INDEX IF NOT EXISTS idx_webhook_delivery_receipts_expires
  ON webhook_delivery_receipts(expires_at);
