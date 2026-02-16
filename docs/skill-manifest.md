# Skill Package Manifest

Skill packages use `manifest.yaml` with these fields:

- `slug`: unique identifier.
- `title`: display name.
- `version`: package version string.
- `min_jarvis_version`: minimum Jarvis version (optional, advisory).
- `author`: package author (optional).
- `tools_required`: required tool names list.
- `tools_optional`: optional tool names list.
- `scope`: default install scope (optional).
- `pinned`: whether to pin after install (`true`/`false`).
- `files`: markdown files to compose into skill content.

## Install conventions
- Install command: `uv run jarvis skill install <path>`
- List command: `uv run jarvis skill list`
- Info command: `uv run jarvis skill info <slug>`
- On install, Jarvis:
  - stores package metadata on `skills` (`package_version`, `manifest_json`, `installed_at`, `install_source`)
  - writes audit rows to `skill_install_log`
  - verifies `tools_required` against configured `tool_permissions` and warns on missing tools

Example:

```yaml
slug: deploy-helper
title: Deploy Helper
version: 1.0.0
min_jarvis_version: 0.1.0
author: platform-team
tools_required:
  - web_search
tools_optional:
  - host_exec
scope: global
pinned: true
files:
  - SKILL.md
```
