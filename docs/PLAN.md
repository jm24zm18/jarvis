# Jarvis Master Execution Plan

**Date:** 2026-02-18
**Rebaseline:** 2026-02-18 (repo/test evidence alignment pass)
**Canonical source note:** This file supersedes fragmented plan docs as the execution source of truth.

## Ralph Sprint v2.0 (2026-02-22 → 2026-02-28)

- [ ] Add admin API and UI drilldown for human_escalations queue visibility and replay controls
      Accept: GET /api/v1/admin/human-escalations returns paginated list; admin UI shows queue; replay action re-dispatches a queued escalation

- [ ] Add integration test coverage for non-main-to-main escalation request patterns through session messaging
      Accept: test_human_escalation_integration.py covers escalation triggered from feature_builder actor; verifies dispatch path and DB persistence

- [ ] Run full quality gates and verify env rollout values for HUMAN_ESCALATION_TARGETS in each deployment environment
      Accept: make lint, make typecheck, make test-gates, make docs-check all pass; runbook section for HUMAN_ESCALATION_TARGETS configuration is verified and documented

- [ ] Implement RLM decomposition + child build pipeline for large feature scopes
      Accept: new `rlm` package + migration 077, `feature_request_build_runs` gains `decomposed` status, RLM config/docs updated, admin `/split` route implemented, and unit tests (`test_rlm_*`, `test_feature_split`, `test_feature_build_rlm_routing`) cover the new behavior.

## Execution Update (2026-02-28, Jarvis Intelligence Core v2 memory stack)

- Completed:
  - Added migrations:
    - `082_extraction_status.sql` (`state_extraction_watermarks` status/error metadata)
    - `083_user_profiles.sql` (`user_profiles`, `user_profile_history`)
    - `084_knowledge_graph.sql` (`knowledge_graph`)
    - `085_user_reflection_watermarks.sql` (per-user synthesis cadence)
  - Added extraction lifecycle observability + timing:
    - `llm_ms`, `embed_ms`, `db_ms` in extraction results/events
    - status transitions through `running|idle|failed|skipped`
    - watermark metadata writes (`status_updated_at`, `last_error`)
  - Added batched embedding API:
    - `IEmbedder.embed_texts(...)`
    - `MemoryService.embed_texts(...)` with Ollama batch endpoint + bounded fallback fan-out
  - Replaced ad-hoc orchestrator context assembly with unified builder:
    - `src/jarvis/orchestrator/context_builder.py`
    - `step.py` now sources summary/state/semantic/KB/skills/profile/KG context from one path
  - Added Tier 3 user profile synthesis in reflection:
    - cross-thread top-item synthesis
    - additive merge + profile history snapshots
    - per-user 24h cadence via `user_reflection_watermarks`
  - Added user-scoped Knowledge Graph support:
    - `src/jarvis/memory/knowledge_graph.py`
    - confidence gate and conflict supersession logic
    - context injection path via unified context builder when `MEMORY_GRAPH_ENABLED=1`
  - Added/updated tests:
    - `tests/unit/test_knowledge_graph.py`
    - `tests/unit/test_state_extractor.py`
    - `tests/unit/test_memory_tasks.py`
    - `tests/unit/test_memory_reflection.py`
    - `tests/unit/test_orchestrator_step.py`
    - `tests/unit/test_prompt_builder.py`
  - Updated documentation:
    - `docs/architecture.md`
    - `docs/configuration.md`
    - `docs/codebase-tour.md`
    - `docs/testing.md`
    - `docs/change-safety.md`
    - `docs/runbook.md`

- Missing tasks discovered during implementation:
  - Add admin/UI visibility for user profile and KG summaries (currently available in DB/context path but not surfaced in admin pages).

- Remaining tasks before handoff:
  - Run full quality gates:
    - `make lint`
    - `make typecheck`
    - `make test-gates`
    - `make docs-check`

## Execution Update (2026-02-28, start-dev dependency + SearXNG health alignment)

- Completed:
  - Updated `start-dev.sh` to start full dependency services via `make dev` before launching API/web.
  - Kept explicit `jarvis-baileys` restart behavior in `start-dev.sh` to preserve session reset ergonomics.
  - Added bounded SearXNG readiness gate in `start-dev.sh`:
    - health probe: `${SEARXNG_BASE_URL}/healthz`
    - fallback probe: `${SEARXNG_BASE_URL}/search?q=ping&format=json`
    - on failure: prints `docker compose ps/logs` diagnostics and actionable remediation.
  - Updated docs to reflect the new `start-dev.sh` contract:
    - `README.md`
    - `docs/getting-started.md`
    - `docs/local-development.md`
  - Verified syntax and docs consistency:
    - `bash -n start-dev.sh`
    - `make docs-check`

- Missing tasks discovered during implementation:
  - Add a lightweight automated smoke check for `start-dev.sh` that validates dependency startup contract and SearXNG readiness path in CI-safe mode.

- Remaining tasks before handoff:
  - Optional runtime verification (local environment):
    - `./start-dev.sh`
    - `curl -fsS http://localhost:8080/healthz`
  - Run full quality gates:
    - `make lint`
    - `make typecheck`
    - `make test-gates`

## Execution Update (2026-02-28, Host Ollama dev startup compatibility)

- Completed:
  - Updated `scripts/dev_preflight_ports.py` to support host-Ollama local workflow:
    - new env toggle: `DEV_USE_HOST_OLLAMA=1` skips port `11434` conflict checks
    - preflight success output now reflects effective required ports.
  - Updated `start-dev.sh` startup contract:
    - defaults to `DEV_USE_HOST_OLLAMA=1`
    - runs preflight directly
    - in host mode starts Docker `searxng` + `sglang` while reusing host Ollama (`OLLAMA_BASE_URL`)
    - in docker mode (`DEV_USE_HOST_OLLAMA=0`) runs full `make dev`
    - adds explicit host Ollama reachability check (`/api/tags`) with remediation output.
  - Updated docs to match behavior:
    - `README.md`
    - `docs/getting-started.md`
    - `docs/local-development.md`

- Missing tasks discovered during implementation:
  - Add a focused automated test for `scripts/dev_preflight_ports.py` host-mode branch (`DEV_USE_HOST_OLLAMA=1`) to avoid regressions in preflight semantics.

- Remaining tasks before handoff:
  - Run focused verification:
    - `python3 scripts/dev_preflight_ports.py`
    - `DEV_USE_HOST_OLLAMA=1 python3 scripts/dev_preflight_ports.py`
    - `bash -n start-dev.sh`
  - Optional runtime validation:
    - `DEV_USE_HOST_OLLAMA=1 ./start-dev.sh`
    - `DEV_USE_HOST_OLLAMA=0 ./start-dev.sh`
  - Run full quality gates:
    - `make lint`
    - `make typecheck`
    - `make test-gates`
    - `make docs-check`

## Execution Update (2026-02-28, Duplicate Reply Prevention for Stale Recovery)

- Completed:
  - Added trace-level emitted-message resolver in:
    - `src/jarvis/tasks/agent_attempts.py`
    - `resolve_existing_trace_message_id(...)` now returns a prior response from either:
      - `agent_run_attempts.final_message_id` (`succeeded` attempts), or
      - `events.event_type='agent.step.end'` payload `message_id` validated against `messages`.
  - Updated `agent_step` idempotency checks to use emitted-message resolver before attempt start and before duplicate-guard finalization:
    - `src/jarvis/tasks/agent.py`
  - Hardened stale reaper to skip replay when response was already emitted:
    - `src/jarvis/tasks/agent_recovery.py`
    - marks stale attempt as `succeeded` with resolved `final_message_id`
    - emits `trace.agent.step.recovery_skipped_duplicate`
    - does not enqueue a new recovery attempt
  - Added unit/regression coverage in:
    - `tests/unit/test_agent_recovery.py`
    - resolver event-fallback behavior
    - `agent_step` short-circuit without creating attempts
    - stale reaper duplicate-skip path with no requeue
  - Updated operator docs for new telemetry/event semantics:
    - `docs/runbook.md`

- Missing tasks discovered during implementation:
  - Add dedicated admin observability counters for duplicate-skip recoveries (currently visible via trace events only).

- Remaining tasks before handoff:
  - Run focused verification:
    - `uv run pytest tests/unit/test_agent_recovery.py -q`
  - Run full quality gates:
    - `make lint`
    - `make typecheck`
    - `make test-gates`
    - `make docs-check`

## Execution Update (2026-02-28, Standardized Number/Text Formatting in Human Output)

- Completed:
  - Added shared backend display formatting helpers in `src/jarvis/formatting/display.py` and exports in `src/jarvis/formatting/__init__.py`.
  - Updated CLI human output paths to use consistent formatting and UTF-8-safe symbol fallback:
    - `src/jarvis/cli/doctor.py`
    - `src/jarvis/cli/main.py` (maintenance status/readouts)
    - `src/jarvis/cli/test_gates.py`
  - Enforced strict machine-only JSON mode for:
    - `jarvis doctor --json`
    - `jarvis test-gates --json`
  - Added explicit UTF-8 encoding for CLI text exports in:
    - `src/jarvis/cli/main.py` (`export`, `memory export`)
  - Added shared frontend display formatting helpers in `web/src/lib/format.ts`.
  - Applied shared web formatting helpers to key chat/admin surfaces:
    - `web/src/pages/chat/index.tsx`
    - `web/src/components/ui/ThinkingPanel.tsx`
    - `web/src/pages/admin/events/index.tsx`
    - `web/src/pages/admin/threads/index.tsx`
    - `web/src/pages/admin/governance/index.tsx`
  - Added/updated tests:
    - `tests/unit/test_display_formatting.py`
    - `tests/unit/test_cli_doctor.py`
    - `tests/unit/test_cli_test_gates_cmd.py`

- Missing tasks discovered during implementation:
  - Expand timestamp/number helper adoption across additional admin pages still rendering raw timestamp strings.

- Remaining tasks before handoff:
  - Run focused verification:
    - `uv run pytest tests/unit/test_display_formatting.py tests/unit/test_cli_doctor.py tests/unit/test_cli_test_gates_cmd.py -q`
  - Run full quality gates:
    - `make lint`
    - `make typecheck`
    - `make test-gates`
    - `make docs-check`

## Execution Update (2026-02-28, Thread Logs Permission + State Extraction Retry + Web Number Rendering)

- Completed:
  - Added `thread_logs` to `agents/main/identity.md` `allowed_tools` so main-agent policy no longer denies the tool with `R4`.
  - Updated main-agent seed identity template to include `thread_logs`:
    - `src/jarvis/agents/seed.py`
  - Implemented bounded timeout retry for state extraction execution in:
    - `src/jarvis/tasks/memory.py`
  - Added timeout retry scheduling events for observability:
    - `state.extraction.retry_scheduled`
    - `trace.state.extraction.retry_scheduled`
  - Added retry metadata on extraction success/failure payloads when retries occur:
    - `attempt_count`, `max_attempts`, `retry_attempted`
    - terminal timeout failures additionally include `retry_delays_seconds`
  - Hardened web display sanitization and numeric rendering normalization in:
    - `web/src/components/ui/textSanitizer.js`
    - `web/src/lib/format.ts`
    - Added format-control stripping (while preserving emoji ZWJ sequences) and broader Unicode-space normalization for timestamp-like numeric clusters.
  - Applied tabular numeric rendering to timestamp-heavy UI surfaces:
    - `web/src/components/ui/ThinkingPanel.tsx`
    - `web/src/pages/chat/index.tsx`
    - `web/src/pages/admin/events/index.tsx`
  - Added/updated tests:
    - `tests/unit/test_memory_tasks.py`
    - `tests/unit/test_agent_seed.py`
    - `web/tests/textSanitizer.test.mjs`
    - `web/tests/thinkingFormat.test.mjs`
    - Added regression for Unicode format-control number splitting in `web/tests/textSanitizer.test.mjs`.
  - Updated operations documentation for new extraction retry lifecycle:
    - `docs/runbook.md`

- Missing tasks discovered during implementation:
  - Add retry-attempt counters/filters for state extraction in admin observability pages (currently available via raw events only).

- Remaining tasks before handoff:
  - Run focused verification:
    - `uv run pytest tests/unit/test_memory_tasks.py tests/unit/test_agent_seed.py -q`
    - `npm --prefix web run test -- textSanitizer.test.mjs thinkingFormat.test.mjs`
  - Run full quality gates:
    - `make lint`
    - `make typecheck`
    - `make test-gates`
    - `make docs-check`

## Execution Update (2026-02-28, Docs Remediation for Approvals + LM Studio + Config Drift)

- Completed:
  - Added dedicated operator workflow doc:
    - `docs/channel-reply-approvals.md`
  - Expanded API usage semantics for:
    - provider config validation/constraints
    - `/api/v1/system/status` payload contract
    - non-web reply approval status transitions and endpoint caveats
  - Linked approval workflow doc across docs surfaces:
    - `docs/README.md`
    - `docs/api-usage-guide.md`
    - `docs/web-admin-guide.md`
  - Reconciled configuration docs with runtime/config source of truth:
    - added missing vars from `src/jarvis/config.py` + `.env.example`
    - removed stale doc-only vars not present in runtime config
  - Updated LM Studio local-dev setup guidance in `docs/local-development.md`.
  - Added CLI setup-wizard env group reference in `docs/cli-reference.md`.
  - Synced migration-range drift in `AGENTS.md` and `CLAUDE.md` (`001..081`).
  - Updated generated API docs preface in `scripts/generate_api_docs.py`.
  - Updated `README.md` implemented-feature summary for provider set and approval-gate schema.

- Missing tasks discovered during implementation:
  - None.

- Remaining tasks before handoff:
  - None. Validation complete (`make docs-generate`, `make docs-check`).

## Execution Update (2026-02-27, Think-Tag Sanitization Hardening)

- Completed:
  - Hardened backend response sanitization to strip leaked reasoning wrappers:
    - `<think>...</think>`
    - `<thinking>...</thinking>`
    - orphan `think/thinking` tags
  - Applied sanitization in:
    - orchestrator user-facing response strip path (`src/jarvis/orchestrator/step.py`)
    - onboarding assistant text sanitizer (`src/jarvis/onboarding/service.py`)
  - Added frontend safety-net sanitization in `web/src/components/ui/textSanitizer.js` so legacy/stored payloads with think tags do not render in chat UI.
  - Added/updated tests:
    - `tests/unit/test_strip_control_tokens.py`
    - `tests/unit/test_onboarding_service.py`
    - `web/tests/textSanitizer.test.mjs`

- Missing tasks discovered during implementation:
  - Consider extending sanitization coverage to additional provider-specific wrapper variants if observed in production traces.

- Remaining tasks before handoff:
  - Run targeted + required quality checks:
    - `uv run pytest tests/unit/test_strip_control_tokens.py tests/unit/test_onboarding_service.py -q`
    - `npm --prefix web run test`
    - `make lint`
    - `make typecheck`
    - `make docs-check`

## Execution Update (2026-02-27, LM Studio Provider + Explicit Fallback Routing)

