## Jarvis 2.0 Master Certified Spec (QA-Ready)

  ### Brief Summary

  Jarvis 2.0 will be built as a parallel system (src/jarvis_v2, web_v2) and promoted only
  when it is fully working under strict gates.
  You are the only user, single approver, and final authority for critical gates.
  Execution is highly automated, but merge/deploy/destructive actions remain human-gated
  with strong policy controls and machine-verifiable evidence.

  ## 1. Delivery Model and Cutover

  1. Build v2 in parallel with v1.
  2. Keep stack: FastAPI + SQLite + React/Vite.
  3. Use separate URLs/ports plus admin UI toggle between v1/v2.
  4. Use separate DBs for v1 and v2 during dual-run.
  5. No v1-v2 data sync; v2 data comes from your real usage.
  6. Pause v1 background jobs when v2 is active.
  7. Cutover only when v2 is fully working.
  8. “Fully working” means:
  9. All domains complete.
  10. All tests green.
  11. Runbooks complete.
  12. 7-day stable dual-run.
  13. Zero P0/P1 incidents (any resets the window).
  14. SLO gates pass.
  15. Mandatory cutover certificate, drafted by Jarvis, signed by you.

  ## 2. Core Authority and Safety

  1. Critical gate approvals are human-admin only.
  2. Auto-run starts immediately after plan approval.
  3. Never auto-merge.
  4. Destructive actions are never automatic.
  5. Deployment executes automatically only after required approvals.
  6. Deploy commands must be explicit allowlist only.
  7. Allowlist changes are governance-gated.
  8. Deploy secrets use short-lived broker-issued scoped tokens.
  9. Token issuance auto-occurs after deploy gate approval.
  10. Tokens are single-use.
  11. Mandatory pre-prod backup for every prod deploy.
  12. Restore verification is weekly periodic drill (not every deploy).

  ## 3. Required Domains in v2

  1. Roadmap as source of truth with typed entities and lifecycle.
  2. Governance as centralized gate/policy engine with evidence model.
  3. Unified issue system (bug + feature + refactor + ops).
  4. Self-update staged pipeline with governance gates.
  5. Repo automation via typed service and strict safety rules.
  6. Swarm orchestration tied to unified issues.
  7. Memory platform with short-term + distilled long-term design.
  8. Redesigned agent system in agents_v2/.

  ## 4. Agent System v2

  1. Replace old trio docs with one strict typed manifest plus optional docs.
  2. Permissions/tool allowlists live in manifest only.
  3. Manifest hot-reloads on file change.
  4. Validation is strict fail-closed.
  5. Undeclared tools are denied for all agents except main.
  6. main undeclared tool calls require human approval per call.
  7. Approval caching is policy-based until revoked.
  8. Cache identity key is tool + argument pattern + target scope.

  ## 5. Execution and Retry Behavior

  1. Main run failures: auto-fix + retry up to 2, then escalate.
  2. If tests fail repeatedly, pause and request human help.
  3. PR opens automatically after green checks.
  4. PRs always from feature branch + PR flow, never direct push to dev.
  5. Branch format: v2/<type>/<issue-id>-<slug>.
  6. PR title format: [v2][<type>][<issue-id>] <summary>.
  7. PR template sections are mandatory.
  8. Missing template sections block PR creation.
  9. Machine-verifiable evidence is mandatory.
  10. Missing/invalid evidence blocks PR creation and merge.
  11. Rollback plan is auto-generated per PR.
  12. Rollback test in staging is mandatory for every PR.
  13. Rollback failure blocks PR and opens remediation.
  14. Remediation PRs also require rollback tests.

  ## 6. Governance, Remediation, and Overrides

  1. Risk classification is hybrid (rules + LLM; rules win).
  2. Production deploy approval is single human admin.
  3. Failed health checks trigger automatic rollback and immediate alert.
  4. Alerts go in-app and all configured channels.
  5. Governance failures auto-create remediation work.
  6. High-severity remediation blocks new feature work.
  7. Severity assignment is hybrid (rules + LLM + human override).
  8. Any gate override requires written justification.
  9. Any override auto-creates high-priority remediation.
  10. Security scanning is mandatory for every PR.
  11. Any security finding blocks PR creation.
  12. Security override allowed only with risk-acceptance record.
  13. Security override auto-creates high-priority remediation with due date.
  14. Due dates are auto-set by severity SLA:
  15. Critical 24h.
  16. High 72h.
  17. Medium 7d.
  18. Low 30d.
  19. Overdue High/Critical remediation blocks new feature execution.
  20. Blocked runs auto-pause and get unblock checklist.
  21. Unblocked runs auto-resume after mandatory quick validation.
  22. Pre-resume failures retry up to 2 with separate counter, then escalate.

  ## 7. Runtime Controls and Monitoring

  1. No hard timeout per run.
  2. Inactivity watchdog pauses run after 60 minutes no progress signal.
  3. Progress signals are tool completion, test result, commit, or state transition.
  4. Watchdog does one auto-recovery attempt before pause.
  5. Recovery failure triggers immediate alert + daily digest.
  6. Paused runs are never auto-canceled.
  7. Paused runs send reminders every 24h.
  8. Reminders include actionable controls (/resume, /cancel, /replan).
  9. /cancel requires reason and auto-learning note.
  10. Cancel moves linked item to blocked with reason.
  11. Cancel always creates follow-up assigned to you.

  ## 8. Roadmap and Backlog Behavior

  1. Roadmap states auto-update with audit logs.
  2. Jarvis auto-creates missing roadmap work items.
  3. Auto-created items default to backlog priority.
  4. No auto-close stale items.
  5. Items inactive 30 days get needs_review.
  6. needs_review triggers immediate alert + daily digest.
  7. needs_review always includes Jarvis next-step suggestion.

  ## 9. Memory Policy

  1. Short-term memory retention is 90 days.
  2. Daily long-term memory distiller runs before expiry.
  3. Distillation is hybrid: rule scoring + LLM judgment/summarization.
  4. Long-term memory is separate dedicated store/table.
  5. Long-term items are immutable and versioned by supersession.
  6. Distiller failures do 1 retry, then high-severity remediation.
  7. Distiller failure does not block normal execution.
  8. Distiller changes auto-commit with audit log.
  9. Daily digest includes memory distillation summary.

  ## 10. Notifications and Reporting

  1. Daily digest is mandatory.
  2. Daily digest schedule is 08:00 local time.
  3. Delivery is in-app + all configured channels.
  4. Critical events also alert immediately:
  5. Rollback.
  6. Gate override.
  7. P1 failures.
  8. Optimization reset events also send immediate + digest updates.

  ## 11. Performance and Provider Resilience

  1. No hard budget cap for runs.
  2. Soft-threshold warnings for high runtime/tool volume.
  3. 3 breaches in 7 days auto-create optimization remediation.
  4. Breach counters reset after verified optimization.
  5. Verification is automatic by Jarvis (metrics + tests).
  6. Provider fallback switching is automatic with audit log.
  7. 3 fallbacks in 24h auto-create ops item.
  8. Fallback incidents block features only when SLOs degrade.

  ## 12. SLO and Reliability Gates

  1. Explicit SLOs required for cutover.
  2. SLO scope is v2 only.
  3. Window is 7-day rolling.
  4. Thresholds:
  5. Availability >= 99.5%.
  6. Failed run rate <= 2%.
  7. MTTR <= 30 minutes.
  8. SLO breach blocks cutover and resets stability window.

  ## 13. Public API / Interface Changes

  1. New versioned API surface /api/v2/*.
  2. Core endpoints:
  3. Intake.
  4. Plans.
  5. Executions.
  6. Approvals.
  7. Rollbacks.
  8. Learn.
  9. Domain endpoints for roadmap/governance/issues/selfupdate/repo/swarm/memory.
  10. Breaking changes after launch only via new versioned endpoints.
  11. Migration guides/changelogs are mandatory and auto-generated with review.
  12. web_v2 uses OpenAPI-generated client/types; no hand-maintained drift.

  ## 14. Mandatory QA and Test Program

  1. Every run requires complete test plan before execution.
  2. Complete test plan must include:
  3. Unit checks.
  4. Integration checks.
  5. Regression checks.
  6. Rollback checks.
  7. If Jarvis cannot complete test plan, escalate to human before execution.
  8. Contract tests:
  9. OpenAPI snapshots.
  10. Generated client compile/type checks.
  11. Migration tests:
  12. Fresh install.
  13. Upgrade/backfill.
  14. Integrity checks.
  15. Behavioral E2E:
  16. Intake -> plan -> approval -> run -> gates -> close.
  17. Rejection/replan loops.
  18. Pause/resume/cancel flows.
  19. Rollback and remediation flows.
  20. Security/policy tests:
  21. Auth enforcement.
  22. Deny-by-default tool policy.
  23. Gate and override rules.
  24. DR tests:
  25. Mandatory staging DR drill before cutover.
  26. Successful drill must be within 7 days of cutover.
  27. DR failure blocks cutover and resets stability window.

  ## 15. Explicit Assumptions and Defaults

  1. Single-user model remains at v2 launch.
  2. Single-admin auth remains at v2 launch.
  3. You are sole certificate signer and gate approver.
  4. Human-in-the-loop remains for critical actions.
  5. Dual-run is required before cutover.
  6. Documentation must be updated in each implementation phase, including docs/PLAN.md.

  ## 16. Open Questions

  1. None currently blocking.
  2. This spec is decision-complete enough to execute implementation planning and backlog
     breakdown.
