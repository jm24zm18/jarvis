CREATE TRIGGER IF NOT EXISTS trg_users_external_id_guard_insert
BEFORE INSERT ON users
FOR EACH ROW
WHEN length(trim(COALESCE(NEW.external_id, ''))) < 1 OR length(COALESCE(NEW.external_id, '')) > 256
BEGIN
  SELECT RAISE(ABORT, 'users.external_id must be 1..256 chars');
END;

CREATE TRIGGER IF NOT EXISTS trg_users_external_id_guard_update
BEFORE UPDATE OF external_id ON users
FOR EACH ROW
WHEN length(trim(COALESCE(NEW.external_id, ''))) < 1 OR length(COALESCE(NEW.external_id, '')) > 256
BEGIN
  SELECT RAISE(ABORT, 'users.external_id must be 1..256 chars');
END;
