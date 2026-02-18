# CLI Reference

Source of truth: `src/jarvis/cli/main.py`.

## Usage

```bash
uv run jarvis --help
```

## Top-Level Commands

- `setup`: interactive setup wizard.
- `doctor`: diagnostics (`--fix`, `--json`).
- `gemini-login`: manual OAuth token bootstrap for Gemini Code Assist.
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
- For `gemini-login`, environment must include Gemini provider config in `.env`.

## Related Docs

- `docs/getting-started.md`
- `docs/local-development.md`
- `docs/testing.md`
- `docs/configuration.md`
