# Structured State Memory System — Full Implementation Plan

---

# Overview

This system introduces a **structured semantic memory layer** alongside summaries to drastically reduce prompt context size while improving precision recall, traceability, and reasoning stability.

It separates memory into two independent channels:

| Layer               | Role              | Failure Impact |
| ------------------- | ----------------- | -------------- |
| Narrative summaries | Story + flow      | none           |
| Structured state    | Facts + decisions | none           |

The system is designed so either layer can fail without affecting the other.

---

# Core Design Principle

> Summaries tell the story.
> State stores the facts.

Summaries preserve narrative continuity.
State preserves actionable knowledge.

Both are required for stable long‑running conversations.

---

# Architecture Flow

messages → summary_generator → summaries
messages → state_extractor → structured_state

prompt_builder merges:

* short summary
* structured state
* tail messages

---

# Structured State Specification

## Item Types (fixed enum)

```
decision
constraint
action
question
risk
```

LLM instruction must include:

> DO NOT invent new item types.

---

# Semantic Compression Memory System — Implementation Plan

## Context

The current prompt assembly packs thread summaries (short+long) and retrieved memory chunks into the prompt. This works but wastes tokens on narrative prose and can't reliably track decisions, constraints, or open actions across long conversations. This plan adds a structured state extraction layer that replaces `summary.long` with a compact, typed state representation — reducing prompt size while improving recall precision and preventing hallucinated history.

---

## Architecture Overview

```
messages (new since watermark)
  │
  ├─→ LLM extractor → candidates ─→ deterministic reconciler → state_items table → embed
  │                                   (vector dedupe + supersession + merge rules)
  │
  └─→ existing memory.search() (unchanged)

Prompt: SYSTEM → SKILLS → SUMMARY_SHORT → STRUCTURED_STATE → CONTEXT → TAIL
```

Extraction runs inline pre-step (before prompt building). The pipeline is split into two clean phases: LLM extraction produces candidates, deterministic reconciliation decides insert/merge/supersede/conflict. State items replace `summary.long` in the prompt budget.

---

## New Files

### 1) `src/jarvis/memory/state_items.py` — Pure types + logic (no DB/LLM)

* `StateItemType` enum: `decision`, `constraint`, `action`, `question`, `risk`
* `StateItem` dataclass:

  * `uid`, `text`, `status`, `type_tag`, `topic_tags[]`, `refs[]` (msg IDs), `confidence`, `replaced_by`,
    `supersession_evidence`, `conflict`, `pinned`, `source`, `created_at`, `last_seen_at`
  * `last_seen_at`: set to the newest ref's `created_at` during upsert/merge. Used for freshness ranking in renderer without adding prompt tokens.
* `normalize_text()` — lowercase, trim, collapse whitespace, remove quotes, NFC, strip bullets
* `compute_uid(type_tag, text)` — prefix + `sha256(type + ":" + normalize(text))[:12]`

  * Prefixes: `d_`, `c_`, `a_`, `q_`, `r_`
* `VALID_STATUSES` with deterministic precedence for merges:

  * action: `superseded > done > blocked > open`
  * question: `superseded > answered > open`
  * decision/constraint/risk: `superseded > active`
* `validate_item()` — returns error list; coerces invalid status to type default + sets `confidence=low`
* `SUPERSESSION_TRIGGERS` — `["instead", "replaced", "switched", "changed to", "no longer"]`

  * Dropped `"actually"` and `"correction"` — too common in normal speech, causes false supersessions
* `has_supersession_signal(text)` — checks trigger presence
* `resolve_status_merge(type_tag, status_a, status_b) -> str` — higher-precedence status per the table above

---

### 2) `src/jarvis/memory/state_store.py` — DB persistence

Takes `conn: sqlite3.Connection` (same pattern as `MemoryService`).

* `upsert_item(conn, thread_id, item)` — insert or merge (same UID = union refs/tags, max confidence, `resolve_status_merge`)
* `get_active_items(conn, thread_id, limit=50)` — non-superseded items, ordered for rendering
* `get_items_by_uids(conn, uids)` — fetch specific items
* `mark_superseded(conn, uid, thread_id, replaced_by, evidence)`

**Watermark with stable tie-breaker**

* `get_extraction_watermark(conn, thread_id) -> tuple[str, str] | None` → `(last_message_created_at, last_message_id)`
* `set_extraction_watermark(conn, thread_id, created_at, message_id)`
* Fetch new messages:

  * `WHERE (created_at > ?) OR (created_at = ? AND id > ?)`
  * `ORDER BY created_at, id LIMIT ?`