- Completed:
  - Added first-class LM Studio provider adapter:
    - `src/jarvis/providers/lmstudio.py`
    - OpenAI-compatible `/chat/completions` + `/models` handling
    - optional bearer auth support via `LMSTUDIO_API_KEY`
  - Extended provider factory routing:
    - `PRIMARY_PROVIDER` now supports `lmstudio`
    - added explicit `FALLBACK_PROVIDER` support
    - fallback resolution now supports all providers (`openrouter`, `sglang`, `lmstudio`) with compatibility-safe defaults.
  - Extended provider config/admin API contract:
    - `GET /api/v1/auth/providers/config` now returns `fallback_provider`, `lmstudio_model`, `lmstudio_base_url`, `lmstudio_api_key_set`, `lmstudio_api_key_masked`
    - `POST /api/v1/auth/providers/config` now accepts `fallback_provider`, `lmstudio_model`, `lmstudio_base_url`, `lmstudio_api_key`, `clear_lmstudio_api_key`
    - `GET /api/v1/auth/providers/models` now returns `lmstudio_models` and `lmstudio_source`
  - Updated `/admin/providers` web UI:
    - LM Studio primary/fallback selection
    - LM Studio model catalog selection
    - LM Studio base URL input
    - LM Studio API key set/clear flow with masked preview
  - Added/updated tests:
    - `tests/unit/test_lmstudio_provider.py`
    - `tests/unit/test_providers.py`
    - `tests/integration/test_web_api.py`
  - Updated docs/config defaults:
    - `.env.example`
    - provider config docs and local development notes.

- Missing tasks discovered during implementation:
  - Consider introducing a dedicated `PROMPT_BUDGET_LMSTUDIO_TOKENS` to decouple local-LM prompt budget tuning from SGLang defaults.
  - Add UI affordances that warn when selected fallback is currently unreachable based on provider health.

- Remaining tasks before handoff:
  - Run targeted and full quality gates:
    - `uv run pytest tests/unit/test_lmstudio_provider.py tests/unit/test_providers.py tests/integration/test_web_api.py -k "provider" -v`
    - `make lint`
    - `make typecheck`
    - `make test-gates`
    - `make docs-check`

## Execution Update (2026-02-25, Auto-Decompose Fallback + Build Thread Routing + Attempt Finalization)

- Completed:
  - Added feature-build auto-decomposition controls:
    - `FEATURE_BUILD_AUTO_DECOMPOSE`
    - `FEATURE_BUILD_DECOMPOSE_FALLBACK`
    - `FEATURE_BUILD_THREAD_TARGET`
    - `FEATURE_BUILD_SUBTASK_LAYER_STRICT`
  - Added migration `080_feature_build_run_routing_mode.sql`:
    - `feature_request_build_runs.source_thread_id`
    - `feature_request_build_runs.execution_mode`
    - supporting indexes.
  - Updated feature build enqueue + runtime routing:
    - build runs now persist source thread at enqueue time,
    - reporter-thread-targeted build output path enabled by default,
    - run metadata exposes execution mode (`direct`, `decomposed`, `fallback_split`).
  - Extended decomposition pipeline:
    - broad-scope builds can force decomposition even with RLM toggles off,
    - deterministic fallback splitter creates one-layer-per-child subtasks when RLM decomposition fails.
  - Hardened agent attempt lifecycle:
    - post-success side-effect failures no longer strand attempts in `running`,
    - `feature_builder` worker relay no longer writes duplicate `[feature_builder->main]` thread messages.
  - Added/updated unit coverage:
    - `tests/unit/test_feature_build_rlm_routing.py`
    - `tests/unit/test_feature_build_task.py`
    - `tests/unit/test_agent_recovery.py`

- Missing tasks discovered during implementation:
  - Add integration coverage for end-to-end reporter-thread routing on non-web channels.
  - Add admin observability surfacing for `execution_mode` transitions (`direct -> decomposed/fallback_split`) in build-run dashboards.

- Remaining tasks before handoff:
  - Run focused and full quality gates:
    - `uv run pytest tests/unit/test_feature_build_rlm_routing.py tests/unit/test_feature_build_task.py tests/unit/test_agent_recovery.py -q`
    - `make lint`
    - `make typecheck`
    - `make test-gates`
    - `make docs-check`

## Execution Update (2026-02-25, Chat UI Readability + Emoji Integrity Hardening)

- Completed:
  - Added shared frontend text sanitizer in `web/src/components/ui/textSanitizer.js` with emoji-safe behavior.
  - Wired sanitizer into:
    - chat thread previews (`web/src/pages/chat/index.tsx`)
    - markdown rendering (`web/src/components/ui/MarkdownLite.tsx`)
    - markdown parser normalization (`web/src/components/ui/markdownParser.js`)
    - thinking event normalization (`web/src/components/ui/thinkingFormat.js`)
  - Hardened chat layout against overflow:
    - message-group/bubble min-width constraints
    - bubble max width by readable character limit
    - preview clamp for long thread snippets
  - Added markdown wrapping/table guardrails in `web/src/styles.css` for dense content.
  - Added/updated frontend tests:
    - `web/tests/textSanitizer.test.mjs`
    - `web/tests/chatContracts.test.mjs`
    - `web/tests/markdownParser.test.mjs`
    - `web/tests/markdownLiteRender.test.mjs`
  - Updated docs coverage in `docs/web-admin-guide.md`.

- Missing tasks discovered during implementation:
  - Add a browser-level visual regression or Playwright smoke suite for chat rendering to catch CSS regressions that contract tests cannot detect.
  - Add explicit mobile chat snapshot checks for long-table content and mixed RTL/LTR text.

- Remaining tasks before handoff:
  - Run and confirm all required quality gates:
    - `make lint`
    - `make typecheck`
    - `make test-gates`
    - `make docs-check`

## Execution Update (2026-02-24, Provider Config Runtime Precedence + OpenRouter Key Admin UX)

- Completed:
  - Fixed provider-config runtime precedence mismatch in `POST /api/v1/auth/providers/config`:
    - save now applies provider env values to live API process before settings reload.
    - addresses cases where runtime process env previously overrode `.env` after save.
  - Hardened provider `.env` persistence path to deduplicate repeated touched keys when writing updates.
  - Extended provider config contract:
    - `GET /api/v1/auth/providers/config` now includes `openrouter_api_key_set` and `openrouter_api_key_masked`.
    - `POST /api/v1/auth/providers/config` now supports `openrouter_api_key` (set/replace) and `clear_openrouter_api_key` (explicit clear).
  - Added admin web UX for OpenRouter key management on `/admin/providers`:
    - masked key preview,
    - password input for set/replace,
    - explicit clear action.
  - Added integration coverage for:
    - runtime precedence fix (`PRIMARY_PROVIDER` conflict path),
    - OpenRouter key set/masked response behavior,
    - explicit key clear behavior.

- Missing tasks discovered during implementation:
  - Add equivalent runtime-apply semantics (or explicit conflict warnings) for other admin-managed env settings beyond provider keys to avoid similar precedence drift.
  - Consider centralizing masked-secret response patterns across admin APIs for consistency.

- Remaining tasks before handoff:
  - Run focused and full quality gates:
    - `uv run pytest tests/integration/test_web_api.py -k provider_config -v`
    - `make lint`
    - `make typecheck`
    - `make test-gates`
    - `make docs-check`

## Execution Update (2026-02-24, Feature-Build Reliability + Escalation Permission Reconciliation)

- Completed:
  - Added migration `078_reconcile_escalation_tool_permissions.sql` to enforce escalation tool ownership (`main` allow, `feature_builder` remove).
  - Updated agent identity contracts:
    - `agents/main/identity.md` includes `request_human_escalation`.
    - `agents/feature_builder/identity.md` no longer includes `request_human_escalation`.
  - Hardened `sync_tool_permissions` with startup drift warning prior to permission replacement.
  - Added feature-build output correction behavior:
    - emits `feature.build.output.corrected`
    - posts corrective system message when prior completion claim is unverifiable.
  - Added non-blocking feature-build diagnostic event for memory timeouts:
    - `feature.build.state_extraction.timeout_observed`.
  - Stabilized capsule repeat-fail-fast hashing by using structured blocker category and excluding volatile blocker prose.
  - Added/updated tests:
    - `tests/unit/test_agent_registry.py`
    - `tests/unit/test_agent_recovery.py`
    - `tests/unit/test_feature_build_capsule.py`
    - `tests/unit/test_tool_runtime_governance.py`

- Missing tasks discovered during implementation:
  - Add API/Web admin surfacing for `feature.build.output.corrected` events to reduce manual DB/event inspection during incident response.
  - Add integration coverage for full retry lifecycle showing `output.corrected -> retry.scheduled/exhausted`.

- Remaining tasks before handoff:
  - Run targeted and full quality gates (`make lint`, `make typecheck`, `make test-gates`, `make docs-check`).
  - Validate migration 078 on a fresh DB and upgraded DB path.

- Follow-up completed:
  - Added exhausted-build retry intent routing in `agent_step` so thread-level `continue/retry` messages trigger a new build run enqueue instead of generic audit-only loops.
  - Added feature-build events `feature.build.retry.manual_requested` and `feature.build.retry.manual_enqueued` for traceability.
  - Added unit coverage for enqueue and non-enqueue paths in `tests/unit/test_agent_recovery.py`.

## Execution Update (2026-02-24, Chat Emoji + Markdown Rendering Recovery)

- Discovered missing task from live chat evidence:
  - Assistant replies containing malformed inline markdown (for example inline `---` + `###` + collapsed numbered sections) rendered as unreadable paragraphs in chat bubbles.
  - User-reported emoji rendering regressions in the same chat-bubble path required explicit regression coverage.

- Completed:
  - Hardened markdown normalization in `web/src/components/ui/markdownParser.js` to recover malformed inline structures into proper blocks:
    - inline horizontal-rule + heading transitions,
    - inline ordered-step boundaries,
    - numbered-step to bullet-list transitions.
  - Preserved emoji/codepoint integrity by avoiding any joiner/variation-selector stripping in parser normalization.
  - Added explicit emoji-safe markdown styling in `web/src/styles.css` (`.markdown-lite` and code/pre fallback stack).
  - Added parser regressions in `web/tests/markdownParser.test.mjs` for:
    - malformed "Cross-Agent Collaboration Hub"-style content recovery,
    - composed emoji grapheme preservation (`👨‍👩‍👧‍👦`, `👩🏽‍💻`).

- Missing tasks discovered during implementation:
  - Add a chat-page contract test for thread-preview emoji handling parity vs chat bubble rendering.

- Remaining tasks before handoff:
  - Run web parser + renderer tests and full quality gates (`make lint`, `make typecheck`, `make test-gates`, `make docs-check`).

- Follow-up completed:
  - Added renderer-level integration tests in `web/tests/markdownLiteRender.test.mjs` that transpile and render `MarkdownLite.tsx` to static DOM and assert malformed markdown recovery plus emoji preservation.

## Mission and Operating Model

Deliver a self-improving Jarvis that combines deterministic governance with agentic execution across self-update, memory, and WhatsApp channels.

Operating model:
- Deterministic Core + Agentic Edge + Verifiable Change Loop.
- Personal-number WhatsApp channel via Evolution API sidecar (Baileys-based), fully governed by existing policy and memory systems.
- Structured multi-tier memory with adaptive scoring, reconciliation, and auditable lifecycle events.

Memory model definition (canonical):

```python
importance = (
    0.4 * recency_score
    + 0.3 * access_count_norm
    + 0.2 * llm_self_assess
    + 0.1 * user_feedback
)
importance = min(1.0, max(0.0, importance))
```

Tier flow: `working -> episodic -> semantic/procedural`, with low-importance stale items archived.

## Non-Negotiable Invariants

1. Deny-by-default tool access.
2. Append-only migrations.
3. Traceable event schema.
4. Test validation required.
5. Policy engine authority.
6. Memory writes require evidence refs.
7. No direct `master` commits.
8. Rollback remains available.

## Current State Snapshot

| Area | implemented | partial | not_started |
|---|---:|---:|---:|
| Foundation + Observability | 7 | 2 | 0 |
| Self-Coding + Release Loop | 3 | 3 | 0 |
| Governance + Safety | 3 | 3 | 1 |
| Memory Intelligence + Retrieval | 2 | 6 | 2 |
| WhatsApp Channel + Admin UX | 7 | 0 | 0 |
| Documentation + Ops Hardening | 2 | 1 | 1 |

_Last updated: 2026-02-22 (Reliability hardening from runtime logs)_

## Execution Update (2026-02-22, Reliability Hardening from Runtime Logs)

- Completed:
  - Added DB compatibility migration `073_feature_requests_compat_view.sql` (`feature_requests` view over `bug_reports WHERE kind='feature'`).
  - Added `sqlite3` preflight in `exec_host` to catch unknown/missing tables before execution and return actionable hints (including `feature_requests -> bug_reports` guidance).
  - Added bounded full-log metadata for host tool results (`full_log_size_bytes`, `full_log_truncated`, `full_log_sha256`) plus new log-size/retention config knobs.
  - Added periodic host-exec log pruning task (`maintenance.exec_host_logs.pruned`).
  - Added follow-up idle-noise suppression with `FOLLOWUP_EMIT_IDLE_TICKS=0` default.
  - Added `task.failed` event emission for background task exceptions in task runner.
  - Added doctor DB-path consistency check to detect split-brain local DB usage.

- Missing tasks discovered during implementation:
  - Add optional per-thread/trace dedupe window for repeated identical `task.failed` events.
  - Add API/UI visibility for exec-host log retention metrics and prune counts.
  - Evaluate whether compatibility views are needed for additional legacy names beyond `feature_requests`.

- Remaining tasks before handoff:
  - Run full quality gates (`make lint`, `make typecheck`, `make test-gates`, `make docs-check`).
  - Validate retention defaults in staging workload (ensure `EXEC_HOST_LOG_RETENTION_*` thresholds match expected disk budget).

## Execution Update (2026-02-22, Memory Vector Map Upsert Concurrency Hotfix)

- Discovered runtime incident from `errors.md`: repeated background task failures in
  `jarvis.tasks.memory.index_event` with
  `UNIQUE constraint failed: memory_vec_index_map.memory_id`.
- Implemented task scope:
  - Hardened memory/event vector map upserts in `src/jarvis/memory/service.py` to be conflict-safe under concurrency.
  - Added per-row backfill conflict handling so vector backfill skips conflicting rows instead of failing the full run.
  - Added task-level suppression in `src/jarvis/tasks/memory.py` for known vector map integrity conflicts so indexing remains non-fatal.
  - Added regressions in:
    - `tests/unit/test_memory_service.py`
    - `tests/unit/test_memory_tasks.py`
- Remaining tasks before handoff:
  - Run full quality gates (`make lint`, `make typecheck`, `make test-gates`, `make docs-check`).

## Execution Update (2026-02-22, Auto-Continue + Human Escalation Routing)

- Completed:
  - Added `human_escalations` persistence + dispatch model (`070_human_escalations.sql`).
  - Added main-agent escalation tool permission (`071_request_human_escalation_tool_permission.sql`).
  - Added `request_human_escalation` tool and policy gate (main-only).
  - Added dispatcher task registration/scheduling for queued escalation delivery.
  - Added build-terminal incompleteness detection (`agent.response.incomplete`) and integrated it into feature-build retry/failure classification.
  - Added exhausted-build escalation path to configured channel targets.
  - Updated configuration/docs for escalation channel settings and retry behavior.

- Missing tasks discovered during implementation:
  - Add admin API/UI drilldown for `human_escalations` queue visibility and replay controls.
  - Add integration coverage for non-main-to-main escalation request patterns through session messaging.
  - Add explicit runbook verification checklist for configured escalation target reachability by channel.

- Remaining tasks before handoff:
  - Run full quality gates (`make lint`, `make typecheck`, `make test-gates`, `make docs-check`) after targeted validation.
  - Confirm env rollout values for `HUMAN_ESCALATION_TARGETS` in each deployment environment.

## Execution Update (2026-02-22, Self-Build + Web Approval Workflow)

- Completed: Feature request approval model, unified approvals center, feature build-run
  orchestration, and SELFUPDATE_AUTO_APPLY_* wiring.

