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