**Vector similarity**

* `search_similar_items(conn, thread_id, embedding, type_tag, limit=10)` — similarity filtered by `type_tag` (never merge/conflict across types) and excludes superseded items. Uses sqlite-vec runtime index.
* `upsert_item_embedding(conn, uid, thread_id, embedding)`

**EXPAND support**

* `get_refs_content(conn, message_ids)` — fetch message content by msg IDs

**Schema/behavior explicitness: `last_seen_at` derivation rules**

* On insert:

  * `last_seen_at = max(created_at(refs))`
* On merge:

  * `last_seen_at = max(old.last_seen_at, max(created_at(new_refs)))`

This prevents regressions where merges accidentally “age” items.

---

### 3) `src/jarvis/memory/state_extractor.py` — LLM extraction + deterministic reconciliation

Two clean phases:

`async def extract_state_items(conn, thread_id, router, memory) -> ExtractResult`

#### Phase A — LLM Extraction (produces candidates)

1. Check watermark `(created_at, message_id)`. Fetch messages using tie-breaker query. Early return if none.

   * Log when skipping due to watermark for debuggability.

2. Skip if the new messages since watermark contain no user messages (assistant-only batches rarely produce new decisions).

3. Cap batch to `settings.state_extraction_max_messages`.

4. Fetch existing active state items as formal input block with strict instructions:

   ```
   ## Existing State (reference by UID — do NOT repeat unchanged items)
   [d_abc123] decision (active): Use PostgreSQL for analytics
   [a_def456] action (open): Set up connection pooling
   ```

5. Call LLM via `router.generate()` with extraction prompt.

   * Hard wall-clock timeout via `asyncio.wait_for(..., timeout=settings.state_extraction_timeout_seconds)` around the entire pipeline.

6. Parse JSON. Validate each item via `validate_item()`. Drop invalid.

#### Phase B — Deterministic Reconciliation (decides action per candidate)

Cap: max 25 candidates processed per run. Batch embedding if possible (else sequential).

For each candidate item:

1. **Validate refs**: every ref must exist in the allowed ref set — defined as exactly the message IDs included in the extraction prompt (the new batch). Drop item if refs are empty or all invalid after filtering.
2. Embed `candidate.text` via `memory.embed_text()`.
3. Search existing state items filtered by same `type_tag` and excluding superseded items via `state_store.search_similar_items()`.

   * Deterministic topic boost: `score = cosine + 0.02` if any topic overlaps (cap at 1.0). Fixed additive bonus so tests can lock it down.
