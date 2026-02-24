# Change Safety

## Critical Invariants

- Tool runtime remains deny-by-default (`src/jarvis/tools/runtime.py`).
- Policy decisions must enforce lockdown/restart and permission checks (`src/jarvis/policy/engine.py`).
- Migration ordering is append-only and monotonic (`src/jarvis/db/migrations/*`).
- Event schema fields (`trace_id`, `span_id`, `event_type`) remain stable for observability.
- ID format prefixes are stable (`src/jarvis/ids.py`).
- Self-update evidence packets must include `file_refs`, `line_refs`, `policy_refs`, and `invariant_checks`.
- Self-update validation must preserve deterministic replay from the captured `baseline_ref`.
- Self-update propose path must reject governance-key mutations in `agents/*/identity.md` (`allowed_tools`, `risk_tier`, `max_actions_per_step`, `allowed_paths`, `can_request_privileged_change`).
- Persisted webhook/event logs must redact QR and pairing-code fields in `payload_redacted_json`.
- WhatsApp inbound processing must not return `500` when `whatsapp_thread_map` contains stale
  mappings; stale rows must be pruned/remapped before `messages` insert.
- Memory state reads/writes must enforce thread-scoped active-agent boundaries and emit governance denials on blocked mutation attempts.
- Every `agent.step.start` must resolve to a terminal attempt status in `agent_run_attempts`; stale `running` attempts must be recoverable without duplicating final assistant publication for the same trace.
- CBAC route and runtime gates must hold:
  - API scope checks must use `require_scope(...)` for scoped resources.
  - Policy `R9` scope filtering must not be bypassed in tool execution paths.
- Media attachment access must enforce owner-or-admin checks on download routes.
- Self-update sandbox mode must not execute smoke commands directly on host when `SELFUPDATE_SANDBOX_ENABLED=1`.
- `channel.typing.clear` events must be unequivocally guaranteed (e.g., via `finally` blocks) to prevent stuck client indicators.
- The system must maintain a periodic stall watchdog covering edge cases where thread processing is live but outbound loops hang, guaranteeing `runtime.stall.detected` emission and fallback recovery.
- State extraction must not block assistant reply persistence; extraction runs asynchronously and emits `state.extraction.queued -> complete|skipped|failed` lifecycle events.
- Assistant final output must pass leak-guard sanitization before message persistence; internal planning/tool payload artifacts must never be user-visible.
- Repeated failing tool calls within a single agent step must be suppressible to avoid deterministic failure loops.
- Assistant must not claim roadmap/feature-request mutation success unless an in-step verified write result exists; unverified claims must be blocked and logged (`agent.response.claim_blocked`).
- Feature-request create path must be idempotent for retry scenarios when `trace_id` is supplied.
- Follow-up heartbeat checks must remain opt-in per thread with ownership enforcement on management APIs; `no_reply` outcomes must not emit user-visible outbound messages.
- Feature-build runs must reject terminal success when deliverable evidence is missing (no allowed-scope diff and no explicit no-op blockers) and emit `feature.build.deliverable_gate.failed`.
- When deliverable evidence is missing, feature-build runs must emit a corrective system message and `feature.build.output.corrected` before retry/exhaustion so unverifiable completion claims are not left unqualified.
- Feature-build runs must fail fast on repeated consecutive `placeholder_response_after_tool_loop` outcomes (`feature.build.retry.denied`) to avoid deterministic retry churn.
- Feature-build execution attempts must not include write attempts against `RALPH_NEVER_EDIT_PATHS` or `PROTECTED_PATH_PATTERNS`; violations must block success finalization.
- `request_human_escalation` permission ownership must remain aligned with policy: allowed for `main`, denied for non-main principals.
- Retry-intent messages in exhausted feature-build threads must enqueue a fresh build run (`feature.build.retry.manual_enqueued`) instead of entering generic audit/tool-only loops.

## High-Risk Files

- `src/jarvis/config.py`
- `src/jarvis/db/queries.py`
- `src/jarvis/tools/runtime.py`
- `src/jarvis/policy/engine.py`
- `src/jarvis/orchestrator/step.py`

Any behavior change in these files should include focused tests and doc updates.

## Pre-Change Checklist

```bash
make lint
make typecheck
uv run pytest tests/unit -q
```

## Post-Change Verification

```bash
make test-gates
uv run jarvis doctor
curl -s http://127.0.0.1:8000/readyz
```

Sandbox-first self-update verification (when enabled):

```bash
docker build -f deploy/Dockerfile.sandbox -t jarvis-sandbox:latest .
SELFUPDATE_SANDBOX_ENABLED=1 make api
```

## Rollback Guidance

- DB schema issue: restore from snapshot with `deploy/restore_db.sh`.
- Runtime issue after deploy: rollback code via `deploy/rollback.sh <git-ref>`.
- Self-update issue: run rollback path in self-update pipeline and verify readiness.

## Agent Notes

- If auth/ownership logic changes, add integration tests for both `user` and `admin` paths.
- If migration changes behavior, document expected compatibility in `docs/architecture.md`.
- For auth identity inputs, enforce limits at both API and DB layers (request validation +
  migration-level guards) to prevent bypass paths.

## Related Docs

- `docs/README.md`
- `docs/testing.md`
- `docs/runbook.md`
- `docs/build-release.md`
- `docs/api-usage-guide.md`