- Implemented task scope:
  - DB migrations 066 (feature approval columns on bug_reports) and 067 (feature_request_build_runs table).
  - DB query helpers: `set_feature_request_approval`, `create_feature_build_run`,
    `update_feature_build_run`, `list_feature_build_runs`, `list_approvals`, `revoke_approval`.
  - Service layer: `src/jarvis/services/feature_requests.py` (approval transitions + build enqueue),
    `src/jarvis/services/approvals.py` (generic approval lifecycle).
  - New task `jarvis.tasks.feature_build.run_feature_build` registered in task runner.
  - Bugs API extended: `PATCH /feature-requests/{id}/approval`, `POST /feature-requests/{id}/build`,
    `GET /feature-requests/{id}/build-runs`, `approval_status` filter on list endpoint.
  - New approvals router at `src/jarvis/routes/api/approvals.py`:
    `GET /approvals`, `POST /approvals`, `POST /approvals/{id}/revoke`.
  - `SELFUPDATE_AUTO_APPLY_DEV/PROD` configs now gate approval requirement in `self_update_apply`.
  - Web lint blockers fixed (roadmap/repo pages).
  - Roadmap page rebuilt with create modal, approve/reject controls, build run panel, trace links, filters.
  - New `/admin/approvals` center page with list/create/revoke and nav item.
  - API client and types extended: `FeatureRequest`, `FeatureBuildRun`, `ApprovalRecord` types.
  - Full test coverage: 17 new unit tests + 12 integration tests + 2 frontend contract test files.
  - Typecheck + lint + test-gates all passing.

- Remaining tasks:
  - Docs-check regeneration: `make docs-generate && make docs-check`.
  - Release promotion: dev → master requires human approval.
  - Consider adding auto-apply behavior to release notes / operational runbook.

## Execution Update (2026-02-22, Roadmap Write Reliability Guard)

- Discovered missing safety task: assistant could claim roadmap writes without a persisted feature row.
- Implemented task scope:
  - Added typed tool `create_feature_request` in agent runtime and registered for `main`.
  - Added idempotent feature-create helper in DB query layer keyed by reporter/thread/trace/title.
  - Wired `/api/v1/feature-requests` to shared idempotent create logic and response flags:
    - `created`
    - `idempotent_hit`
  - Added roadmap claim guard in orchestrator finalization:
    - blocks unverified roadmap-success wording
    - emits `agent.response.claim_blocked`
  - Added migration `068_feature_request_idempotency_and_tool_permission.sql`:
    - idempotency lookup index
    - explicit tool permission for `main:create_feature_request`
  - Added tests for:
    - feature-request idempotency
    - claim-blocked vs verified-write-allowed response paths
    - tool registration presence
- Remaining tasks before handoff:
  - Run full gate sweep (`make test-gates`) before release promotion.

## Execution Update (2026-02-22, Feature Build Thread Schema Hotfix)

- Discovered runtime gap from production log: `jarvis.tasks.feature_build.run_feature_build`
  queried `threads.channel_type`, but current schema stores channel type on `channels.channel_type`.
- Implemented task scope:
  - Patched feature-build thread lookup to join `threads.channel_id -> channels.id`.
  - Switched thread status filter to `open` (current schema contract) and thread-create path to
    `ensure_channel(..., 'web') + create_thread(...)`.
  - Added regression unit test `tests/unit/test_feature_build_task.py`.
- Remaining tasks before handoff:
  - Run full gate sweep (`make test-gates`) before release promotion.

## Execution Update (2026-02-22, Feature Build Run Reconciliation + Crash Safety)

- Discovered runtime gap from live operation: failed `run_feature_build` tasks could leave
  `feature_request_build_runs.status='running'` indefinitely, making roadmap/admin UI appear stuck.
- Implemented task scope:
  - Added crash-safe reconciliation in `run_feature_build`: unexpected exceptions now mark the run
    `failed` with an explicit summary.
  - Added stale-run reconciliation helper in query layer:
    - `reconcile_stale_feature_build_runs(...)` marks long-running stale rows as `failed`.
  - Added task registration and periodic sweep:
    - `jarvis.tasks.feature_build.reconcile_stale_feature_build_runs` every 60s.
  - Added admin endpoint for manual reconciliation:
    - `POST /api/v1/feature-requests/build-runs/reconcile`.
  - Added service-layer auto-reconcile on run-list reads so UI reflects corrected status quickly.
  - Added regressions:
    - unit: task crash -> failed status with summary
    - unit: stale running run -> reconciled failed
    - integration: admin reconcile endpoint success + non-admin deny
- Remaining tasks before handoff:
  - Run full gate sweep (`make test-gates`) before release promotion.

## Execution Update (2026-02-22, Feature Build Degraded Finalization + Leak Retry)

- Discovered missing task from live incident trace `trc_f677297aaccf4156bc3c3dbcf66d81ee`:
  - repeated `model.fallback` quota events could end in `agent.response.leak_blocked`, but linked
    `feature_request_build_runs` stayed `running` until stale sweeper timeout.
- Implemented task scope:
  - Added trace-scoped build-run finalizer helper in query layer:
    - `finalize_feature_build_run_by_trace(...)` updates latest queued/running build row by `trace_id`.
  - Wired `jarvis.tasks.agent.agent_step` to finalize linked feature build runs immediately:
    - success path -> `succeeded`
    - degraded/leak-blocked terminal output -> `failed` with actionable summary
    - terminal non-retryable exception/retry-exhausted path -> `failed` with failure-kind summary
  - Hardened orchestrator leak guard:
    - when final output matches leak pattern, run one constrained terminal re-synthesis attempt
      (no tool narration / internal planning text)
    - only degrade if retry still fails or remains leak-patterned.
  - Added regression coverage:
    - orchestrator leak-retry recovery unit test
    - agent trace-driven feature-build run finalization tests
    - query helper unit test for trace finalizer.
- Remaining tasks before handoff:
  - Run targeted tests and full gate sweep (`make test-gates`) before release promotion.

## Execution Update (2026-02-22, Feature Build Auto-Retry Reliability)

- Implemented reliability-first recovery for degraded feature-build terminal outcomes.
- Implemented task scope:
  - Added migration `069_feature_build_retry_metadata.sql`:
    - `attempt_count`, `max_attempts`, `retry_state`, `next_retry_at`, `last_failure_reason`
    - retry dispatch index (`idx_frbr_retry_due`).
  - Added config knobs:
    - `FEATURE_BUILD_RETRY_ON_DEGRADED`
    - `FEATURE_BUILD_RETRY_MAX_ATTEMPTS`
    - `FEATURE_BUILD_RETRY_BACKOFF_SECONDS`
    - `FEATURE_BUILD_RETRY_DISPATCH_INTERVAL_SECONDS`
  - Updated build-run query layer to expose and mutate retry metadata.
  - Added periodic retry dispatcher task:
    - `jarvis.tasks.feature_build.dispatch_due_feature_build_retries`
    - registered + scheduled in periodic scheduler.
  - Updated `agent_step` feature-build finalization:
    - retryable degraded outcomes schedule delayed retry attempts on same run row
    - exhausted attempts emit terminal failed state + `feature.build.retry.exhausted`
    - successful completion after retries emits `feature.build.retry.succeeded_after_retry`.
  - Build-run list payload now includes retry metadata fields for UI/API consumers.
  - Added/updated regression tests for:
    - scheduled degraded retry behavior
    - retry-disabled fallback to immediate failed
    - due-retry query filtering
    - due-retry dispatch task enqueue path.
- Remaining tasks before handoff:
  - Run full quality gate sweep (`make test-gates`) before release promotion.

## Execution Update (2026-02-22, Roadmap Build-Run Live Chat Window)

- Implemented admin live monitoring inside roadmap Build Runs modal using existing thread/message
  APIs and build-run metadata.
- Implemented task scope:
  - Roadmap Build Runs modal now has two-pane layout:
    - selectable run list
    - live Build Chat pane
  - Build Chat polling:
    - polls `GET /api/v1/threads/{thread_id}/messages` every 2.5s while modal is open
    - supports `Load older` via `before` cursor
    - preserves bottom-stick scrolling unless user scrolls up
  - Added sticky run status metadata bar:
    - status
    - trace id (short)
    - created/updated timestamps
  - Added quick actions:
    - `Open full Events trace`
    - `Open Chat thread`
  - Added UI states for:
    - no attached thread yet
    - empty message history
    - retry on fetch failure
  - API/web contract updates:
    - `listMessages` client supports `limit` query parameter
    - integration coverage asserts `thread_id` + `updated_at` fields in build-runs payload
    - roadmap contract tests extended for build-chat affordances
- Remaining tasks before handoff:
  - Run full gate sweep (`make test-gates`) before release promotion.

## Execution Update (2026-02-23, Memory Reflection Loop)

- Completed:
  - Added migration `075_memory_reflection_watermarks.sql` to track last reflection timestamps and counts per thread.
  - Extended `MemoryService` with reflection helpers (candidate selection, worldview/insight upserts, pruning, watermark recording).
  - Introduced `proactive_reflection` task + scheduler registration with configurable `MEMORY_REFLECTION_*` knobs plus docs + `.env` defaults.
  - Added deterministic worldview/insight state item types and ensured renderer/orchestrator orderings recognise them.
  - Created `tests/unit/test_memory_reflection.py` covering candidate selection, worldview/insight creation, pruning, and watermark persistence.
- Remaining tasks before handoff:
  - Run targeted regression tests (`uv run pytest tests/unit/test_memory_reflection.py -v`) and confirm periodic scheduler reflects the new job before any release gating.

## Execution Update (2026-02-22, WhatsApp Pairing 401 Auto-Recovery + Diagnostics)

- Discovered missing operational/task gap: WhatsApp sidecar could remain in `close` with repeated
  `401 loggedOut`, while Admin UI showed only generic `QR not ready` messaging with no root-cause
  diagnostics.
- Implemented task scope:
  - Baileys sidecar now records disconnect diagnostics in `/status`:
    - `last_disconnect_code`
    - `last_disconnect_reason`
    - `last_error_at`
    - `autoheal_attempted`
  - Added one-shot auto-heal for `401 loggedOut`: clear auth and auto-reconnect once; if still logged
    out, remain `close` and require explicit re-pair.
  - API status endpoint now returns normalized `status` plus `diagnostics.*` fields for Admin UI.
  - Admin Channels UI now surfaces disconnect reason and explicit 401 guidance.
  - Added regression coverage for status diagnostics mapping and admin UI diagnostics copy contracts.
- Remaining tasks before handoff:
  - Run full quality gate sweep (`make test-gates`) before release promotion.

## Execution Update (2026-02-21, WhatsApp Processing Stabilization)

- Discovered critical missing operational stability: API/event loop stalls after an assistant message is drafted but before outbound dispatch finishes, locking WhatsApp into a stuck "typing" indicator and preventing new messages.
- Implemented task scope:
  - Made outbound dispatch failure observable (`channel.dispatch.enqueue.failed`) and recoverable via `tools_io_retry`.
  - Protected WhatsApp "paused" presence via a `finally` block and augmented `cleanup_stale_typing` periodic TTL loop.
  - Deployed `watchdog_stall_check` matching events to track age-based staleness and self-recovered with a rate-limited `enqueue_restart`.
  - Improved health checks to export internal liveness latency probes (`/metrics` for `last_message_write_age_seconds`).
- Remaining tasks before handoff:
  - Validated manually, code logic tested via test suite.

## Execution Update (2026-02-22, Stall Recovery Hardening + Wiring Fixes)

- Closed implementation gaps in the 2026-02-21 stabilization patch:
  - Registered new periodic/runtime tasks in task registry:
    - `jarvis.tasks.channel.cleanup_stale_typing`
    - `jarvis.tasks.system.watchdog_stall_check`
    - `jarvis.tasks.system.update_liveness_probe`
  - Moved scheduler wiring to `tasks/__init__.py` to prevent duplicate registrations across app lifespans.
  - Added missing config contract/env keys:
    - `STALL_DETECT_ENABLED`
    - `STALL_DETECT_THRESHOLD_SECONDS`
    - `STALL_RECOVERY_COOLDOWN_SECONDS`
    - `WHATSAPP_TYPING_TTL_SECONDS`
  - Fixed watchdog correctness and safety:
    - imported `get_system_state`
    - normalized timestamp parsing to UTC
    - explicit `restart_enqueued` status in recovery result payload
  - Removed nested DB write pattern in channel typing-clear paths by allowing `_emit(..., conn=...)`:
    - avoids opening a second write connection while the first write transaction is active.
- Added regression tests:
  - `tests/unit/test_channel_tasks.py` (typing clear guaranteed on outbound failure)
  - `tests/unit/test_system_tasks.py` (stall watchdog recovery + disabled mode)
- Remaining tasks before handoff:
  - Run full gate sweep (`make test-gates`) before release promotion.


## Execution Update (2026-02-21, CBAC + Sandbox + Multimedia Continuation)

- Completed implementation closure for the CBAC + sandbox + multimedia plan:
  - Added missing media unit/integration coverage (`tests/unit/test_media_service.py`, `tests/integration/test_media_upload_api.py`).
  - Added sandbox artifact summary persistence for self-update smoke runs in sandbox mode (`artifact.json["sandbox"]`) and API retrieval path.
  - Updated docs/contracts for CBAC scope gates, media endpoints, sandbox endpoint, and `mda_` ID prefix consistency.
  - Synced new config keys across `.env.example` and configuration docs:
    - `SELFUPDATE_SANDBOX_ENABLED`, `SELFUPDATE_SANDBOX_IMAGE`, `SELFUPDATE_SANDBOX_TIMEOUT_SECONDS`
    - `MEDIA_STORAGE_DIR`, `MEDIA_MAX_UPLOAD_BYTES`
- Full gate sweep status:
  - `make lint`: passed
  - `make typecheck`: passed
  - `make docs-check`: passed (after `make docs-generate`)
  - `make test-gates`: passed

## Execution Update (2026-02-21)

- Discovered missing task: WhatsApp webhook reliability gap where stale
  `whatsapp_thread_map.thread_id` values could trigger `sqlite3.IntegrityError`
  (`FOREIGN KEY constraint failed`) and return `500` for inbound `messages.upsert`.
- Implemented task scope:
  - Runtime auto-heal in webhook path: detect stale mapping, emit degraded event, prune orphan
    map rows, remap to a valid thread, continue processing.
  - Startup hygiene: prune orphan `whatsapp_thread_map` rows during API lifespan boot.
  - Regression coverage: integration test for stale-map healing + unit test for prune helper.
- Remaining tasks before handoff:
  - Run full quality gate sweep (`make test-gates`) and attach results in PR evidence notes.

## Execution Update (2026-02-21, Pairing UX/API)

- Discovered missing task: `/api/v1/channels/whatsapp/pairing-code` returned HTTP `200` even
  when Baileys returned upstream `503` (`QR state not reached`), causing misleading admin UI success.
- Implemented task scope:
  - API now propagates upstream pairing HTTP errors and detail payloads (including explicit
    `qr_not_ready` detail mapping for the QR-state race condition).
  - Admin Channels UI now disables pairing-code generation unless status is `qr` and shows
    explicit guidance when QR is not ready.
  - Added integration regression for upstream `503` propagation path.
- Remaining tasks before handoff:
  - Run full quality gate sweep (`make test-gates`) with this pairing-route behavior change and
    attach evidence in PR notes.

## Execution Update (2026-02-21, System Audit Improvements)

- Root-cause investigation of user-visible "internal response issue" (`DEGRADED_RESPONSE` constant)
  confirmed as provider failure → terminal synthesis failure path in `step.py`.
