"""PLAN.md parser and updater for the Ralph autonomous improvement loop.

Reads the `## Ralph Sprint` section, finds the next unchecked task,
and marks tasks as done or failed atomically.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_RALPH_SECTION_RE = re.compile(r"^## Ralph Sprint", re.MULTILINE)
_NEXT_SECTION_RE = re.compile(r"^## ", re.MULTILINE)
_UNCHECKED_RE = re.compile(r"^- \[ \] (.+)$")
_ACCEPT_RE = re.compile(r"^\s+Accept:\s*(.+)$")


def _read_plan(plan_path: str) -> str:
    return Path(plan_path).read_text(encoding="utf-8")


def _write_plan_atomic(plan_path: str, content: str) -> None:
    """Write content to plan_path atomically via temp file + rename."""
    p = Path(plan_path)
    fd, tmp_path = tempfile.mkstemp(dir=p.parent, prefix=".ralph_plan_tmp_")
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp_path, p)


def _locate_ralph_section(lines: list[str]) -> tuple[int, int]:
    """Return (start, end) line indices of the Ralph Sprint section (exclusive end).

    Raises RuntimeError if the section is not found.
    """
    text = "".join(lines)
    match = _RALPH_SECTION_RE.search(text)
    if match is None:
        raise RuntimeError(
            "## Ralph Sprint section not found in PLAN.md — "
            "Ralph requires this section to be present."
        )

    # Find the line index of the section header.
    start_char = match.start()
    start_line = text[:start_char].count("\n")

    # Find the next top-level ## section after ours.
    rest = text[match.end():]
    next_match = _NEXT_SECTION_RE.search(rest)
    if next_match is None:
        end_line = len(lines)
    else:
        end_char = match.end() + next_match.start()
        end_line = text[:end_char].count("\n")

    return start_line, end_line


def next_ralph_task(plan_path: str = "docs/PLAN.md") -> dict[str, object] | None:
    """Parse the ## Ralph Sprint section; return the first unchecked task or None.

    Returns a dict with keys:
      - text (str): the task description text (first line of the item)
      - accept (str | None): acceptance criteria text if an Accept: line follows
      - line_number (int): 0-based line index of the `- [ ]` line in the file
      - slug (str): a URL-safe slug derived from task text
    """
    content = _read_plan(plan_path)
    lines = content.splitlines(keepends=True)
    start_line, end_line = _locate_ralph_section(lines)

    i = start_line
    while i < end_line:
        line = lines[i].rstrip("\n")
        m = _UNCHECKED_RE.match(line)
        if m:
            task_text = m.group(1).strip()
            accept: str | None = None

            # Look ahead for continuation lines and Accept: line.
            # Continuation lines start with whitespace (indented under the task).
            j = i + 1
            while j < end_line:
                next_line = lines[j].rstrip("\n")
                if not next_line.startswith(" ") and not next_line.startswith("\t"):
                    break
                accept_match = _ACCEPT_RE.match(next_line)
                if accept_match:
                    accept = accept_match.group(1).strip()
                j += 1

            slug = _slugify(task_text)
            return {
                "text": task_text,
                "accept": accept,
                "line_number": i,
                "slug": slug,
            }
        i += 1

    return None


def mark_task_done(task: dict[str, object], plan_path: str = "docs/PLAN.md") -> None:
    """Toggle '- [ ]' → '- [x]' at task['line_number'].

    Only modifies the single checkbox line. Fails loudly on mismatch.
    """
    line_number = int(str(task["line_number"]))
    content = _read_plan(plan_path)
    lines = content.splitlines(keepends=True)

    if line_number >= len(lines):
        raise RuntimeError(
            f"ralph_plan: line_number {line_number} out of range "
            f"(file has {len(lines)} lines)"
        )

    original = lines[line_number]
    if not _UNCHECKED_RE.match(original.rstrip("\n")):
        raise RuntimeError(
            f"ralph_plan: expected unchecked item at line {line_number}, "
            f"got: {original!r}"
        )

    lines[line_number] = original.replace("- [ ] ", "- [x] ", 1)
    _write_plan_atomic(plan_path, "".join(lines))


def mark_task_failed(
    task: dict[str, object],
    reason: str,
    plan_path: str = "docs/PLAN.md",
) -> None:
    """Append a failure note after the task line without checking it off."""
    line_number = int(str(task["line_number"]))
    content = _read_plan(plan_path)
    lines = content.splitlines(keepends=True)

    if line_number >= len(lines):
        raise RuntimeError(
            f"ralph_plan: line_number {line_number} out of range "
            f"(file has {len(lines)} lines)"
        )

    original = lines[line_number]
    if not _UNCHECKED_RE.match(original.rstrip("\n")):
        raise RuntimeError(
            f"ralph_plan: expected unchecked item at line {line_number} for failure note, "
            f"got: {original!r}"
        )

    # Detect indentation used by this task block.
    indent = "      "
    # Insert failure note after the task line (before any existing continuation).
    failure_note = f"{indent}FAILED: {reason[:200]}\n"
    lines.insert(line_number + 1, failure_note)
    _write_plan_atomic(plan_path, "".join(lines))


def _slugify(text: str) -> str:
    """Convert task text to a URL-safe slug (max 40 chars)."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:40]
