-- Reconcile escalation tool permission ownership with policy contract.
-- Main agent can request human escalation; feature_builder cannot.
INSERT OR REPLACE INTO tool_permissions(principal_id, tool_name, effect)
VALUES ('main', 'request_human_escalation', 'allow');

DELETE FROM tool_permissions
WHERE principal_id = 'feature_builder' AND tool_name = 'request_human_escalation';