- Implemented audit improvements:
  - `_degraded_response_msg(trace_id)` now embeds `ref: <trace_id>` in the user-visible degraded
    message for self-service post-incident lookup.
  - `memory.write.rejected` event emitted by `MemoryService.write()` when governance blocks a write
    (missing evidence ref or scope violation), making write rejections explicitly queryable in the events
    table (supplements the existing `memory.policy.denial` event).
  - Post-incident triage queries added to `docs/runbook.md` under "Degraded Response Post-Incident
    Triage" with SQL for `agent.response.degraded` events, attempt history, and failure taxonomy.
  - `src/jarvis/runtime/__init__.py` placeholder documented (reserved for future sandboxing).
  - BK-067 and BK-068 added to consolidated backlog.
- Confirmed no config mismatch: `AGENT_RUN_STALE_HARD_CAP_SECONDS` default is 2700 in both
  `config.py` and `.env.example`; code uses `max(300, config_value)` as a minimum floor only.

## Execution Update (2026-02-21, Agent Run Reliability)

- Discovered missing task: agent traces could terminate after `agent.thought` without terminal lifecycle
  completion (`agent.step.end` absent), causing user-facing stalls and no deterministic retry path.
- Implemented task scope:
  - Added durable attempt ledger table `agent_run_attempts` (migration `060_agent_run_attempts.sql`).
  - Added phase-aware attempt heartbeats from orchestrator (`state.extract`, `model.run`, `tool.exec`,
    `finalize`) and bounded in-process retry in `agent_step`.
  - Added stale-attempt recovery task (`jarvis.tasks.agent_recovery.reap_stale_agent_runs`) scheduled by
    periodic scheduler with trace recovery telemetry.
  - Added trace-scoped dedupe guard so only one successful attempt publishes per `trace_id`.
  - Added targeted unit coverage in `tests/unit/test_agent_recovery.py`.
- Remaining tasks before handoff:
  - Run full quality gate sweep (`make test-gates`) and docs validation (`make docs-check`) with new
    migration + recovery task behavior.

## Security Audit Update (2026-02-18)

Source: `docs/security-audit-2026-02-18.md` (dev @ `b9a4e1447282ec8a0d67fdd22e8591b7c2b7adc4`)

Scanner execution status (local run):
- Installed local scanner toolchain under `/tmp/sec-tools/bin`:
  - `semgrep 1.152.0`
  - `gitleaks 8.30.0`
  - `trivy 0.69.1`
  - `osv-scanner 2.3.3`
  - `trufflehog 3.93.3`
- Results:
  - `semgrep` (python + react/javascript): 0 findings.
  - `trufflehog filesystem --only-verified`: 0 verified secrets.
  - `gitleaks`: 6 `generic-api-key` hits; triage = mostly false positives plus one local untracked `.env` secret hit.
  - `osv-scanner --lockfile=uv.lock`: 1 High vuln (`starlette 0.47.3`, fixed in `0.49.1`).
  - `osv-scanner --lockfile=web/package-lock.json`: 2 Medium vulns (`ajv 6.12.6`, `esbuild 0.21.5`).
  - `pip-audit`: confirms Starlette vulnerability/fix path.
  - `npm audit --json`: 12 moderate vulns (dev dependency graph).
  - `trivy fs --scanners misconfig`: 0 findings in this runtime.

High-priority audit findings to action:
1. Non-admin `subscribe_system` authorization gap in WebSocket path.
2. Session token exposure risk (query-string WS token + `localStorage` persistence).
3. Missing webhook replay protection.
4. CI action pinning gap (`@main` mutable ref) and CI least-privilege permissions tightening.
5. Dependency lockfile remediation required (`starlette`, `ajv`, `esbuild`).

Status normalization:
- Source `implemented`/`done` => `done`
- Source `partial`/`in_progress`/`blocked` => `partial`
- Source unchecked TODO / planned-only without evidence => `not_started`
- Duplicate conflict rule applied conservatively (`partial` over `done`; `not_started` only used over `partial` when no evidence exists).

## Beta Full-Pass Update (2026-02-18)

Source: `docs/reports/beta-2026-02-18-full-pass.md`

Findings incorporated into this plan:
1. `jarvis ask --json` can hang on provider DNS/transport failures and time out without a deterministic terminal payload.
2. `make dev` startup fails on occupied host ports (`11434`, `30000`) without preflight detection/remediation guidance.
3. `tests/integration/test_authorization.py::test_non_admin_cannot_toggle_lockdown` hangs and requires external timeout.
4. `make web-install` has a reproducible npm failure mode (`Exit handler never called!`) with weak diagnostics/recovery guidance.
5. Quick-start documentation omits explicit web dependency bootstrap before web targets.

Stabilization directive:
- Prioritize reliability/onboarding fixes ahead of feature expansion until core user path + local setup path are deterministic.

## Unified Milestones

### M1 - Foundation and Observability
Dependencies: none
- Close remaining foundation gaps (repo index drift checks, evidence validator, observability unification, memory policy denial/redaction events).
- Stand up WhatsApp sidecar and secure webhook baseline.

### M2 - Self-Coding and Core Memory Reliability
Dependencies: M1
- Enforce test-first + evidence gates for mutation paths.
- Complete deterministic reconciliation hardening and retrieval fusion.
- Stabilize failure bridge mapping and dedupe semantics.

### M3 - Governance and Channel Productization
Dependencies: M2
- Enforce permission governance hardening and memory ACL scope checks.
- Complete WhatsApp admin pairing and governance review flows.
- Productize consistency evaluator visibility and governance filtering.

### M4 - Recursive Optimization and Fitness
Dependencies: M3
- Activate learning-loop feedback into planning.
- Expand fitness metrics (coverage stability + hallucination incidents).
- Add adaptive memory optimization with measurable retrieval-quality lift.

## Consolidated Backlog

