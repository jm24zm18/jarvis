"""Agent bundle loader from disk with hot-reload support."""

import logging
from pathlib import Path

from jarvis.agents.types import AgentBundle

logger = logging.getLogger(__name__)

REQUIRED_FILES = ("identity.md", "soul.md", "heartbeat.md")

# Cache for discovered agent IDs
_agent_ids_cache: tuple[frozenset[str], float] | None = None


def get_all_agent_ids(agent_root: Path = Path("agents")) -> frozenset[str]:
    """Discover all agent IDs from the agents/ directory on disk.

    Returns a frozenset of agent directory names that contain
    the required bundle files.
    """
    global _agent_ids_cache
    if not agent_root.exists():
        return frozenset({"main"})

    # Simple mtime-based cache invalidation
    root_mtime = agent_root.stat().st_mtime
    if _agent_ids_cache is not None:
        cached_ids, cached_mtime = _agent_ids_cache
        if root_mtime <= cached_mtime:
            return cached_ids

    ids: set[str] = set()
    for candidate in sorted(agent_root.iterdir()):
        if not candidate.is_dir():
            continue
        if all((candidate / f).exists() for f in REQUIRED_FILES):
            ids.add(candidate.name)
    if not ids:
        ids.add("main")
    result = frozenset(ids)
    _agent_ids_cache = (result, root_mtime)
    return result

# Cache: agent_id -> (bundle, max_mtime)
_bundle_cache: dict[str, tuple[AgentBundle, float]] = {}


def reset_loader_caches() -> None:
    """Clear in-process caches so agent discovery and bundles are reloaded from disk."""
    global _agent_ids_cache
    _agent_ids_cache = None
    _bundle_cache.clear()


def _parse_allowed_tools(identity_markdown: str) -> list[str]:
    lines = identity_markdown.splitlines()
    allowed: list[str] = []
    in_allowed = False
    for line in lines:
        stripped = line.strip()
        if stripped == "allowed_tools:":
            in_allowed = True
            continue
        if in_allowed:
            if stripped.startswith("- "):
                allowed.append(stripped[2:].strip())
                continue
            if stripped.startswith("---") or stripped == "":
                continue
            break
    return allowed


def _parse_identity_frontmatter(identity_markdown: str) -> dict[str, object]:
    if not identity_markdown.startswith("---"):
        return {}
    end = identity_markdown.find("\n---", 3)
    if end == -1:
        return {}
    block = identity_markdown[3:end].strip()
    parsed: dict[str, object] = {}
    current_list_key: str | None = None
    current_list_values: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if current_list_key and stripped.startswith("- "):
            item = stripped[2:].strip()
            if item:
                current_list_values.append(item)
            continue
        if current_list_key:
            parsed[current_list_key] = current_list_values
            current_list_key = None
            current_list_values = []
        if ":" not in stripped:
            continue
        key, raw = stripped.split(":", 1)
        key = key.strip()
        value = raw.strip()
        if not value:
            current_list_key = key
            current_list_values = []
            continue
        lowered = value.lower()
        if lowered in {"true", "false"}:
            parsed[key] = lowered == "true"
        elif value.isdigit():
            parsed[key] = int(value)
        else:
            parsed[key] = value
    if current_list_key:
        parsed[current_list_key] = current_list_values
    return parsed


def _parse_governance(identity_markdown: str) -> tuple[str, int, tuple[str, ...], bool]:
    frontmatter = _parse_identity_frontmatter(identity_markdown)
    risk_tier = str(frontmatter.get("risk_tier", "")).strip().lower()
    if risk_tier not in {"low", "medium", "high"}:
        raise RuntimeError("identity frontmatter missing valid risk_tier")

    max_actions_raw = frontmatter.get("max_actions_per_step")
    if not isinstance(max_actions_raw, int) or max_actions_raw < 1:
        raise RuntimeError("identity frontmatter missing valid max_actions_per_step")

    allowed_paths_raw = frontmatter.get("allowed_paths")
    if not isinstance(allowed_paths_raw, list) or not allowed_paths_raw:
        raise RuntimeError("identity frontmatter missing non-empty allowed_paths")
    allowed_paths: list[str] = []
    for item in allowed_paths_raw:
        if not isinstance(item, str) or not item.strip():
            raise RuntimeError("identity frontmatter has invalid allowed_paths entry")
        allowed_paths.append(item.strip())

    can_request = frontmatter.get("can_request_privileged_change")
    if not isinstance(can_request, bool):
        raise RuntimeError("identity frontmatter missing can_request_privileged_change")
    return risk_tier, max_actions_raw, tuple(allowed_paths), can_request


def _get_bundle_mtime(agent_dir: Path) -> float:
    """Get the maximum mtime of all files in an agent bundle directory."""
    max_mtime = 0.0
    for child in agent_dir.iterdir():
        if child.is_file():
            max_mtime = max(max_mtime, child.stat().st_mtime)
    return max_mtime


def load_agent_bundle(agent_dir: Path) -> AgentBundle:
    missing = [name for name in REQUIRED_FILES if not (agent_dir / name).exists()]
    if missing:
        raise RuntimeError(
            f"agent bundle {agent_dir.name} missing required files: {', '.join(missing)}"
        )

    identity = (agent_dir / "identity.md").read_text()
    soul = (agent_dir / "soul.md").read_text()
    heartbeat = (agent_dir / "heartbeat.md").read_text()

    # Load optional tools.md for tool-specific prompt instructions
    tools_md_path = agent_dir / "tools.md"
    tools_md = tools_md_path.read_text() if tools_md_path.exists() else ""

    tools = _parse_allowed_tools(identity)
    if not tools:
        tools = ["echo"]
    risk_tier, max_actions_per_step, allowed_paths, can_request_privileged_change = (
        _parse_governance(identity)
    )

    bundle = AgentBundle(
        agent_id=agent_dir.name,
        identity_markdown=identity,
        soul_markdown=soul,
        heartbeat_markdown=heartbeat,
        allowed_tools=tools,
        risk_tier=risk_tier,
        max_actions_per_step=max_actions_per_step,
        allowed_paths=allowed_paths,
        can_request_privileged_change=can_request_privileged_change,
        tools_markdown=tools_md,
    )
    # Update cache
    mtime = _get_bundle_mtime(agent_dir)
    _bundle_cache[agent_dir.name] = (bundle, mtime)
    return bundle


def load_agent_bundle_cached(agent_dir: Path) -> AgentBundle:
    """Load an agent bundle, using cache if files haven't changed."""
    agent_id = agent_dir.name
    current_mtime = _get_bundle_mtime(agent_dir)

    cached = _bundle_cache.get(agent_id)
    if cached is not None:
        bundle, cached_mtime = cached
        if current_mtime <= cached_mtime:
            return bundle
        logger.info("Hot-reloading agent bundle: %s (mtime changed)", agent_id)

    return load_agent_bundle(agent_dir)


def load_agent_registry(root: Path) -> dict[str, AgentBundle]:
    if not root.exists():
        raise RuntimeError(f"agent root does not exist: {root}")
    bundles: dict[str, AgentBundle] = {}
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir():
            continue
        bundle = load_agent_bundle(candidate)
        bundles[bundle.agent_id] = bundle
    if not bundles:
        raise RuntimeError("no agent bundles found")
    return bundles
