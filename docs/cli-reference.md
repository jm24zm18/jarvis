# CLI Reference

Source of truth: `src/jarvis/cli/main.py`.

## Usage

```bash
uv run jarvis --help
```

## Top-Level Commands

- `setup`: interactive setup wizard.
- `doctor`: diagnostics (`--fix`, `--json`).
- `ask`: single prompt/reply interaction.
- `chat`: interactive chat loop.
- `export`: export thread data as JSONL.
- `build`: enqueue self-improvement build workflow.
- `test-gates`: run quality gates from CLI.

## Command Groups

### `skill`

- `uv run jarvis skill install <path> [--scope global] [--actor-id cli]`
- `uv run jarvis skill list [--scope global] [--limit 50]`
- `uv run jarvis skill info <slug> [--scope global]`

### `maintenance`

- `uv run jarvis maintenance status [--json]`
- `uv run jarvis maintenance run [--json]`
- `uv run jarvis maintenance enqueue`

### `memory`

- `uv run jarvis memory review --conflicts [--limit 50]`
- `uv run jarvis memory export [--format jsonl] [--tier <tier>] [--thread-id <thr_...>] [-o <file>] [--limit 1000]`

## Setup Wizard Env Groups

`uv run jarvis setup` prompts by environment category (from `src/jarvis/cli/env_groups.py`):

- `Core` (required)
- `Task Runner` (required)
- `WhatsApp` (optional)
- `OpenRouter` (optional)
- `Local LLM (SGLang)` (required for local dev profile)
- `Local LLM (LM Studio)` (optional)
- `Embeddings (Ollama)` (required for local dev profile)
- `Search (SearXNG)` (required for local dev profile)
- `Backup & Alerting` (optional)
- `GitHub PR Automation` (optional)

## Common Examples

```bash
uv run jarvis doctor --fix
uv run jarvis ask "summarize this repo"
uv run jarvis ask "health check" --json --enqueue
uv run jarvis chat --new-thread
uv run jarvis export thr_123 --include-events -o thread.jsonl
uv run jarvis test-gates --fail-fast
uv run jarvis maintenance status --json
uv run jarvis skill list
```

## Preconditions

- API runtime should be active (`make api`) for chat/ask/build flows.
- DB migrations should be current (`make migrate`).

## Diagnostics Error Contract

`jarvis ask --json` and doctor HTTP checks classify network/provider outages into deterministic codes:
- `dns_resolution`
- `timeout`
- `network_unreachable`
- `provider_unavailable`

Doctor also validates DB-path consistency to detect split-brain local setups
(for example, querying an empty `jarvis.db` while `APP_DB` points to `app.db`).

Use targeted evidence checks:

```bash
uv run pytest tests/unit/test_cli_checks.py -q
uv run pytest tests/unit/test_cli_chat.py -q
uv run jarvis doctor --json
```

## Output Formatting Policy

- Human mode (`default`) is optimized for readability.
- JSON mode (`--json`) is machine-only payload output:
  - `jarvis doctor --json` prints only JSON.
  - `jarvis test-gates --json` prints only JSON.
- CLI export writes text files with explicit UTF-8 encoding.

## Related Docs

- `docs/getting-started.md`
- `docs/local-development.md`
- `docs/testing.md`
- `docs/configuration.md`
