"""Types for deterministic repository index artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CommandEntry:
    target: str
    recipe: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MigrationEntry:
    file: str
    number: int


@dataclass(slots=True)
class RepoIndex:
    generated_at: str
    repo_root: str
    entrypoints: list[str]
    commands: list[CommandEntry]
    migrations: list[MigrationEntry]
    protected_modules: list[str]
    api_routes: list[str]
    agents: dict[str, list[str]]
    invariant_checks: list[str]