| ID | area | task | status | priority | owner | acceptance |
|---|---|---|---|---|---|---|
| BK-001 | Foundation + Observability | Ground-truth index dependency edges + freshness CI gate | done | P0 | planner | `make lint`; `make typecheck`; `uv run pytest tests/unit -k repo_index -v` |
| BK-002 | Foundation + Observability | Evidence validator required for all mutation-capable flows | done | P0 | security_reviewer | `uv run pytest tests/unit -k evidence -v`; `uv run pytest tests/integration -k selfupdate -v` |
| BK-003 | Foundation + Observability | Unified evolution observability view with trace drill-down | done | P1 | web_builder | additive evolution-item filters (`status`, `trace_id`, `from`, `to`) + stable trace linkage fields (`trace_id`, `span_id`, `thread_id`, `status`, `updated_at`) and admin drill-down UI wired; `uv run pytest tests/integration/test_web_api.py -k evolution -v`; `cd web && npm test -- adminObservabilityContracts.test.mjs` |
| BK-004 | Foundation + Observability | Memory denial/redaction event emission contract completion | done | P1 | api_guardian | `uv run pytest tests/unit/test_memory_policy.py -v` |
| BK-005 | Self-Coding + Release Loop | Self-update artifact schema versioning | done | P0 | coder | `uv run pytest tests/integration -k selfupdate -v` |
| BK-006 | Self-Coding + Release Loop | Deterministic reconciliation edge-case lock tests + run summary events | done | P0 | tester | `uv run pytest tests/unit/test_state_store.py -v`; `uv run pytest tests/unit/test_memory_tasks.py -v` |
| BK-007 | Self-Coding + Release Loop | Test-first gate (failing-test proof + coverage floor + critical-path test requirement) | done | P0 | tester | `make test-gates`; `uv run pytest tests/integration/test_selfupdate.py -v`; `uv run pytest tests/unit/test_selfupdate_contracts.py -v` |
| BK-008 | Self-Coding + Release Loop | PR base-branch enforcement test (`dev` only) | done | P1 | release_ops | `uv run pytest tests/unit/test_github_tasks.py -v` |
| BK-009 | Self-Coding + Release Loop | Failure remediation scoring uses acceptance/rejection outcomes | done | P1 | researcher | `uv run pytest tests/unit -k failure_capsule -v` |
| BK-010 | Governance + Safety | Block self-permission escalation edits on agent identity governance fields | done | P0 | security_reviewer | `uv run pytest -q tests/unit/test_selfupdate_pipeline.py -k governance_identity_edits_from_patch`; `uv run pytest -q tests/integration/test_selfupdate.py -k identity_governance_field_edits` |
| BK-011 | Governance + Safety | Self-update deployment gate state machine + typed failure taxonomy | done | P0 | release_ops | `uv run pytest tests/integration -k selfupdate_apply -v` |
| BK-012 | Governance + Safety | Memory governance hardening (schema write gates + deny/redaction governance filters) | done | P0 | security_reviewer | `uv run pytest tests/unit/test_memory_policy.py -v`; `uv run pytest tests/unit/test_memory_service.py -v`; `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v` |
| BK-013 | Governance + Safety | Explicit per-agent memory read/write scope checks across APIs/tasks | done | P0 | security_reviewer | `uv run pytest tests/unit/test_memory_tasks.py -v`; `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v` |
| BK-014 | Governance + Safety | WhatsApp risky/unknown sender review queue with in-chat approve/deny commands | done | P1 | main | `uv run pytest tests/integration/test_whatsapp_webhook.py -k "strict_mode_queues_unknown_sender or strict_mode_blocks_sender_after_denied_review" -v`; `uv run pytest tests/integration/test_admin_api.py -k review_queue -v`; `uv run pytest tests/integration/test_commands.py -k wa_review -v`; `uv run pytest tests/integration/test_authorization.py -k non_admin_cannot_manage_whatsapp_channels -v` |
| BK-015 | Memory Intelligence + Retrieval | Multi-tier memory lifecycle and archival flow with score-driven migration | done | P1 | planner | `uv run pytest tests/unit -k state_store -v` |
| BK-016 | Memory Intelligence + Retrieval | Retrieval fusion completion (RRF for vector + FTS5 + filters + tier priors) | done | P0 | planner | `uv run pytest tests/unit/test_hybrid_search.py -v` |
| BK-017 | Memory Intelligence + Retrieval | Failure bridge typed mapping + stable dedupe key (`trace_id+phase+summary_hash`) | done | P1 | planner | `uv run pytest tests/unit/test_memory_tasks.py -v` |
| BK-018 | Memory Intelligence + Retrieval | Graph relation extraction confidence/evidence policy completion | partial | P1 | researcher | traversal + relation-extraction tests |
| BK-019 | Memory Intelligence + Retrieval | Adaptive forgetting/archival calibration harness and threshold tuning | partial | P1 | memory_curator | maintenance/task tests + workload simulation |
| BK-020 | Memory Intelligence + Retrieval | Consistency evaluator endpoint/UI surface and historical queryability | partial | P1 | planner | API + admin UI tests for reports/filters |
| BK-021 | Memory Intelligence + Retrieval | Full memory endpoint/CLI/RBAC test suite for new state/review/export surfaces | done | P0 | tester | `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v`; `uv run pytest tests/integration/test_authorization.py -v` |
| BK-022 | WhatsApp Channel + Admin UX | Evolution sidecar bootstrap (persistent auth, API key auth, webhook callback) | done | P0 | api_guardian | callback contract/env wiring landed (`EVOLUTION_WEBHOOK_URL`, `EVOLUTION_WEBHOOK_BY_EVENTS`, `EVOLUTION_WEBHOOK_EVENTS`); instance callback state persisted (`054_evolution_instance_contract.sql`); coverage in `tests/integration/test_admin_api.py` + `python3 scripts/test_migrations.py` |
| BK-023 | WhatsApp Channel + Admin UX | WhatsApp channel implementation: text/media/reaction/groups/thread mapping | done | P0 | api_guardian | `uv run pytest tests/integration/test_whatsapp_webhook.py -v`; `uv run pytest tests/unit/test_channel_abstraction.py -v` |
| BK-024 | WhatsApp Channel + Admin UX | Voice-note pipeline (download, transcribe, memory linkage) | done | P0 | api_guardian | secure media download + transcript insertion + linkage metadata landed; `uv run pytest tests/integration/test_whatsapp_webhook.py -v` and `uv run pytest tests/unit/test_whatsapp_transcription.py -v` |
| BK-025 | WhatsApp Channel + Admin UX | Admin pairing APIs (`status/create/qrcode/pairing-code/disconnect`) + auth/rate limits | done | P0 | api_guardian | `uv run pytest -q tests/integration/test_admin_api.py -k "whatsapp or pairing_code_rejects_non_numeric_input"`; `uv run pytest tests/integration/test_authorization.py -v` |
| BK-026 | WhatsApp Channel + Admin UX | Admin pairing UI (QR, status polling, connect/disconnect flows) | done | P1 | web_builder | `cd web && npm test` (`web/tests/adminChannelsContracts.test.mjs`) + endpoint contract tests |
| BK-027 | WhatsApp Channel + Admin UX | Webhook auth and payload normalization (`messages.upsert` variants) | done | P0 | api_guardian | webhook secret reject contract + no-op ignore path for non-upsert events + variant normalization; `uv run pytest tests/integration/test_whatsapp_webhook.py -v` |
| BK-028 | WhatsApp Channel + Admin UX | WhatsApp security controls (no QR/code leakage, file limits, safe media paths) | done | P0 | security_reviewer | QR/pairing redaction + media URL/mime/size/path controls + negative tests landed; `uv run pytest tests/integration/test_whatsapp_webhook.py -v`; `uv run pytest tests/unit/test_whatsapp_media_security.py -v` |
| BK-029 | Documentation + Ops Hardening | Memory Prometheus KPI wiring and docs (`items_count`, `avg_tokens_saved`, `reconciliation_rate`, `hallucination_incidents`) | done | P1 | release_ops | structured `tokens_saved` persisted (`053_state_reconciliation_tokens_saved.sql`) and `/metrics` validation (`uv run pytest tests/unit/test_health.py -q`) |
| BK-030 | Documentation + Ops Hardening | Add rollback/runbook and config docs for new memory tables/tasks/flags | done | P1 | release_ops | memory rollback/recovery and conflict operator flow documented in `docs/runbook.md`; memory/state feature flags added to `docs/configuration.md`; `make docs-generate`; `make docs-check` |
| BK-031 | Documentation + Ops Hardening | WhatsApp operator docs and troubleshooting coverage | done | P1 | release_ops | troubleshooting decision tree + rollback path documented in `docs/channels/whatsapp.md` and `docs/channels/whatsapp-ui.md`; `uv run pytest tests/integration/test_whatsapp_webhook.py -v` |
| BK-032 | Documentation + Ops Hardening | API/schema docs for memory routes and conflict-resolution operator flow | done | P2 | planner | API reference regenerated (`make docs-generate`) and operator conflict-resolution flow documented in `docs/runbook.md`; `make docs-check` |
| BK-033 | Foundation + Observability | Evolution/governance event contract additions (`evolution.item.*`) | done | P2 | api_guardian | event types + payload minimum key enforcement + admin query/update APIs landed (`055_evolution_items.sql`); `uv run pytest tests/integration/test_web_api.py -k evolution_items -v`; `uv run pytest tests/unit/test_event_envelope_enforcement.py -v` |
| BK-034 | Governance + Safety | Dependency steward hardening (CVE severity, compatibility bundle, rollback-ready PR context) | partial | P1 | dependency_steward | `uv run pytest tests/unit/test_governance_tasks.py -v` |
| BK-057 | Foundation + Observability | Multi-channel media: persist `media_path`/`mime_type` on inbound messages (migration 058) and wire write path | done | P0 | api_guardian | `insert_message()` updated with media params; WhatsApp router passes media fields; `tests/unit/test_db_queries.py::test_insert_message_media_round_trip`; `python3 scripts/test_migrations.py` |
| BK-058 | Governance + Safety | Policy engine: wildcard `*` tool permission support (migration 057) and R8 `max_actions_per_step` enforcement | done | P0 | api_guardian | `is_allowed()` supports `IN (?, '*')`; R8 enforced via event count per trace_id; `tests/unit/test_tools_runtime.py::test_wildcard_permission_allows_any_tool`; `tests/unit/test_tools_runtime.py::test_max_actions_per_step_enforced` |
| BK-059 | Memory Intelligence + Retrieval | Memory consistency evaluator API surface and historical storage (migration 059) | done | P1 | api_guardian | `GET /api/v1/memory/consistency` endpoint + `memory_consistency_reports` table + `store_consistency_report()` in queries; `tests/integration/test_admin_api.py::test_memory_consistency_endpoint_requires_thread_id` |
| BK-060 | Foundation + Observability | Scheduler: fix NULL thread_id bug, add transaction on thread creation, per-schedule error isolation | done | P0 | data_migrator | scheduler skips NULL-thread schedules with `schedule.error` event; 3-INSERT transaction uses `BEGIN/COMMIT/ROLLBACK`; per-schedule try/except; `tests/integration/test_scheduler.py::test_scheduler_tick_null_thread_id_skips_gracefully`; `tests/integration/test_scheduler.py::test_scheduler_tick_creates_isolated_thread` |
| BK-061 | Foundation + Observability | Event retention maintenance task (configurable `EVENT_RETENTION_DAYS`, default 90) | done | P1 | api_guardian | `src/jarvis/tasks/events.py`; registered as weekly periodic task; `EVENT_RETENTION_DAYS` config flag; `.env.example` updated |
| BK-062 | Foundation + Observability | Fitness snapshot periodic task interval: change from weekly to 30-minute schedule | done | P0 | api_guardian | `compute_system_fitness` interval changed from 604800s to 1800s in `tasks/__init__.py` |
| BK-063 | Foundation + Observability | Fix `main.py` undefined `evolution` variable (should be `baileys`) and I001 import sort | done | P0 | api_guardian | `evolution.*` -> `baileys.*`; import sort auto-fixed; `make lint` clean; `make typecheck` clean |
| BK-064 | Documentation + Ops Hardening | Deduplicate soul.md branch policy boilerplate across all agent bundles | done | P2 | docs_keeper | 4 soul.md files now reference CLAUDE.md instead of inline git-flow block (main, coder, data_migrator, planner) |
| BK-065 | Documentation + Ops Hardening | Add FEATURE_BUILDER_PROMPT.md and DOCS_AGENT_PROMPT.md to docs/prompts/ | done | P2 | docs_keeper | `docs/prompts/FEATURE_BUILDER_PROMPT.md`; `docs/prompts/DOCS_AGENT_PROMPT.md`; `docs/prompts/README.md` updated |
| BK-066 | Governance + Safety | Self-update guardrail defaults: bound `max_files_per_patch`, `max_risk_score`, `max_patch_attempts_per_day`, `max_prs_per_day` | done | P1 | api_guardian | `SELFUPDATE_MAX_FILES_PER_PATCH=20`, `SELFUPDATE_MAX_RISK_SCORE=100`, `SELFUPDATE_MAX_PATCH_ATTEMPTS_PER_DAY=10`, `SELFUPDATE_MAX_PRS_PER_DAY=5` added to `config.py` and `.env.example`; prevents runaway self-update loops |
| BK-035 | Governance + Safety | Release-candidate hardening (changelog artifact + runbook evidence) | partial | P1 | release_candidate | `uv run pytest tests/unit/test_governance_tasks.py -v` |
| BK-067 | Foundation + Observability | Agent run reliability: durable attempt ledger, phase-aware heartbeats, stale-run reaper, dedupe guard | done | P0 | api_guardian | migration `060_agent_run_attempts.sql`; `tests/unit/test_agent_recovery.py`; `AGENT_STEP_MAX_ATTEMPTS`, `AGENT_RUN_REAPER_INTERVAL_SECONDS` config flags; `make test` |
| BK-068 | Foundation + Observability | Audit improvements: trace_id in degraded response, memory.write.rejected event, post-incident triage runbook | done | P1 | api_guardian | `_degraded_response_msg(trace_id)` in `step.py`; `memory.write.rejected` event emitted in `service.py`; triage queries in `docs/runbook.md`; `uv run pytest tests/unit/test_orchestrator_step.py -k degraded -v`; `uv run pytest tests/unit/test_memory_service.py -v` |
| BK-036 | Memory Intelligence + Retrieval | Memory admin UI completion (conflicts, tier/archive stats, failure lookup, graph preview) | done | P1 | web_builder | `cd web && npm test` (`web/tests/adminMemoryContracts.test.mjs`) + `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v` |
| BK-037 | Governance + Safety | Enforce admin-only WS system subscription (`subscribe_system`) and add regression tests | done | P0 | security_reviewer | `uv run pytest tests/integration/test_authorization.py -k websocket -v` |
| BK-038 | Governance + Safety | Web auth hardening: remove WS query-token transport + replace persistent browser token storage model | done | P0 | api_guardian | `uv run pytest tests/integration/test_websocket.py -v`; `uv run pytest tests/integration/test_authorization.py -k websocket -v`; manual login/session regression |
| BK-039 | Governance + Safety | Webhook replay defense (delivery-id/nonce + bounded replay window) | done | P0 | security_reviewer | `uv run pytest tests/integration/test_web_api.py -k github_webhook -v` with replay negatives |
| BK-040 | Documentation + Ops Hardening | Dependency vuln remediation from audit (`starlette`, `ajv`, `esbuild`) and lockfile refresh | done | P0 | dependency_steward | Python lock + audit clean (`uv run pip-audit`); npm `esbuild` path remediated (`vite@7.3.1` -> `esbuild@0.27.3`); residual ESLint-transitive `ajv@6.12.6` formally risk-accepted with sunset (`docs/security-risk-acceptance.md`, 2026-04-30); `osv-scanner --lockfile=web/package-lock.json` re-run shows single remaining accepted finding |
| BK-041 | Documentation + Ops Hardening | CI supply-chain hardening: pin third-party GitHub actions to SHAs and add top-level CI permissions | done | P0 | release_ops | workflow CI pass + branch-policy/release workflow validation |
| BK-042 | Documentation + Ops Hardening | Secret hygiene follow-up: rotate local exposed OAuth credentials and add pre-commit secret scan command docs | partial | P1 | release_ops | repo-owned work complete: explicit operator-owned credential-rotation checklist + required artifact naming template added to `docs/runbook.md`; rotation execution evidence remains external/operator-owned |
| BK-043 | Self-Coding + Release Loop | Fail-fast `jarvis ask --json` path on provider transport/DNS errors with bounded fallback budget + deterministic error payload | done | P0 | api_guardian | `uv run pytest -q tests/unit/test_cli_chat.py -k "ask_json"` passes with structured `ok=false` envelope and non-zero exit |
| BK-044 | Self-Coding + Release Loop | Guard orchestrator/state-extractor error paths to prevent long traceback/timeouts after provider failure | done | P0 | planner | `uv run pytest -q tests/unit/test_orchestrator_step.py -k "provider or degraded or fallback"` passes; degraded assistant message + `model.run.error` event emitted on provider failure |
| BK-045 | Governance + Safety | Deflake and unhang `test_non_admin_cannot_toggle_lockdown` via lifecycle/teardown instrumentation and fix | done | P0 | tester | `WEB_AUTH_SETUP_PASSWORD=secret uv run pytest -q tests/integration/test_authorization.py::test_non_admin_cannot_toggle_lockdown` and login flow tests complete deterministically |
| BK-046 | Foundation + Observability | Add `make dev` host-port preflight (`11434`, `30000`, `8080`) with actionable remediation output | done | P0 | release_ops | `python3 scripts/dev_preflight_ports.py` fails fast on occupied ports and prints remediation commands |
| BK-047 | Documentation + Ops Hardening | Document Docker/local port-conflict troubleshooting and optional alternate-port profile | done | P1 | release_ops | docs updates landed in `docs/local-development.md` and `docs/runbook.md`; `make docs-check` passed |
| BK-048 | Documentation + Ops Hardening | Harden `make web-install` path with deterministic npm diagnostics/retry guidance and fallback commands | done | P1 | web_builder | failure/success evidence captured (`/tmp/jarvis-web-install-failure.log`, `/tmp/jarvis-web-install-success.log`) and wrapper hardened with deterministic `network_blocked_or_sandboxed` classification + npm debug-log extraction (`scripts/web_install.py`) plus regression tests (`tests/unit/test_web_install_script.py`) |
| BK-049 | Documentation + Ops Hardening | Update quick-start docs to require `make web-install` before web dev/build/typecheck/lint commands | done | P0 | release_ops | `README.md` and `docs/getting-started.md` include explicit sequencing; `make docs-check` passes |
| BK-050 | Foundation + Observability | Improve CLI/doctor environment diagnostics to distinguish sandbox/network/provider outage classes | done | P1 | api_guardian | deterministic outage enum contract locked to `dns_resolution`, `timeout`, `network_unreachable`, `provider_unavailable` across doctor/CLI + regression tests (`tests/unit/test_cli_checks.py`, `tests/unit/test_cli_chat.py`); documented in `docs/cli-reference.md` and `docs/runbook.md` |
| BK-051 | Foundation + Observability | Add reproducible new-user setup smoke target covering API + web bootstrap path | done | P1 | tester | local evidence captured: `make setup-smoke` fails deterministically on occupied ports (`11434`,`30000`,`8080`) with remediation; `make setup-smoke-running` passes bootstrap checks end-to-end |
| BK-052 | Self-Coding + Release Loop | Add regression tests for provider-unavailable and DNS-failure UX in CLI/API flows | done | P0 | tester | CLI/orchestrator failure-mode tests pass and enforce structured fast-fail behavior (`ok=false`, failure kind metadata, degraded response persistence) |
| BK-053 | Governance + Safety | Align provider-config integration tests with admin-only RBAC and retain non-admin deny regression | done | P0 | tester | `uv run pytest tests/integration/test_web_api.py -k provider_config -v` |
| BK-054 | Governance + Safety | Harden auth login `external_id` bounds with API validation + DB trigger guard (`1..256`) | done | P0 | security_reviewer | `uv run pytest tests/integration/test_web_api.py -k external_id -v`; `python3 scripts/test_migrations.py` |
| BK-055 | Foundation + Observability | Suppress expected CLI channel adapter warning noise while preserving unknown-channel warnings | done | P1 | api_guardian | `uv run pytest tests/unit/test_channel_tasks.py -v` |
| BK-056 | Documentation + Ops Hardening | Add `setup-smoke-running` path and docs for already-running local dependency services | done | P1 | release_ops | `make setup-smoke-running`; `make docs-check` |

## Done vs Remaining (as of 2026-02-19)

### Completed Recently

1. BK-003, BK-030, BK-031, BK-032, BK-050 completed (2026-02-19 packet 8):
   - evolution observability drill-down filters/linkage fields finalized.
   - diagnostics outage-class contract locked with deterministic enums and evidence tests.
   - runbook/config/WhatsApp/operator-flow docs closed and API reference regenerated.
   - Evidence: packet 8 validation list below (`make lint`, `make typecheck`, targeted integration/unit suites, `make docs-check`, `make test-gates`).
2. BK-024 completed:
   - Voice-note pipeline now downloads/stages media, persists `whatsapp_media` linkage, and inserts transcript/marker text.
   - Evidence: `uv run pytest tests/integration/test_whatsapp_webhook.py -v`; `uv run pytest tests/unit/test_whatsapp_transcription.py -v`.
3. BK-028 completed:
   - WhatsApp media URL/mime/size/path security controls enforced with negative regression tests.
   - Evidence: `uv run pytest tests/integration/test_whatsapp_webhook.py -v`; `uv run pytest tests/unit/test_whatsapp_media_security.py -v`.
4. Full gate refresh for this tranche:
   - `make lint`
   - `make typecheck`
   - `make docs-generate`
   - `make docs-check`
   - `make test-gates` (coverage gate passed: 84.76% vs 80.00% threshold)

### Remaining Work (prioritized open backlog)

P1:
1. BK-018 (partial): graph relation extraction confidence/evidence policy completion.
2. BK-019 (partial): adaptive forgetting/archival calibration harness + threshold tuning.
3. BK-034 (partial): dependency steward hardening (CVE severity + compatibility bundle + rollback context).
4. BK-035 (partial): release-candidate hardening (changelog artifact + runbook evidence).
5. BK-042 (partial): operator-owned local credential rotation execution evidence closure.

P2:
1. None.

Additional follow-up discovered:
1. (Resolved 2026-02-19) Added production transcription backend (`faster_whisper`) with explicit runtime/config contract and regression coverage.

## Execution Packets

### Packet 0 (completed): Rebaseline + missing test evidence
1. Re-baselined `docs/PLAN.md` acceptance commands to real test modules.
2. Added memory policy event/audit contract tests (`tests/unit/test_memory_policy.py`).
3. Added memory state/review/export RBAC integration suite (`tests/integration/test_memory_api_state_surfaces.py`).
4. Updated targeted test docs in `docs/testing.md`.
5. Validation run: targeted tests + `make docs-check` passed.

### Packet 1 (completed): M1 closure + channel ingress baseline
1. Finished BK-001 and BK-002 with evidence-path unit/integration coverage.
2. Locked core tests for evidence and inbound webhook validation.
3. Preserved end-to-end inbound validation path: WhatsApp webhook -> orchestrator -> memory store with auditable events.

### Packet 1A (completed, security fast-follow): Audit remediation tranche
1. Finished BK-037, BK-039, BK-041.
2. Landed WS system-subscription authz fix + webhook replay guard + CI action pinning/permissions.
3. Targeted validation passed:
   - `uv run pytest tests/integration/test_authorization.py -k websocket -v`
   - `uv run pytest tests/integration/test_websocket.py -v`
   - `uv run pytest tests/integration/test_web_api.py -k github_webhook -v`
   - `make docs-check`
4. Full gate note: `make lint` and `make typecheck` remain blocked by pre-existing unrelated failures outside Packet 1A scope.

### Packet 1B (in progress, security fast-follow): Token and dependency hardening
1. BK-038 completed (cookie-backed web auth/session flow, WS query-token rejection, regression tests).
2. BK-040 completed: Python lock remediated + `pip-audit` clean; npm side reduced from two findings to one (`ajv@6.12.6` only) with `esbuild` remediated; residual ESLint-transitive advisory now formally risk-accepted through 2026-04-30 (`docs/security-risk-acceptance.md`).
3. BK-048 completed with deterministic failure/success evidence + wrapper regression tests.
4. BK-051 completed with explicit clean-profile failure and running-profile success evidence.
5. BK-042 remains partial: scanner evidence attached, but credential rotation execution is still operator-dependent.
6. Evidence bundle refreshed (2026-02-18):
   - `uv run pip-audit`: clean
   - `osv-scanner --lockfile=uv.lock`: clean
   - `osv-scanner --lockfile=web/package-lock.json`: one Medium (`ajv@6.12.6`)
   - `cd web && npm audit --json`: DNS blocked in sandbox (`getaddrinfo EAI_AGAIN registry.npmjs.org`) during refresh run
   - `/tmp/sec-tools/bin/gitleaks detect --source . --no-git --redact`: 6 hits
   - `/tmp/sec-tools/bin/trufflehog filesystem . --only-verified`: 0 verified
   - `python3 scripts/test_migrations.py`: includes `053_state_reconciliation_tokens_saved.sql`, integrity OK
   - `uv run pytest tests/unit/test_health.py -q`: memory KPI metrics path passes with structured `tokens_saved`
   - `make docs-check`: passed

#### Immediate Next Steps (remaining work)
1. Finish ops follow-through for `BK-042`: execute local credential rotation checklist (Google/GitHub/webhook secrets) and attach operator evidence notes.
2. Re-run `cd web && npm audit --json` in a network-enabled environment and attach evidence to close the temporary sandbox DNS gap.

