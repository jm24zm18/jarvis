"""Agent bundle loader from disk with hot-reload support."""

import logging
from pathlib import Path

from jarvis.agents.types import AgentBundle

logger = logging.getLogger(__name__)

REQUIRED_FILES = ("identity.md", "soul.md", "heartbeat.md")

# Cache: agent_id -> (bundle, max_mtime)
_bundle_cache: dict[str, tuple[AgentBundle, float]] = {}


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

    bundle = AgentBundle(
        agent_id=agent_dir.name,
        identity_markdown=identity,
        soul_markdown=soul,
        heartbeat_markdown=heartbeat,
        allowed_tools=tools,
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