4. Decision tree:

   * cosine ≥ `0.92` → **merge**: union refs/tags, `resolve_status_merge()`, max confidence.

     * Guard: if old is superseded, skip merge (don't resurrect).
   * cosine `0.85–0.92` + **supersession check** → **supersede** old item
   * cosine `0.85–0.92`, no supersession → **conflict**: set `conflict=true` on both candidate and existing item, insert candidate as new
   * cosine < `0.85` → insert as new

**Supersession check (deterministic v1)**
Requires ALL of:

* `has_supersession_signal(candidate.text)` (trigger present)
* candidate has ≥1 ref pointing to a **user** message
* candidate text contains a **replacement verb** (one of: `use`, `choose`, `switch`, `go with`, `adopt`)

Notes:

* Skip the “explicit negation of old text” heuristic for v1 (hard to do robustly). It can be added later as an optional bonus signal.

When superseding, set both sides deterministically:

* Old item: `status=superseded`, `replaced_by=candidate.uid`, `supersession_evidence={...}`
* Candidate: `status=active/open` (as extracted), `conflict=false` (supersession resolved the tension)
* Never mark candidate as both superseding AND conflicting — supersession wins.

Structured evidence stored on old item:

* `{"trigger": "instead", "ref_msg_id": "msg_123", "candidate_uid": "d_newuid"}`

5. Persist all candidates via `state_store.upsert_item()` + `upsert_item_embedding()`.
6. Update watermark last, in the same transaction as upserts — ensures a crash between parse and persist doesn't permanently skip messages.
7. Emit `state.extraction.complete` event with metrics.

**Conflict stickiness note**
Marking both sides `conflict=true` can permanently “scar” items. V1 can keep this simple, but consider later:

* adding `conflict_reason` / `conflict_with_uid`, or
* making conflict “soft” (only mark conflicts for items with `last_seen_at` within 30 days), or
* limiting conflicts per item.

---

### Extraction LLM prompt (system message)

You are a structured state extractor. Given conversation messages and existing state, extract new/updated items.

Types: decision, constraint, action, question, risk

Each item: `{type_tag, text, status, confidence, topic_tags[], refs[], supersedes (uid or null), conflict}`

Rules:

* Only concrete, specific items. No vague observations.
* Reference existing items by UID. Do NOT repeat unchanged items.
* Only output NEW items or updates (supersede/conflict) supported by the new messages.
* `refs` must be message IDs from the provided transcript only. Never invent IDs.
* `topic_tags`: 1–3 short labels max.
* Mark `supersedes` ONLY with explicit change language (instead, replaced, switched, changed to, no longer).
* Otherwise set `conflict=true` for tensions.
* Return ONLY a JSON array. No prose. No markdown fences.

Examples (keep ultra short to save tokens):

* Given:

  * `[msg_a1] user: Let's use Redis for caching`
  * `[msg_a2] assistant: OK`
    →
  * `[{"type_tag":"decision","text":"Use Redis for caching","status":"active","confidence":"high","topic_tags":["caching"],"refs":["msg_a1","msg_a2"],"supersedes":null,"conflict":false}]`

* Given:

  * `[msg_b1] user: Let's switch to Memcached instead of Redis`
  * Existing: `[d_abc123] decision (active): Use Redis for caching`
    →
  * `[{"type_tag":"decision","text":"Use Memcached for caching instead of Redis","status":"active","confidence":"high","topic_tags":["caching"],"refs":["msg_b1"],"supersedes":"d_abc123","conflict":false}]`

`ExtractResult`: `items_extracted, items_merged, items_conflicted, items_dropped, duration_ms, skipped_reason`

---

### 4) `src/jarvis/memory/state_renderer.py` — Compact rendering

`def render_state_section(items: list[StateItem]) -> str`

Format (one line per item, optimized for token efficiency):

```
State (updated: 2026-02-16T15:42Z, items: 12)
[d_abc123] DECISION (active) auth: Use OAuth2 PKCE flow [refs:2]
[a_def456] ACTION (open) deploy: Run migration 025 [refs:1]
[r_jkl012] RISK (active) security: No rate limiting on refresh [refs:1] CONFLICT
[q_mno345] QUESTION (open, low) arch: Cache embeddings client-side? [refs:1]
```

Rendering rules:

* One-line freshness header (≈10 tokens) to prevent stale-memory mistakes.
* Omit confidence unless it's `low` or `conflict=true`.
* Show first topic tag only (or none if empty).
* Show `refs:N` count, not raw message IDs.
* Append `CONFLICT` marker when `conflict=true`.
* Sort: pinned first → type priority (`decision > constraint > action > risk > question`) → confidence → `last_seen_at DESC`.
* Truncation handled by existing `_truncate_with_marker` in prompt builder.

---

### 5) `src/jarvis/db/migrations/025_state_items.sql`

```sql
CREATE TABLE IF NOT EXISTS state_items (
    uid TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    type_tag TEXT NOT NULL,
    topic_tags_json TEXT NOT NULL DEFAULT '[]',
    refs_json TEXT NOT NULL DEFAULT '[]',
    confidence TEXT NOT NULL DEFAULT 'medium',
    replaced_by TEXT,
    supersession_evidence TEXT,
    conflict INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'extraction',
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (uid, thread_id)
);

CREATE INDEX IF NOT EXISTS idx_state_items_thread_status ON state_items(thread_id, status);
CREATE INDEX IF NOT EXISTS idx_state_items_thread_type ON state_items(thread_id, type_tag);
CREATE INDEX IF NOT EXISTS idx_state_items_thread_updated ON state_items(thread_id, updated_at DESC);

-- Matches renderer freshness ordering
CREATE INDEX IF NOT EXISTS idx_state_items_thread_last_seen
ON state_items(thread_id, last_seen_at DESC);

CREATE TABLE IF NOT EXISTS state_item_embeddings (
    uid TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (uid, thread_id)
);

CREATE TABLE IF NOT EXISTS state_extraction_watermarks (
    thread_id TEXT PRIMARY KEY,
    last_message_created_at TEXT NOT NULL,
    last_message_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

sqlite-vec runtime index tables (`state_vec_index`, `state_vec_index_map`) created at runtime in `StateStore`, same pattern as `MemoryService._ensure_vec_runtime()`.

---

## Files to Modify

### 6) `src/jarvis/orchestrator/prompt_builder.py`

Budget allocation — replace `summary.long` with `structured_state`:

* Full mode: `summary.short 6%`, `structured_state 14%`, `skills 10%`, `context 15%`, `tail 55%`
* Minimal mode: `summary.short 6%`, `structured_state 14%`, `skills 8%`, `context 12%`, `tail 60%`

State section has both:

* token budget (14% via allocation)
* hard item cap (`state_max_active_items`)

`_build_prompt_with_report()`:

* add `structured_state: str = ""`
* insert `[structured_state]` between `summary.short` and `skills`
* remove `summary.long`
* keep `summary_long` param accepted but unused (backward compat)

Fallback during rollout:

* If `structured_state == ""` (extractor skipped/failed/empty), allow `summary.long` to render for that step only.

Public functions (`build_prompt`, `build_prompt_parts`, `build_prompt_with_report`) — add `structured_state: str = ""` param.

---

### 7) `src/jarvis/orchestrator/step.py`

Inline pre-step extraction after `memory.thread_summary()` and before `retrieved = ...`:

* call `extract_state_items()` when enabled
* log `skipped_reason` and metrics
* fetch active state items `state_store.get_active_items(... limit=state_max_active_items)`
* pass `structured_state=render_state_section(active_state_items)` into `build_prompt_with_report()`
* re-render state after compaction

---

### 8) `src/jarvis/config.py`

Add settings:

* `state_extraction_enabled: int = 1`
* `state_extraction_max_messages: int = 20`
* `state_extraction_merge_threshold: float = 0.92`
* `state_extraction_conflict_threshold: float = 0.85`
* `state_max_active_items: int = 40`
* `state_extraction_timeout_seconds: int = 15`

---

## On-Demand Expansion (follow-up PR)

Agent outputs `EXPAND: d_abc123` → orchestrator fetches refs (message IDs) → injects source messages into next prompt.

Implement as a registered tool (`expand_state_item`) so it participates in the permission system. Deferred to avoid scope creep.

---

## Testing

### Unit Tests (new files)

* `tests/unit/test_state_items.py`

  * normalization + UID determinism/prefixes
  * validate/coercion
  * supersession trigger detection
  * deterministic status precedence merge

* `tests/unit/test_state_store.py`

  * upsert/merge round-trip
  * mark_superseded sets status + replaced_by + evidence
  * watermark tie-breaker
  * get_active_items excludes superseded
  * no cross-type merges
  * last_seen_at derivation rules (insert + merge)

* `tests/unit/test_state_extractor.py`

  * skip on no new messages / no user messages
  * mocked LLM JSON parse + invalid drop
  * refs validation (allowed ref set only)
  * merge/conflict/supersede decision tree
  * supersession guardrails (trigger + replacement verb + user ref)
  * candidate cap
  * watermark advances only after successful persist
  * structured evidence stored

* `tests/unit/test_state_renderer.py`

  * empty renders empty
  * sort priority + last_seen ordering
  * conflict marker
  * conditional confidence
  * header present

### Existing tests to update

* `tests/unit/test_prompt_builder.py`

  * add `structured_state` param
  * verify `[structured_state]` section appears
  * verify backward compat with empty `structured_state`
  * verify fallback to `summary.long` when `structured_state` empty

### Integration

* `tests/integration/test_state_extraction_flow.py`

  * insert messages → run extraction (mock router)
  * verify DB items written + embeddings
  * verify idempotent watermark gating
  * verify watermark tie-breaker for equal timestamps

---

## Verification

1. `make migrate` — 025 applies cleanly
2. `uv run pytest tests/unit/test_state_items.py tests/unit/test_state_store.py tests/unit/test_state_renderer.py -v`
3. `uv run pytest tests/unit/test_state_extractor.py -v`
4. `uv run pytest tests/unit/test_prompt_builder.py -v`
5. `uv run pytest tests/ -x -q` — full suite green
6. `make lint && make typecheck` — clean
7. Manual: `uv run jarvis chat` → multi-turn conversation → verify `state.extraction.complete` events in logs

---

## Implementation Order

1. Migration `025_state_items.sql`
2. `state_items.py` (pure types + `resolve_status_merge`) + tests
3. `state_store.py` (DB layer with watermark tie-breaker + last_seen rules + type-filtered dedupe) + tests
4. `state_renderer.py` (compact rendering with conditional confidence + freshness header) + tests
5. `state_extractor.py` (LLM extraction → deterministic reconciliation split) + tests
6. `config.py` additions
7. `prompt_builder.py` changes + update tests
8. `step.py` integration + integration test