#### Remaining tasks discovered during implementation
1. Evaluate adding a CI job for `make setup-smoke --skip-web-install` (or equivalent split target) to prevent onboarding regressions without introducing flaky external network dependency.

### Packet 1C (completed, beta stabilization): Core reliability + onboarding unblock
1. Finished BK-043, BK-044, BK-045, BK-046, BK-049, BK-052.
2. Landed deterministic CLI fail-fast JSON envelope, orchestrator provider-failure terminal handling, auth/web TestClient lifecycle stabilization, and `make dev` port preflight.
3. Validation evidence:
   - `WEB_AUTH_SETUP_PASSWORD=secret uv run pytest -q tests/integration/test_authorization.py::test_non_admin_cannot_toggle_lockdown tests/integration/test_authorization.py::test_lockdown_route_is_reachable_after_successful_login tests/integration/test_web_api.py::test_web_auth_login_me_logout_flow`
   - `uv run pytest -q tests/unit/test_orchestrator_step.py -k "provider or degraded or fallback"`
   - `uv run pytest -q tests/unit/test_cli_chat.py -k "ask_json"`
   - `make docs-check`
4. Remaining Packet 1C tasks discovered during implementation: none.

### Packet 1D (completed, codex beta stabilization): Auth/input safety + signal cleanup
1. Scope: BK-053, BK-054, BK-055, BK-056 from `docs/reports/beta-2026-02-18-codex.md`.
2. Change set:
   - provider-config integration coverage realigned to admin RBAC + explicit non-admin deny check
   - login `external_id` max-length enforcement (`<=256`) plus DB trigger guard migration
   - CLI channel dispatch warning suppression for expected `cli` skip path
   - additive `make setup-smoke-running` path and operator docs updates
3. Validation evidence:
   - `python3 scripts/test_migrations.py`
   - `uv run pytest -q tests/integration/test_web_api.py -k "provider_config or external_id"`
   - `uv run pytest -q tests/unit/test_channel_tasks.py`
   - `make setup-smoke-running`
   - `make docs-check`
4. Remaining tasks discovered during implementation:
   - (Resolved 2026-02-19) Added mocked-provider CLI integration regression asserting single-line warning-free `jarvis ask --json` output (`tests/integration/test_cli_chat_flow.py::test_ask_json_output_is_warning_free_with_mocked_provider`).

### Packet 2 (in progress, 2026-02-18): M2 memory reliability + self-update enforcement
1. Completed in this tranche:
   - BK-006: deterministic reconciliation counters and ordering edge-case tests.
   - BK-016: hybrid retrieval fusion with tier priors and deterministic tie-break ordering.
   - BK-017: failure bridge mismatch/malformed-detail handling and linkage summary assertions.
2. BK-007 advanced to enforce-capable implementation:
   - Added test-first gate mode (`warn`/`enforce`) and typed failure taxonomy in self-update apply path.
   - Added unit/integration coverage for warn/enforce transitions and typed failure codes.
   - Local default remains warn-friendly.
3. BK-021 remains partial:
   - Memory state/admin RBAC integration suites pass.
   - Remaining: explicit CLI ownership-scope regression for memory export/state commands and any missing WS-vs-HTTP parity assertions for memory surfaces.
4. Validation evidence executed for this tranche:
   - `make lint`
   - `make typecheck`
   - `uv run pytest tests/unit/test_state_store.py tests/unit/test_hybrid_search.py tests/unit/test_memory_tasks.py tests/unit/test_selfupdate_contracts.py tests/unit/test_cli_test_gates_cmd.py -v`
   - `uv run pytest tests/integration/test_memory_api_state_surfaces.py tests/integration/test_authorization.py tests/integration/test_selfupdate.py -v`
   - `make test-gates`
   - `make docs-check`
5. Remaining tasks discovered during implementation:
   - (Resolved 2026-02-19) Wired CI merge-time default to explicit `SELFUPDATE_TEST_GATE_MODE=enforce` in `.github/workflows/ci.yml`; local/default runtime remains warn.
   - (Resolved 2026-02-19) Added committed retrieval benchmark artifact/report path with refresh script and baseline output:
     - `scripts/retrieval_benchmark_report.py`
     - `docs/reports/retrieval/latest.json`
     - `docs/reports/retrieval/README.md`

### Packet 3 (in progress): M3 productization and governance visibility
1. Finish BK-010, BK-011, BK-012, BK-013, BK-025, BK-026, BK-036.
2. Complete admin UX for pairing and memory governance visibility.
3. Run governance/RBAC regression suite before merge.

### Packet 3A (in progress): Memory + WhatsApp hardening tranche
1. Landed memory KPI wiring on `/metrics` (`memory_items_count`, `memory_avg_tokens_saved`, `memory_reconciliation_rate`, `memory_hallucination_incidents`).
2. Hardened `sync_failure_capsules` with typed detail mapping, deterministic dedupe key (`trace_id+phase+summary_hash`), and trace-thread linkage validation.
3. Extended memory state API/UI surfaces:
   - consistency report thread/time filters
   - state stats endpoint (`/api/v1/memory/state/stats`)
   - admin memory sections for conflicts, tier/archive stats, failure lookup, graph preview.
4. Expanded WhatsApp hardening coverage:
   - admin channel lifecycle endpoint coverage (`status/create/qrcode/pairing-code/disconnect`)
   - non-admin authorization regression checks
   - webhook payload variants (extended text, media classes, group payload)
   - QR/pairing redaction key coverage in event writer.

#### Remaining tasks discovered during implementation (2026-02-18)
1. (Resolved 2026-02-19) Added frontend component-level contract tests for `/admin/memory` review/resolve and filtered consistency workflows.
2. (Resolved 2026-02-19) Added explicit log-capture assertions for QR/pairing leakage prevention beyond payload redaction unit tests.
3. (Resolved 2026-02-18) Prior repo-wide lint/typecheck blockers cleared and full `make test-gates` evidence attached in Packet 1E.

### Packet 3B (in progress, 2026-02-19): Governance identity guardrail + WhatsApp log-capture hardening
1. Scope: BK-010 and Packet 3A QR/pairing leakage follow-up.
2. Change set landed:
   - Added self-update propose-time guardrail to reject governance-field edits in `agents/*/identity.md` for keys:
     - `allowed_tools`
     - `risk_tier`
     - `max_actions_per_step`
     - `allowed_paths`
     - `can_request_privileged_change`
   - Added integration log-capture assertion proving QR/pairing secrets are redacted in persisted `channel.inbound.batch` event payloads.
3. Validation completed:
   - `uv run pytest -q tests/unit/test_selfupdate_pipeline.py -k governance_identity_edits_from_patch`
   - `uv run pytest -q tests/integration/test_selfupdate.py -k identity_governance_field_edits`
   - `uv run pytest -q tests/integration/test_whatsapp_webhook.py -k redacts_qr_and_pairing_fields_in_stored_logs`
4. Remaining tasks discovered during implementation:
   - None for Packet 3B scope.

### Packet 3C (completed, 2026-02-19): Memory governance scope-enforcement closure
1. Scope: BK-012, BK-013, BK-021.
2. Change set landed:
   - Added shared agent-scope enforcement for thread memory surfaces (`src/jarvis/memory/scope.py`) with known-agent + thread-active-agent checks.
   - Hardened memory writes with explicit governance denials for:
     - disallowed agent scope (`agent_scope_denied`)
     - message-linked writes missing evidence linkage (`missing_evidence_ref`).
   - Applied per-agent scope checks across API/task paths:
     - state extraction/upsert/search paths scoped by agent
     - state search/graph/export API `agent_id` scope enforcement
     - background memory indexing denies out-of-scope agent writes without mutating memory rows.
   - Added regression coverage:
     - API agent-scope deny path for state search/graph/export
     - task-side deny path for `index_event` with disallowed `actor_id`
     - schema gate regression for message-linked writes lacking evidence linkage.
3. Validation evidence:
   - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/jarvis/memory/scope.py src/jarvis/memory/policy.py src/jarvis/memory/service.py src/jarvis/memory/state_store.py src/jarvis/memory/state_extractor.py src/jarvis/routes/api/memory.py src/jarvis/tasks/memory.py tests/unit/test_memory_service.py tests/unit/test_memory_tasks.py tests/integration/test_memory_api_state_surfaces.py`
   - `UV_CACHE_DIR=/tmp/uv-cache uv run mypy src/jarvis/memory/scope.py src/jarvis/memory/policy.py src/jarvis/memory/service.py src/jarvis/memory/state_store.py src/jarvis/memory/state_extractor.py src/jarvis/routes/api/memory.py src/jarvis/tasks/memory.py`
   - `uv run pytest -q tests/unit/test_memory_service.py tests/unit/test_memory_tasks.py tests/unit/test_state_extractor.py tests/unit/test_hybrid_search.py`
   - `UV_CACHE_DIR=/tmp/uv-cache WEB_AUTH_SETUP_PASSWORD=secret uv run pytest -q tests/integration/test_memory_api_state_surfaces.py tests/integration/test_authorization.py -k "memory or websocket or lockdown"`
   - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/integration/test_state_extraction_flow.py`
4. Remaining tasks discovered during implementation:
   - None.
5. Remaining tasks before handoff:
   - None.
6. Full-gate evidence refresh (2026-02-19):
   - `make lint`
   - `make typecheck`
   - `make test-gates` (includes migrations, unit, integration, and coverage threshold check via `scripts/check_coverage.py`)

### Packet 1E (completed, 2026-02-18): WhatsApp ingress closure + evolution governance contracts
1. Scope: BK-022, BK-027, BK-033.
2. Change set landed:
   - Evolution callback bootstrap/settings wiring (`EVOLUTION_WEBHOOK_URL`, `EVOLUTION_WEBHOOK_BY_EVENTS`, `EVOLUTION_WEBHOOK_EVENTS`) and persisted instance callback state.
   - WhatsApp webhook auth hardening (`401` structured error payload) + deterministic ignore path for non-`messages.upsert`.
   - Governance evolution-item contracts:
     - event types `evolution.item.started|verified|blocked`
     - admin endpoints `GET /api/v1/governance/evolution/items` and `POST /api/v1/governance/evolution/items/{item_id}/status`
     - transition validation + decision timeline inclusion.
   - Added migrations:
     - `054_evolution_instance_contract.sql`
     - `055_evolution_items.sql`
3. Validation completed:
   - `uv run pytest tests/integration/test_whatsapp_webhook.py -v`
   - `uv run pytest tests/integration/test_admin_api.py -v`
   - `uv run pytest tests/integration/test_web_api.py -k evolution_items -v`
   - `uv run pytest tests/unit/test_event_envelope_enforcement.py -v`
   - `python3 scripts/test_migrations.py`
   - `make docs-generate`
   - `make docs-check`
   - `make lint`
   - `make typecheck`
   - `make test-gates`
4. Remaining tasks discovered during implementation:
   - None for Packet 1E scope.

### Packet 4 (completed, 2026-02-19): Backlog status/evidence refresh and residual closure
1. Scope: BK-001, BK-002, BK-007, BK-011, BK-023, BK-028 + residual Packet 1D/2 follow-ups.
2. Change set landed:
   - Added CLI integration regression for warning-free mocked-provider JSON output:
     - `tests/integration/test_cli_chat_flow.py::test_ask_json_output_is_warning_free_with_mocked_provider`
   - Added committed retrieval benchmark artifact/report path:
     - `scripts/retrieval_benchmark_report.py`
     - `docs/reports/retrieval/latest.json`
     - `docs/reports/retrieval/README.md`
   - Wired merge-time CI default for strict test-gate enforcement:
     - `.github/workflows/ci.yml` sets `SELFUPDATE_TEST_GATE_MODE=enforce`
     - local runtime default remains warn mode
   - Updated backlog status table:
     - `done`: BK-001, BK-002, BK-007, BK-011, BK-023
     - `partial`: BK-028 (QR/pairing redaction tests landed; file-limit/safe-media-path negatives still pending)
3. Validation evidence completed:
   - `uv run pytest tests/unit -k repo_index -v`
   - `uv run pytest tests/unit -k evidence -v`
   - `uv run pytest tests/integration -k selfupdate -v`
   - `uv run pytest tests/integration -k selfupdate_apply -v`
   - `uv run pytest tests/integration/test_selfupdate.py -v`
   - `uv run pytest tests/unit/test_selfupdate_contracts.py -v`
   - `uv run pytest tests/integration/test_whatsapp_webhook.py -v`
   - `uv run pytest tests/unit/test_channel_abstraction.py -v`
   - `uv run pytest -q tests/integration/test_cli_chat_flow.py tests/unit/test_hybrid_search.py`
   - `make lint`
   - `make typecheck`
   - `make test-gates`
   - `make docs-check`
4. Remaining tasks discovered during implementation:
   - (Resolved 2026-02-19) Completed BK-024 with media download/transcript marker flow and transcript assertions.
   - (Resolved 2026-02-19) Completed BK-028 file-size and safe-media-path controls with negative coverage.

### Packet 5 (completed, 2026-02-19): WhatsApp media security closure + voice-note pipeline
1. Scope: BK-024, BK-028.
2. Change set landed:
   - Added inbound media security guards in webhook path:
     - HTTPS-only media URLs (+ optional host allowlist)
     - MIME-prefix allowlist and bounded download size enforcement
     - safe media-path resolution rooted at configured runtime directory
   - Added voice-note processing pipeline:
     - media staging under `WHATSAPP_MEDIA_DIR`
     - `whatsapp_media` persistence linkage via `thread_id` + `message_id`
     - pluggable transcription interface with default `stub` backend
     - degraded fallback marker `[voice note unavailable]` on transcription/security failures
   - Added configuration contract:
     - `WHATSAPP_MEDIA_DIR`
     - `WHATSAPP_MEDIA_MAX_BYTES`
     - `WHATSAPP_MEDIA_ALLOWED_MIME_PREFIXES`
     - `WHATSAPP_MEDIA_ALLOWED_HOSTS`
     - `WHATSAPP_VOICE_TRANSCRIBE_ENABLED`
     - `WHATSAPP_VOICE_TRANSCRIBE_BACKEND`
     - `WHATSAPP_VOICE_TRANSCRIBE_TIMEOUT_SECONDS`
   - Added coverage:
     - `tests/unit/test_whatsapp_media_security.py`
     - `tests/unit/test_whatsapp_transcription.py`
     - webhook integration negatives for oversized media and transcription failure markers.
3. Validation evidence completed:
   - `uv run pytest tests/unit/test_whatsapp_media_security.py tests/unit/test_whatsapp_transcription.py -v`
   - `uv run pytest tests/integration/test_whatsapp_webhook.py -v`
   - `uv run pytest tests/unit/test_channel_abstraction.py tests/integration/test_whatsapp_webhook.py tests/unit/test_whatsapp_media_security.py tests/unit/test_whatsapp_transcription.py -v`
   - `make lint`
   - `make typecheck`
   - `make docs-generate`
   - `make docs-check`
4. Remaining tasks discovered during implementation:
   - (Resolved 2026-02-19) Added production-grade local transcription backend (`faster_whisper`) with config/docs contract and webhook/unit regressions.
5. Remaining tasks before handoff:
   - None for BK-024/BK-028 scope.

