"""Build deterministic, machine-readable repository index artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from jarvis.repo_index.types import CommandEntry, MigrationEntry, RepoIndex

REPO_INDEX_DIR = ".jarvis"
REPO_INDEX_FILE = "repo_index.json"
REPO_INDEX_HASH_FILE = "repo_index.sha256"

ENTRYPOINT_CANDIDATES = (
    "src/jarvis/main.py",
    "src/jarvis/cli/main.py",
    "web/src/App.tsx",
)

PROTECTED_MODULES = (
    "src/jarvis/policy/engine.py",
    "src/jarvis/tools/runtime.py",
    "src/jarvis/auth",
    "src/jarvis/db/migrations",
)

INVARIANT_CHECKS = (
    "deny-by-default tool policy",
    "append-only database migrations",
    "traceable events schema",
    "ownership/rbac boundaries",
    "no direct master writes",
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_makefile_commands(repo_root: Path) -> list[CommandEntry]:
    makefile = repo_root / "Makefile"
    if not makefile.exists():
        return []
    lines = makefile.read_text(encoding="utf-8").splitlines()
    commands: list[CommandEntry] = []
    current_target = ""
    current_recipe: list[str] = []
    target_re = re.compile(r"^([A-Za-z0-9_.-]+):")

    def flush() -> None:
        nonlocal current_target, current_recipe
        if current_target:
            commands.append(CommandEntry(target=current_target, recipe=list(current_recipe)))
        current_target = ""
        current_recipe = []

    for line in lines:
        match = target_re.match(line)
        if match and not line.startswith("\t"):
            flush()
            current_target = match.group(1)
            continue
        if current_target and line.startswith("\t"):
            current_recipe.append(line.strip())
    flush()
    commands.sort(key=lambda item: item.target)
    return commands


def _parse_migrations(repo_root: Path) -> list[MigrationEntry]:
    migrations_dir = repo_root / "src/jarvis/db/migrations"
    if not migrations_dir.exists():
        return []
    entries: list[MigrationEntry] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        name = path.name
        prefix = name.split("_", 1)[0]
        if not prefix.isdigit():
            continue
        entries.append(MigrationEntry(file=str(path.relative_to(repo_root)), number=int(prefix)))
    entries.sort(key=lambda item: item.number)
    return entries


def _list_api_routes(repo_root: Path) -> list[str]:
    api_dir = repo_root / "src/jarvis/routes/api"
    if not api_dir.exists():
        return []
    routes = [str(path.relative_to(repo_root)) for path in sorted(api_dir.rglob("*.py"))]
    return routes


def _parse_agent_allowed_tools(identity_path: Path) -> list[str]:
    raw = identity_path.read_text(encoding="utf-8")
    tools: list[str] = []
    in_block = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == "allowed_tools:":
            in_block = True
            continue
        if in_block:
            if not stripped:
                continue
            if stripped.startswith("-"):
                tool = stripped[1:].strip()
                if tool:
                    tools.append(tool)
                continue
            break
    return sorted(set(tools))


def _collect_agents(repo_root: Path) -> dict[str, list[str]]:
    agents_dir = repo_root / "agents"
    if not agents_dir.exists():
        return {}
    data: dict[str, list[str]] = {}
    for identity in sorted(agents_dir.glob("*/identity.md")):
        agent_id = identity.parent.name
        data[agent_id] = _parse_agent_allowed_tools(identity)
    return data


def _as_dict(index: RepoIndex) -> dict[str, object]:
    return {
        "generated_at": index.generated_at,
        "repo_root": index.repo_root,
        "entrypoints": index.entrypoints,
        "commands": [{"target": item.target, "recipe": item.recipe} for item in index.commands],
        "migrations": [{"file": item.file, "number": item.number} for item in index.migrations],
        "protected_modules": index.protected_modules,
        "api_routes": index.api_routes,
        "agents": index.agents,
        "invariant_checks": index.invariant_checks,
    }


def build_repo_index(repo_root: Path) -> dict[str, object]:
    entrypoints = [
        candidate for candidate in ENTRYPOINT_CANDIDATES if (repo_root / candidate).exists()
    ]
    index = RepoIndex(
        generated_at=_now_iso(),
        repo_root=str(repo_root),
        entrypoints=sorted(entrypoints),
        commands=_parse_makefile_commands(repo_root),
        migrations=_parse_migrations(repo_root),
        protected_modules=sorted(PROTECTED_MODULES),
        api_routes=_list_api_routes(repo_root),
        agents=_collect_agents(repo_root),
        invariant_checks=sorted(INVARIANT_CHECKS),
    )
    return _as_dict(index)


def write_repo_index(repo_root: Path) -> tuple[Path, Path]:
    payload = build_repo_index(repo_root)
    out_dir = repo_root / REPO_INDEX_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / REPO_INDEX_FILE
    hash_path = out_dir / REPO_INDEX_HASH_FILE

    encoded = json.dumps(payload, sort_keys=True, indent=2)
    out_path.write_text(encoded + "\n", encoding="utf-8")
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    hash_path.write_text(digest + "\n", encoding="utf-8")
    return out_path, hash_path


def read_repo_index(repo_root: Path) -> dict[str, object] | None:
    path = repo_root / REPO_INDEX_DIR / REPO_INDEX_FILE
    if not path.exists():
        return None
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded
