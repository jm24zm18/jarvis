-- In Jarvis, 'main' should inherently have access to all tools.
-- We add wildcard permissions if we don't have a tools table, or specifically add the ones from seed.py
DELETE FROM tool_permissions WHERE principal_id = 'main';
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', 'echo', 'allow');
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', 'session_list', 'allow');
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', 'session_history', 'allow');
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', 'session_send', 'allow');
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', 'web_search', 'allow');
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', 'exec_host', 'allow');
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', 'skill_list', 'allow');
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', 'skill_read', 'allow');
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', 'skill_write', 'allow');
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', 'update_persona', 'allow');
INSERT INTO tool_permissions (principal_id, tool_name, effect) VALUES ('main', '*', 'allow');