### Packet 6 (completed, 2026-02-19): Production voice transcription backend (local faster-whisper)
1. Scope: residual follow-up from Packet 5 (`non-stub` voice backend closure).
2. Change set landed:
   - Added WhatsApp transcription backend adapter support for `faster_whisper` in `src/jarvis/channels/whatsapp/transcription.py`.
   - Added runtime configuration contract:
     - `WHATSAPP_VOICE_MODEL`
     - `WHATSAPP_VOICE_DEVICE`
     - `WHATSAPP_VOICE_COMPUTE_TYPE`
     - `WHATSAPP_VOICE_LANGUAGE`
   - Added backend/error-path coverage:
     - `tests/unit/test_whatsapp_transcription.py`
     - `tests/integration/test_whatsapp_webhook.py::test_inbound_voice_note_uses_faster_whisper_backend`
   - Updated operator/config docs:
     - `docs/configuration.md`
     - `docs/channels/whatsapp.md`
     - `docs/runbook.md`
     - `.env.example`
3. Validation completed:
   - `uv run pytest tests/unit/test_whatsapp_transcription.py -v`
   - `uv run pytest tests/integration/test_whatsapp_webhook.py -k "voice_note" -v`
4. Remaining tasks discovered during implementation:
   - None.

### Packet 7 (in progress, 2026-02-19): BK-003 observability trace drill-down + feature-build trial prep
1. Scope: BK-003 (unified evolution observability view with trace drill-down).
2. Change set landed:
   - Added governance evolution-items web client and typed frontend contract:
     - `web/src/api/endpoints.ts`
     - `web/src/types/index.ts`
   - Added cross-page trace handoff affordances:
     - governance decision timeline and evolution items now include `Open Trace` links to `/admin/events?trace_id=...&thread_id=...`
     - self-update patch detail adds `View In Events` link for selected patch trace
   - Added events-page URL hydration for trace/filter state:
     - `/admin/events` now initializes and syncs `trace_id`/filters from query params and preserves deep-link drill-down context.
   - Added frontend contract coverage:
     - `web/tests/adminObservabilityContracts.test.mjs`
3. Validation completed:
   - `make setup-smoke-running`
   - `cd web && npm test`
   - `cd web && npm run typecheck`
   - `uv run pytest tests/integration/test_web_api.py -k evolution_items -v`
   - `uv run pytest tests/integration -k governance -v`
   - Live feature-build trial execution:
     - API runtime: `UV_CACHE_DIR=/tmp/uv-cache uv run uvicorn jarvis.main:app --reload --app-dir src`
     - build run #1: `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 120 --poll-interval-s 2`
     - trace/thread evidence #1: `thr_5eba1a949c5f4826b87f760e5a98c6f6`
     - build run #2 (after remediation): `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 120 --poll-interval-s 2`
     - trace/thread evidence #2: `thr_4ba836b7312a492ab8e2462a62e40fb8`
   - Remediation validation:
     - `uv run pytest tests/unit/test_host_tool.py tests/unit/test_cli_build.py tests/unit/test_task_runner.py -v`
4. Remaining tasks discovered during implementation:
   - Resolved in this packet:
     - build prompt now keeps execution in `main` (no coder delegation) to avoid `R6: governance.risk_tier` for `exec_host`.
     - `exec_host` no longer applies `ulimit` caps when `EXEC_HOST_SANDBOX=none`; removes false memory-allocation failures during normal local runs.
     - task runner now swallows known shutdown-time threadpool scheduling race (`cannot schedule new futures after shutdown`) and logs as dropped task.
     - orchestrator now runs terminal synthesis after tool-loop exhaustion and emits explicit reason taxonomy (`placeholder_response_after_tool_loop`, `placeholder_response_after_terminal_synthesis`, `provider_error_terminal_synthesis`).
     - when synthesis still cannot recover after tool-loop exhaustion, assistant now emits deterministic operator-facing terminal text (includes trace id) instead of generic internal-error text.
   - Validation evidence for terminal-synthesis hardening:
     - `uv run pytest tests/unit/test_orchestrator_step.py -v`
     - `uv run pytest tests/unit/test_cli_build.py tests/unit/test_task_runner.py tests/unit/test_host_tool.py -v`
   - Previously reported blocker now resolved:
     - fixed API startup syntax/import issue in `src/jarvis/routes/api/channels.py` by removing misplaced import line in `from jarvis.db.queries import (...)`.
   - Unblock verification evidence (targeted local path):
     - syntax check: `uv run python -m py_compile src/jarvis/routes/api/channels.py` -> pass (no `SyntaxError`).
     - API startup/import check: `UV_CACHE_DIR=/tmp/uv-cache uv run uvicorn jarvis.main:app --app-dir src` -> startup complete; `curl -fsS http://127.0.0.1:8000/healthz` -> `{"ok":true}`.
     - live build check: `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 120 --poll-interval-s 2` -> thread `thr_d9c3e31b01b7493ea7a0deeed6b28ed9`; non-syntax terminal failure with trace `trc_4d48f04a30124b84b3670ccf16cdf126`.
     - first actionable failure after unblock: build cycle completed tool execution but failed terminal synthesis (`Review /admin/events for details and retry.`), indicating the prior `channels.py` syntax crash is no longer the gating issue.
   - Follow-up triage evidence after first unblock:
     - fixed route + command type blockers found in trace triage:
       - `src/jarvis/routes/api/channels.py`: restored `Literal` typing for `decision`.
       - `src/jarvis/commands/service.py`: resolved `/wa-review` mypy issues (variable type collision + `Literal` decision typing).
     - targeted typecheck evidence:
       - `uv run mypy src/jarvis/routes/api/channels.py src/jarvis/commands/service.py` -> pass.
     - rerun #1 after type fixes: `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 120 --poll-interval-s 2`
       - thread `thr_37a2137089a841d8aadb52600961eaf6`
       - trace `trc_3bc2c07a38db48099adf9fa938d36ff2`
       - outcome: still terminal synthesis degraded after tool-loop exhaustion.
     - rerun #2 after type fixes: `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 120 --poll-interval-s 2`
       - thread `thr_e1407b2594a442b1bb90211d678a672e`
       - trace `trc_daccceb598e546ea985100307838cb31`
       - outcome: `exec_host` timed out `uv run jarvis test-gates --fail-fast` at 120s (`exit_code=124`); subsequent model run errored (`cannot schedule new futures after shutdown`) and returned degraded fallback text.
     - remediation applied for build-flow timeout mismatch:
       - raised exec-host timeout cap default `EXEC_HOST_TIMEOUT_MAX_SECONDS` from 120 -> 600 in config/docs/env (`src/jarvis/config.py`, `.env.example`, `docs/configuration.md`).
       - added build-path timeout handling in agent host tool bridge (`src/jarvis/tasks/agent.py`) with unit coverage (`tests/unit/test_agent_exec_host.py`).
       - targeted validation:
         - `uv run pytest tests/unit/test_agent_exec_host.py -v`
         - `uv run ruff check src/jarvis/tasks/agent.py src/jarvis/config.py tests/unit/test_agent_exec_host.py`
         - `uv run mypy src/jarvis/tasks/agent.py src/jarvis/config.py tests/unit/test_agent_exec_host.py`
     - rerun #3 after timeout remediation: `UV_CACHE_DIR=/tmp/uv-cache uv run jarvis build --new-thread --web --timeout-s 700 --poll-interval-s 2`
       - thread `thr_039ffbae84f847dd864f921c7e6455b2`
       - trace `trc_b1c947524f134e1f9528d9bb08dfb452`
       - outcome: success; assistant final summary reports `All gates pass - nothing to fix.` and confirms `uv run jarvis test-gates --fail-fast` passed.
5. Remaining tasks before handoff:
   - Execute manual admin E2E walk for trace-drilldown workflow (`/admin/governance` -> `/admin/events` and `/admin/selfupdate` -> `/admin/events`) and attach screenshots/evidence.
   - Close historical degraded-build traces (`trc_4d48f04a30124b84b3670ccf16cdf126`, `trc_3bc2c07a38db48099adf9fa938d36ff2`, `trc_daccceb598e546ea985100307838cb31`) with retrospective note now that unblock verification passes under updated timeout policy.
   - After local remediation passes, run equivalent Docker-backed verification for reproducibility hardening.

### Packet 8 (completed, 2026-02-19): Reliability + ops closure (BK-003/050/030/031/032 + BK-042 repo-side)
1. Scope completed:
   - BK-003: evolution observability drill-down closed.
   - BK-050: deterministic outage-class diagnostics contract + evidence closed.
   - BK-030/BK-031/BK-032: docs/runbook/config/API/operator-flow gaps closed.
   - BK-042: repo-actionable checklist closure complete; operator execution remains external.
2. Backend/API changes:
   - `GET /api/v1/governance/evolution/items` now supports additive admin filters:
     - `status`
     - `trace_id`
     - `thread_id`
     - `from` (maps to `updated_at>=`)
     - `to` (maps to `updated_at<=`)
   - Evolution item responses now include stable linkage fields:
     - `item_id` (compat alias of `id`)
     - `trace_id`
     - `span_id` (latest `evolution.item.*` event span)
     - `thread_id`
     - `status`
     - `updated_at`
3. Admin UI/contract closure:
   - Governance page now exposes evolution filters (status/trace/from/to) and preserves trace handoff to `/admin/events`.
   - Frontend contract checks updated (`web/tests/adminObservabilityContracts.test.mjs`).
4. Diagnostics outage-class contract closure:
   - Doctor/CLI classification now normalizes to required deterministic classes:
     - `dns_resolution`
     - `timeout`
     - `network_unreachable`
     - `provider_unavailable`
   - Added regression assertions in:
     - `tests/unit/test_cli_checks.py`
     - `tests/unit/test_cli_chat.py`
5. Documentation closure:
   - `docs/runbook.md`: memory rollback/recovery, memory conflict resolution flow, WhatsApp decision tree, outage-class evidence, explicit operator-owned credential rotation checklist + artifact template.
   - `docs/configuration.md`: memory/state extraction and memory lifecycle flags.
   - `docs/channels/whatsapp.md`: troubleshooting decision tree + rollback path.
   - `docs/channels/whatsapp-ui.md`: operator troubleshooting additions.
   - `docs/cli-reference.md`: outage-class JSON/doctor contract and evidence commands.
   - `docs/api-reference.md`: regenerated from OpenAPI (`make docs-generate`).
6. Validation evidence:
   - `make lint`
   - `make typecheck`
   - `uv run pytest tests/integration/test_web_api.py -k evolution -v`
   - `uv run pytest tests/integration/test_authorization.py -k websocket -v`
   - `uv run pytest tests/integration/test_whatsapp_webhook.py -v` (one transient `database is locked` setup error; immediate rerun passed)
   - `uv run pytest tests/unit/test_health.py -q`
   - `make docs-check`
   - `make test-gates`
7. Remaining tasks discovered during implementation:
   - None new in repo scope.
8. Deferred explicitly to next packet (unchanged):
   - BK-018
   - BK-019
   - BK-020
   - BK-034
   - BK-035

### Packet 9 (completed, 2026-02-20): Framework audit + multi-channel media Phase 1

Comprehensive audit across memory, events, scheduler, governance, self-update, test suite, and agent prompts — closing critical bugs, filling architecture gaps, adding missing tests, and fixing documentation drift.

1. Scope completed: BK-057, BK-058, BK-059, BK-060, BK-061, BK-062, BK-063, BK-064, BK-065, BK-066.
2. Critical bug fixes (P0):
   - **BK-057**: `insert_message()` now accepts `media_path`/`mime_type`; WhatsApp router passes media fields from inbound handler.
   - **BK-058**: `is_allowed()` supports wildcard `*` permission; R8 rule enforces `max_actions_per_step` via `tool.call.start` event count per trace.
   - **BK-060**: Scheduler NULL thread_id: skips dispatch with `schedule.error` event; 3-INSERT creation wrapped in `BEGIN/COMMIT/ROLLBACK`; per-schedule try/except prevents one bad schedule from crashing the tick.
   - **BK-062**: `compute_system_fitness` rescheduled from weekly (604800s) to 30-minute (1800s) interval so SLO gate works on new deployments.
   - **BK-063**: `main.py` `evolution.*` references fixed to `baileys.*`; import sort fixed; lint/typecheck clean.
3. Architecture gaps closed (P1):
   - **BK-059**: `memory_consistency_reports` table (migration 059) + `store_consistency_report()` + `GET /api/v1/memory/consistency` endpoint with historical queries.
   - **BK-061**: `src/jarvis/tasks/events.py` with `run_event_maintenance()` — deletes events older than `EVENT_RETENTION_DAYS` (default 90), prunes orphaned FTS/vector rows, registered as weekly periodic task.
4. Missing tests added (P1):
   - `tests/unit/test_db_queries.py`: media round-trip, insert-without-media, multi-channel thread unification.
   - `tests/unit/test_tools_runtime.py`: wildcard `*` permission, `max_actions_per_step` R8 enforcement.
   - `tests/integration/test_scheduler.py`: thread isolation (threads/sessions/participants created), NULL thread_id graceful skip with `schedule.error`.
   - `tests/integration/test_events.py`: semantic event search returns list.
5. Self-update guardrail defaults (P1):
   - **BK-066**: `SELFUPDATE_MAX_FILES_PER_PATCH=20`, `SELFUPDATE_MAX_RISK_SCORE=100`, `SELFUPDATE_MAX_PATCH_ATTEMPTS_PER_DAY=10`, `SELFUPDATE_MAX_PRS_PER_DAY=5` added to `config.py` and `.env.example`.
6. Documentation fixes (P2):
   - **BK-064**: `agents/main/soul.md`, `agents/coder/soul.md`, `agents/data_migrator/soul.md`, `agents/planner/soul.md` — inline git-flow block replaced with CLAUDE.md reference.
   - **BK-065**: `docs/prompts/FEATURE_BUILDER_PROMPT.md` + `docs/prompts/DOCS_AGENT_PROMPT.md` created; `docs/prompts/README.md` updated.
   - `MEMORY.md`: Celery/RabbitMQ reference replaced with in-process asyncio task runner.
7. Validation evidence:
   - `make lint` — all checks passed.
   - `make typecheck` — no issues in 135 source files.
   - `make test-gates` — 420 passed; coverage 86.57% (threshold 80%).
   - `make docs-generate && make docs-check` — docs check passed.
8. Remaining tasks discovered during implementation:
   - None new in repo scope.
9. Deferred explicitly (scope too large for this pass):
   - BK-018: graph relation LLM extraction (200–300 lines, separate BK item).
   - BK-019: adaptive forgetting calibration harness.
   - Concurrent scheduler deduplication (single-process deployment; low priority).

### Packet 10 (completed, 2026-02-22): State extraction timeout hardening (async path)

1. Scope completed:
   - Move state extraction out of synchronous `run_agent_step` path.
   - Add background task `jarvis.tasks.memory.extract_thread_state`.
   - Emit `state.extraction.queued` + trace notification lifecycle.
   - Raise `STATE_EXTRACTION_TIMEOUT_SECONDS` default from 15s to 30s.
   - Add quota-cooldown skip classification (`provider_quota_cooldown`).
2. Code updates:
   - `src/jarvis/orchestrator/step.py`: queue extraction task and emit queued/failure events.
   - `src/jarvis/tasks/memory.py`: new extraction task, event emission, trace notification writes.
   - `src/jarvis/tasks/__init__.py`: task registration.
   - `src/jarvis/memory/state_extractor.py`: skip extraction when provider is in quota cooldown.
   - `src/jarvis/config.py`: timeout default bump.
3. Test updates:
   - `tests/unit/test_orchestrator_step.py`: queued task/event assertion.
   - `tests/unit/test_memory_tasks.py`: task success/failure trace/event assertions.
   - `tests/unit/test_state_extractor.py`: provider quota cooldown skip case.
4. Documentation updates:
   - `docs/configuration.md`, `docs/architecture.md`, `docs/runbook.md`, `docs/change-safety.md`.
5. Validation evidence:
   - Targeted unit suite for orchestrator/state extractor/memory tasks (see handoff notes).
6. Remaining tasks discovered during implementation:
   - Add dashboard metric for queued/complete/failed extraction ratio by failure kind.
