ALTER TABLE whatsapp_instances
  ADD COLUMN callback_url TEXT NOT NULL DEFAULT '';

ALTER TABLE whatsapp_instances
  ADD COLUMN callback_by_events INTEGER NOT NULL DEFAULT 0;

ALTER TABLE whatsapp_instances
  ADD COLUMN callback_events_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE whatsapp_instances
  ADD COLUMN callback_configured INTEGER NOT NULL DEFAULT 0;

ALTER TABLE whatsapp_instances
  ADD COLUMN callback_last_error TEXT NOT NULL DEFAULT '';
