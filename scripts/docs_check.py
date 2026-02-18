#!/usr/bin/env python3
"""Check markdown links and docs command/API drift."""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable
from pathlib import Path

from click.core import Group

from jarvis.cli.main import cli
from generate_api_docs import render_api_reference

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_GLOBS = ["README.md", "AGENTS.md", "CLAUDE.md", "docs/**/*.md"]
SKIP_PARTS = ("docs/gemini/venv", "web/node_modules")


class CheckError(Exception):
    """Raised when a docs check fails."""


def _iter_doc_files() -> Iterable[Path]:
    seen: set[Path] = set()
    for pattern in DOC_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(part in rel for part in SKIP_PARTS):
                continue
            if path in seen:
                continue
            seen.add(path)
            yield path


def _parse_make_targets() -> set[str]:
    targets: set[str] = set()
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for line in makefile.splitlines():
        if not line or line.startswith(("#", "\t", " ")):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+):", line)
        if match:
            targets.add(match.group(1))
    return targets


def _iter_local_links(markdown: str) -> Iterable[str]:
    for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", markdown):
        target = match.group(1).strip()
        if not target or target.startswith("#"):
            continue
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            continue
        yield target


def _check_links() -> list[str]:
    failures: list[str] = []
    for path in _iter_doc_files():
        text = path.read_text(encoding="utf-8")
        for target in _iter_local_links(text):
            raw_target = target.split("#", 1)[0].split("?", 1)[0]
            if not raw_target:
                continue
            resolved = (path.parent / raw_target).resolve()
            if not resolved.exists():
                rel = path.relative_to(REPO_ROOT).as_posix()
                failures.append(f"{rel}: broken link -> {target}")
    return failures


def _check_make_commands() -> list[str]:
    failures: list[str] = []
    targets = _parse_make_targets()
    pattern = re.compile(r"\bmake\s+([A-Za-z0-9_.-]+)")
    for path in _iter_doc_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for match in pattern.finditer(text):
            target = match.group(1)
            if target not in targets:
                failures.append(f"{rel}: unknown make target `{target}`")
    return failures


def _walk_cli_commands(group: Group, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    commands: set[tuple[str, ...]] = set()
    for name, command in group.commands.items():
        chain = prefix + (name,)
        commands.add(chain)
        if isinstance(command, Group):
            commands.update(_walk_cli_commands(command, chain))
    return commands


def _parse_cli_invocation(trailing: str) -> tuple[str, ...]:
    try:
        tokens = shlex.split(trailing)
    except ValueError:
        return tuple()
    if not tokens:
        return tuple()
    if tokens[0] in {"--help", "-h"}:
        return tuple()

    chain: list[str] = []
    group: Group = cli
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token.startswith("-"):
            idx += 1
            continue
        command = group.commands.get(token)
        if command is None:
            break
        chain.append(token)
        idx += 1
        if isinstance(command, Group):
            group = command
            continue
        break
    return tuple(chain)


def _check_cli_commands() -> list[str]:
    failures: list[str] = []
    known = _walk_cli_commands(cli)
    pattern = re.compile(r"uv\s+run\s+jarvis\s+([^\n`]+)")
    for path in _iter_doc_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for match in pattern.finditer(text):
            trailing = match.group(1).strip()
            chain = _parse_cli_invocation(trailing)
            if not chain:
                continue
            if chain not in known:
                failures.append(f"{rel}: unknown CLI command `jarvis {' '.join(chain)}`")
    return failures


def _check_api_reference_sync() -> list[str]:
    api_path = REPO_ROOT / "docs/api-reference.md"
    if not api_path.exists():
        return ["docs/api-reference.md missing (run `make docs-generate`) "]
    expected = render_api_reference().strip()
    actual = api_path.read_text(encoding="utf-8").strip()
    if expected != actual:
        return ["docs/api-reference.md is out of date (run `make docs-generate`) "]
    return []


def main() -> int:
    failures = []
    failures.extend(_check_links())
    failures.extend(_check_make_commands())
    failures.extend(_check_cli_commands())
    failures.extend(_check_api_reference_sync())
    if failures:
        print("docs check failed:")
        for item in failures:
            print(f"- {item}")
        return 1
    print("docs check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