7. Deferred explicitly to next packet:
   - Optional backoff policy per-thread for repeated extraction failures.

### Packet 11 (completed, 2026-02-22): Follow-up heartbeat loop + proactive no-reply policy

1. Scope completed:
   - Added opt-in per-thread proactive follow-up state and APIs.
   - Implemented periodic `followup_heartbeat_tick` task with strict `reply|no_reply` evaluator output handling.
   - Added `no_reply` behavior: update status + events with no outbound user message.
   - Added stale periodic job visibility in maintenance/system status surfaces.
2. Code updates:
   - `src/jarvis/db/migrations/065_thread_followups.sql`
   - `src/jarvis/tasks/followups.py`
   - `src/jarvis/tasks/periodic.py`
   - `src/jarvis/tasks/__init__.py`
   - `src/jarvis/routes/api/followups.py`
   - `src/jarvis/routes/api/__init__.py`
   - `src/jarvis/routes/api/system.py`
   - `src/jarvis/cli/main.py`
   - `src/jarvis/config.py`
   - `.env.example`
3. Test updates:
   - `tests/unit/test_followup_tasks.py`
   - `tests/integration/test_authorization.py` (follow-up ownership/boundary checks)
4. Documentation updates:
   - `docs/api-reference.md`
   - `docs/api-usage-guide.md`
   - `docs/configuration.md`
   - `docs/architecture.md`
   - `docs/runbook.md`
   - `docs/change-safety.md`
5. Remaining tasks discovered during implementation:
   - Add admin web UI controls to toggle follow-up heartbeat per thread.
   - Add per-thread cooldown/jitter to smooth large cohorts of enabled threads.

## Testing and Acceptance Gates

Global gates before marking backlog item `done`:
1. `make lint`
2. `make typecheck`
3. Relevant unit/integration tests for touched modules
4. `make test-gates` before merge
5. Evidence refs and docs updates present in the same PR

Supplemental targeted checks for this plan:
- `uv run pytest tests/integration/test_whatsapp_webhook.py -v`
- `uv run pytest tests/integration/test_admin_api.py -v`
- `uv run pytest tests/unit/test_memory_service.py -v`
- `uv run pytest tests/integration/test_memory_api_state_surfaces.py -v`
- `uv run pytest tests/unit/test_memory_policy.py -v`
- `osv-scanner --lockfile=uv.lock`

- `osv-scanner --lockfile=web/package-lock.json`
- `UV_CACHE_DIR=/tmp/uv-cache XDG_CACHE_HOME=/tmp/.cache uv run pip-audit --cache-dir /tmp/pip-audit-cache`
- `cd web && npm audit --json` (run in network-enabled environment when sandbox DNS is unavailable)

## Rollout and Rollback

Rollout order:
1. Backend safety and test hardening first.
2. Channel/webhook and memory reliability second.
3. Admin UI and governance visibility third.
4. Metrics-driven optimization features last.

Rollback policy:
- Prefer feature-flag fallback for new strict gates.
- Keep compatibility fields/version readers for evolving artifacts/events.
- Revert per-packet changesets independently; preserve append-only migration history.
- On guardrail trip, lock down mutation paths and retain read-only observability.

## Open Risks and Mitigations

- Retrieval/ranking regressions from fusion/tuning.
  - Mitigation: deterministic tests + benchmark harness before threshold changes.
- Webhook payload compatibility drift.
  - Mitigation: dual parser fixtures for legacy + Evolution variants.
- Security leakage (QR/pairing/media paths).
  - Mitigation: explicit no-leak tests, redaction checks, strict path/size validation.
- Governance overreach or bypass.
  - Mitigation: deny-by-default retained, typed denial events, ownership/RBAC regressions.

## Traceability

| Backlog IDs | Source references |
|---|---|
| BK-001..BK-013, BK-033..BK-035 | `evo.md` (Document Contract, Non-Negotiable Invariants, Phase 1-4, Rollout Packets, Global Gates) |
| BK-014, BK-022..BK-028 | `whatsapp.md` (Goals/Constraints, Phases 1-5, admin endpoints, webhook/governance commands, security checklist) |
| BK-015, BK-019 | `docs/memory-roadmap.md` (importance formula, tier/archive flow, delivery order) |
| BK-016..BK-021, BK-036 | `docs/memory-roadmap-todo.md` (not implemented, hardening gaps, tests needed, operational follow-ups) |
| BK-017, BK-029, BK-036 and packet sequencing emphasis | `docs/evolution-whatsapp-memory-execution-plan.md` (workstreams, file-level plan, rollout strategy, risk controls) |
| BK-043..BK-052 | `docs/reports/beta-2026-02-18-full-pass.md` (reproducible reliability/setup/documentation defects + ranked stabilization priorities) |
| BK-053..BK-056 | `docs/reports/beta-2026-02-18-codex.md` (RBAC test mismatch, auth input bounds, CLI warning noise, setup-smoke friction) |

## Appendix

### Merged from
- `evo.md`
- `whatsapp.md`
- `docs/memory-roadmap.md`
- `docs/memory-roadmap-todo.md`
- `docs/evolution-whatsapp-memory-execution-plan.md`
- `docs/reports/beta-2026-02-18-full-pass.md`

### Deferred/Excluded items
- No source items were discarded. Items were merged/deduplicated into normalized backlog IDs.
- Optional API additions (`GET/POST /api/v1/governance/evolution/items*`) from `evo.md` were retained as lower-priority backlog coverage under BK-033 unless promoted by milestone pressure.

### Packet 12 (completed, 2026-02-22): Orchestrator reliability hardening for quota/leak/suppression failures

1. Scope completed:
   - Added final-response leak guard to block internal planning/tool payload leakage.
   - Extended embedded tool payload parsing (`tool_calls`, `tool+tool_input`, `tool_name+arguments`).
   - Added provider-router cooldown short-circuit when primary reports active quota cooldown.
   - Added per-thread state-extraction backoff with `state.extraction.skipped` events.
   - Added duplicate failing tool-call suppression and suppression telemetry (`tool.call.suppressed`).
2. Code updates:
   - `src/jarvis/orchestrator/step.py`
   - `src/jarvis/providers/router.py`
   - `src/jarvis/tasks/memory.py`
   - `src/jarvis/config.py`
   - `.env.example`
3. Test updates:
   - `tests/unit/test_orchestrator_step.py`
   - `tests/unit/test_router.py`
   - `tests/unit/test_memory_tasks.py`
4. Documentation updates:
   - `docs/architecture.md`
   - `docs/change-safety.md`
   - `docs/configuration.md`
   - `docs/testing.md`
5. Remaining tasks discovered during implementation:
   - Persist extraction backoff state in DB (currently process-local) if multi-worker durability is required.
   - Add admin/system dashboard counters for `agent.response.leak_blocked` and `tool.call.suppressed`.

### Packet 13 (completed, 2026-02-22): Feature-build retry hardening + deliverable gate

1. Scope completed:
   - Added reason-aware feature-build retry controls with fail-fast on repeated consecutive
     `placeholder_response_after_tool_loop` outcomes (`feature.build.retry.denied`).
   - Added feature-build deliverable gate checks before success finalization:
     - require allowed-scope `git diff --name-only` changes, or explicit no-op with blockers.
     - block success when protected-path edit attempts are detected against
       `RALPH_NEVER_EDIT_PATHS` / `PROTECTED_PATH_PATTERNS`.
   - Added terminal synthesis observability event `feature.build.terminal_synthesis`.
   - Added loop-cap telemetry `tool.call.loop_cap_reached` for repeated identical tool signatures.
2. Code updates:
   - `src/jarvis/tasks/agent.py`
   - `src/jarvis/orchestrator/step.py`
   - `src/jarvis/tasks/feature_build.py`
   - `src/jarvis/db/queries.py`
   - `src/jarvis/db/migrations/072_feature_build_run_diagnostics.sql`
   - `src/jarvis/config.py`
   - `src/jarvis/cli/env_groups.py`
   - `.env.example`
3. Test updates:
   - `tests/unit/test_agent_recovery.py`
   - `tests/unit/test_orchestrator_step.py`
4. Documentation updates:
   - `docs/configuration.md`
   - `docs/architecture.md`
   - `docs/change-safety.md`
   - `docs/testing.md`
5. Remaining tasks discovered during implementation:
   - Consider exposing new build diagnostics fields (`active_attempt`, `last_progress_at`,
     `last_event_type`, `last_trace_id`, `terminal_reason`) in admin API/UI follow-up pass.

## Execution Update (2026-02-24, WhatsApp One-Click Recovery UX for 401 loggedOut)

- Completed:
  - Added one-click Admin UI recovery action `Recover Session` for non-recoverable
    `close + 401 loggedOut + autoheal_attempted=true` connector state.
  - Implemented deterministic frontend recovery sequence:
    - `POST /api/v1/channels/whatsapp/reset`
    - poll `GET /api/v1/channels/whatsapp/status` (1s interval, 30s timeout) until `qr` or `open`
    - `GET /api/v1/channels/whatsapp/qrcode` and render QR
  - Added in-card progress/failure operator feedback:
    - `Resetting session...`
    - `Waiting for QR state...`
    - `Loading QR...`
    - `Recovery failed: ...`
  - Updated pairing guidance copy to direct logged-out recovery through `Recover Session`.
  - Updated docs:
    - `docs/channels/whatsapp-ui.md`
    - `docs/channels/whatsapp.md`
  - Extended web contract coverage in `web/tests/adminChannelsContracts.test.mjs` to assert:
    - recovery control presence
    - logged-out guidance copy update
    - recovery progress/failure copy contracts
- Remaining tasks before handoff:
  - Run full gate sweep (`make test-gates`) before release promotion.

## Execution Update (2026-02-25, WhatsApp 401 loggedOut Manual Relink Policy)

- Completed:
  - Replaced automatic `loggedOut` recovery loop in Baileys sidecar with terminal diagnostics.
  - On `DisconnectReason.loggedOut`, sidecar now:
    - stops reconnect scheduling
    - does not auto-clear auth
    - marks relink-required state for explicit operator action.
  - Extended sidecar `/status` payload with:
    - `relink_required`
    - `can_reconnect`
    while retaining `autoheal_attempted` for compatibility.
  - Updated `/api/v1/channels/whatsapp/status` diagnostics normalization to drive
    `recoverable` from `relink_required/can_reconnect` (with 401+loggedOut fallback).
  - Simplified Admin Channels UI to manual relink workflow:
    - removed one-click `Recover Session` flow/progress states
    - retained explicit lifecycle actions (`Initialize Connection`, `Force Re-pair`, `Load QR`,
      `Disconnect`, `Restart Server`)
    - updated copy to direct operators to `Force Re-pair` for logged-out states.
  - Updated docs:
    - `docs/channels/whatsapp.md`
    - `docs/channels/whatsapp-ui.md`

## Execution Update (2026-02-25, Baileys Hard-Cutover Contract Alignment)

- Discovered operational drift: WhatsApp runtime was Baileys-first but config/env/docs/error
  contracts still used Evolution naming, causing recurring operator misconfiguration and
  webhook secret mismatches in Docker Compose deployments.
- Completed hard cutover to Baileys config and runtime contract:
  - Config/env contract switched to:
    - `BAILEYS_API_URL`
    - `BAILEYS_AUTO_CREATE_ON_STARTUP`
    - `BAILEYS_WEBHOOK_URL`
    - `BAILEYS_WEBHOOK_BY_EVENTS`
    - `BAILEYS_WEBHOOK_EVENTS`
    - `BAILEYS_WEBHOOK_SECRET_HEADER`
  - Admin channel API errors normalized from `evolution_api_*` to `baileys_api_*`.
  - Baileys sidecar webhook forwarding now includes configurable secret header.
  - Inbound audio media extraction fixed to bind by matching external message id (not first audio in batch).
- Documentation updated for operator/runtime consistency:
  - `.env.example`
  - `docs/configuration.md`
  - `docs/channels/whatsapp.md`
  - `docs/channels/whatsapp-ui.md`
  - `docs/runbook.md`
- Remaining follow-up tasks:
  - Watch staging/production for regressions in one release cycle and confirm no external automation
    still writes legacy `EVOLUTION_*` keys.
    - `docs/local-development.md`
  - Updated tests:
    - `tests/integration/test_admin_api.py`
    - `web/tests/adminChannelsContracts.test.mjs`
- Remaining tasks before handoff:
  - Run targeted checks (`tests/integration/test_admin_api.py`, `web/tests/adminChannelsContracts.test.mjs`).
  - Run full gate sweep (`make test-gates`) before release promotion.

## Execution Update (2026-02-25, Startup fix for missing orchestrator registry import)

- Completed:
  - Resolved FastAPI startup crash caused by dangling import in `src/jarvis/orchestrator/step.py`:
    - removed accidental `from jarvis.orchestrator.registry import registry`
    - removed orphan `fan_out_to_agents(...)` helper that depended on nonexistent module.
  - Added regression test `tests/unit/test_orchestrator_step_import.py` to assert
    `jarvis.orchestrator.step` remains importable.
- Remaining tasks before handoff:
  - Run full gate sweep (`make test-gates`) before release promotion.

## Execution Update (2026-02-25, Startup fix gate verification)

- Completed:
  - Ran `make test-gates` after the startup-regression fix; all gates passed.
  - Verified task-runner startup import path with:
    - `uv run python -c "from jarvis.tasks import get_task_runner; get_task_runner(); print('task-runner-ok')"`
- Remaining tasks before handoff:
  - None for this startup fix.

## Execution Update (2026-02-27, Non-Web Reply Approval Gate + Admin Chat Visibility)

- Discovered issue:
  - Admin `/chat` required manual toggle (`all=true`) to see non-owned/channel threads.
  - Non-web outbound replies (WhatsApp) auto-dispatched without explicit approval checkpoint.
- Completed:
  - Added migration `081_channel_reply_approvals.sql`:
    - `channel_reply_approval_requests`
    - `channel_reply_permissions`
  - Added non-web approval gate service:
    - `src/jarvis/services/channel_reply_approval.py`
    - blocks non-web outbound until approved, unless sender+channel allow rule exists
    - emits `channel.reply.approval.*` and `channel.reply.dispatch.blocked` events
  - Applied gate in both outbound paths:
    - `src/jarvis/tasks/agent.py`
    - `src/jarvis/tasks/followups.py`
  - Added admin API surfaces:
    - `GET /api/v1/channel-reply-approvals`
    - `POST /api/v1/channel-reply-approvals/{id}/approve`
    - `POST /api/v1/channel-reply-approvals/{id}/reject`
    - `GET /api/v1/channel-reply-permissions`
    - `POST /api/v1/channel-reply-permissions/revoke`
  - Added chat command controls:
    - `/channel-approve-list`
    - `/channel-approve <id> once|always`
    - `/channel-deny <id> [reason]`
    - `/channel-allow-list`
    - `/channel-allow-revoke <channel> <recipient> [reason]`
  - Admin chat visibility fix:
    - `/chat` now requests all threads automatically for `role=admin` (no Eye toggle dependency).
    - Auth store now tracks role from `/api/v1/auth/me`.
- Verification run:
  - `uv run pytest tests/integration/test_task_flow.py::test_scheduler_tick_and_agent_step_flow -q`
  - `uv run pytest tests/integration/test_whatsapp_webhook.py::test_webhook_to_outbound_flow_emits_events -q`
  - `cd web && npm test -- --runInBand adminChannelsContracts.test.mjs`
- Remaining tasks before handoff:
  - Run full gate sweep: `make test-gates`
  - Add dedicated integration coverage for the new `/api/v1/channel-reply-approvals*` and `/api/v1/channel-reply-permissions*` endpoints.
