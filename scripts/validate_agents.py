#!/usr/bin/env python3
"""Validate all agent bundles under agents/ directory.

Checks:
- Required files exist (identity.md, soul.md, heartbeat.md)
- YAML frontmatter in identity.md has agent_id matching directory name
- allowed_tools is non-empty
- governance fields are present and valid
- Referenced tools exist in the tool registry
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"
AGENT_TASK_FILE = ROOT / "src" / "jarvis" / "tasks" / "agent.py"
REQUIRED_FILES = ("identity.md", "soul.md", "heartbeat.md")


def _parse_frontmatter(text: str) -> dict[str, object]:
    """Parse YAML frontmatter from markdown text (simple key: value parser)."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()
    result: dict[str, object] = {}
    current_key: str | None = None
    current_list: list[str] = []

    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # List item under current key
        if stripped.startswith("- ") and current_key is not None:
            current_list.append(stripped[2:].strip())
            continue
        # New key
        if ":" in stripped:
            # Save previous list key
            if current_key is not None and current_list:
                result[current_key] = current_list
            parts = stripped.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip()
            if val:
                lowered = val.lower()
                if lowered in {"true", "false"}:
                    result[key] = lowered == "true"
                elif val.isdigit():
                    result[key] = int(val)
                else:
                    result[key] = val
                current_key = None
                current_list = []
            else:
                current_key = key
                current_list = []

    if current_key is not None and current_list:
        result[current_key] = current_list

    return result


def _discover_registered_tools() -> set[str]:
    """Auto-discover tool names by scanning agent.py for registry.register() calls."""
    if not AGENT_TASK_FILE.exists():
        return set()
    content = AGENT_TASK_FILE.read_text()
    # Match registry.register("toolname", ...) patterns
    return set(re.findall(r'registry\.register\(\s*"([^"]+)"', content))


def validate() -> list[str]:
    errors: list[str] = []
    registered_tools = _discover_registered_tools()

    if not AGENTS_DIR.exists():
        errors.append(f"agents directory not found: {AGENTS_DIR}")
        return errors

    agent_dirs = sorted(d for d in AGENTS_DIR.iterdir() if d.is_dir())
    if not agent_dirs:
        errors.append("no agent directories found")
        return errors

    print(f"Discovered {len(registered_tools)} registered tools: {sorted(registered_tools)}")
    print(f"Validating {len(agent_dirs)} agent bundles...\n")

    for agent_dir in agent_dirs:
        agent_id = agent_dir.name
        prefix = f"  [{agent_id}]"

        # Check required files
        for req in REQUIRED_FILES:
            if not (agent_dir / req).exists():
                errors.append(f"{prefix} missing required file: {req}")

        # Parse and validate identity.md frontmatter
        identity_path = agent_dir / "identity.md"
        if identity_path.exists():
            frontmatter = _parse_frontmatter(identity_path.read_text())

            # Check agent_id matches directory name
            fm_agent_id = frontmatter.get("agent_id")
            if fm_agent_id != agent_id:
                errors.append(
                    f"{prefix} agent_id mismatch: frontmatter has '{fm_agent_id}', "
                    f"directory is '{agent_id}'"
                )

            # Check allowed_tools is non-empty
            tools = frontmatter.get("allowed_tools")
            if not isinstance(tools, list) or len(tools) == 0:
                errors.append(f"{prefix} allowed_tools is empty or missing")
            elif registered_tools:
                # Validate tools exist in registry
                for tool in tools:
                    if tool not in registered_tools:
                        errors.append(f"{prefix} tool '{tool}' not found in registry")

            risk_tier = frontmatter.get("risk_tier")
            if risk_tier not in {"low", "medium", "high"}:
                errors.append(f"{prefix} risk_tier must be one of low|medium|high")

            max_actions = frontmatter.get("max_actions_per_step")
            if not isinstance(max_actions, int) or max_actions < 1:
                errors.append(f"{prefix} max_actions_per_step must be integer >= 1")

            allowed_paths = frontmatter.get("allowed_paths")
            if not isinstance(allowed_paths, list) or not allowed_paths:
                errors.append(f"{prefix} allowed_paths must be a non-empty list")
            elif any(not isinstance(path, str) or not path.strip() for path in allowed_paths):
                errors.append(f"{prefix} allowed_paths entries must be non-empty strings")

            can_request = frontmatter.get("can_request_privileged_change")
            if not isinstance(can_request, bool):
                errors.append(
                    f"{prefix} can_request_privileged_change must be true or false"
                )

        print(f"  {agent_id}: OK" if not any(agent_id in e for e in errors) else "")

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print(f"\n{len(errors)} error(s) found:")
        for err in errors:
            print(f"  ERROR: {err}")
        return 1
    print("\nAll agent bundles valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
