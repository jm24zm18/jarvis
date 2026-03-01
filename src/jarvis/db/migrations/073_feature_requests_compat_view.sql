-- Compatibility view for legacy/tooling SQL that still references feature_requests.
DROP VIEW IF EXISTS feature_requests;

CREATE VIEW feature_requests AS
SELECT *
FROM bug_reports
WHERE kind = 'feature';
