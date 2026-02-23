"""Decomposition prompt builder, parser, and validator."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from jarvis.orchestrator.prompt_builder import estimate_tokens
from jarvis.rlm.config import RLMConfig

ANCHOR_FILES = (
    "src/jarvis/tasks/feature_build.py",
    "src/jarvis/services/feature_requests.py",
    "src/jarvis/db/queries.py",
)

KEYWORD_HINTS: dict[str, Sequence[str]] = {
    "db": ("src/jarvis/db/queries.py", "src/jarvis/db/migrations"),
    "migration": ("src/jarvis/db/migrations",),
    "service": ("src/jarvis/services/feature_requests.py", "src/jarvis/services/approvals.py"),
    "task": ("src/jarvis/tasks/feature_build.py", "src/jarvis/tasks/agent.py"),
    "memory": ("src/jarvis/memory/service.py", "src/jarvis/memory/state_renderer.py"),
    "orchestrator": ("src/jarvis/orchestrator/step.py",),
    "prompt": ("src/jarvis/orchestrator/prompt_builder.py",),
    "web": ("web/src/App.tsx", "web/src/pages/chat/index.tsx"),
    "docs": ("docs/architecture.md",),
}

EXPLICIT_PATH_PATTERN = re.compile(r"(src/[A-Za-z0-9_/.-]+)")
ACCEPTANCE_KEYWORDS = (
    "test",
    "assert",
    "response",
    "migration",
    "lint",
    "typecheck",
    "verify",
    "doc",
)


@dataclass(frozen=True)
class ContextFile:
    path: str
    content: str
    reason: str
    tokens: int


def select_context_files(description: str, config: RLMConfig) -> list[ContextFile]:
    """Return prioritized context files with reasons."""
    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []
    description_lower = description.lower()
    candidates.extend((path, "anchor") for path in ANCHOR_FILES)
    for match in EXPLICIT_PATH_PATTERN.finditer(description):
        candidates.append((match.group(1), "explicit"))
    for keyword, hints in KEYWORD_HINTS.items():
        if keyword not in description_lower:
            continue
        for hint_path in hints:
            candidates.append((hint_path, f"keyword:{keyword}"))

    selected: list[ContextFile] = []
    tokens_remaining = config.context_token_limit
    for path, reason in candidates:
        if len(selected) >= config.context_files_limit or tokens_remaining <= 0:
            break
        if path in seen:
            continue
        seen.add(path)
        normalized = Path(path)
        if not normalized.exists() or not normalized.is_file():
            continue
        try:
            raw = normalized.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        tokens = estimate_tokens(raw)
        truncated, consumed = _truncate_content(raw, min(tokens, tokens_remaining))
        if not truncated:
            continue
        selected.append(
            ContextFile(path=path, content=truncated, reason=reason, tokens=consumed)
        )
        tokens_remaining -= consumed
    return selected


def _truncate_content(text: str, token_budget: int) -> tuple[str, int]:
    if token_budget <= 0:
        return "", 0
    max_chars = max(64, token_budget * 4)
    normalized = text.strip()
    if len(normalized) <= max_chars:
        return normalized, estimate_tokens(normalized)
    head_chars = max(32, int(max_chars * 0.65))
    tail_chars = max(16, int(max_chars * 0.25))
    marker = "\n[...truncated for context...]\n"
    if head_chars + tail_chars + len(marker) >= max_chars:
        clipped = normalized[: max_chars - 1] + "…"
        return clipped, estimate_tokens(clipped)
    clipped = f"{normalized[:head_chars]}{marker}{normalized[-tail_chars:]}"
    return clipped, estimate_tokens(clipped)


def build_decompose_prompt(
    feature_title: str,
    feature_description: str,
    context_files: Iterable[ContextFile],
) -> tuple[str, list[str]]:
    """Build the initial decomposition prompt and return allowed paths."""
    allowed_paths: list[str] = []
    sections: list[str] = []
    for item in context_files:
        allowed_paths.append(item.path)
        sections.append(f"## {item.path}\nReason: {item.reason}\n{item.content}")
    context_dump = "\n\n".join(sections) if sections else "No code context available."
    allowed_list = "\n".join(f"- {path}" for path in allowed_paths) or "- (none)"
    prompt = f"""
You are a feature decomposition agent for the Jarvis codebase.
Given the feature description, decompose the work into 3-6 atomic subtasks.
Each subtask must be scoped to at most 3 target files. Allowed files are listed below.
Use llm_query() recursively if you need to analyze deeper layers, but do not invent file paths.
OUTPUT: pure JSON only (no extra commentary). If you output markdown fences, they will be ignored.

Allowed target files (must match one of these exactly):
{allowed_list}

Feature title:
{feature_title}

Feature description:
{feature_description.strip()}

Code context:
{context_dump}

OUTPUT FORMAT:
{{
  "subtasks": [
    {{
      "title": "...",
      "description": "...",
      "target_files": ["..."],
      "acceptance_criteria": "...",
      "estimated_lines": 50
    }}
  ]
}}
Ensure each subtask has a testable acceptance criteria and references
the allowed files listed above.
""".strip()
    return prompt, allowed_paths


def build_repair_prompt(
    previous_json: str,
    errors: Sequence[str],
    allowed_paths: Sequence[str],
) -> str:
    """Prompt the model to repair the JSON by listing validation errors."""
    allowed_list = "\n".join(f"- {path}" for path in allowed_paths) or "- (none)"
    errors_text = "\n".join(f"- {error}" for error in errors) or "- (unknown error)"
    return f"""
The previous JSON output had validation issues:
{errors_text}
Please return corrected JSON only (no markdown, no explanation).
Allowed target files:
{allowed_list}

Previous JSON:
{previous_json}
""".strip()


def parse_decompose_result(raw: str) -> tuple[dict[str, object] | None, str | None]:
    """Extract JSON object from the model output."""
    candidate = raw.strip()
    if candidate.startswith("{"):
        try:
            return json.loads(candidate), candidate
        except json.JSONDecodeError:
            pass
    fence_match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence_match:
        snippet = fence_match.group(1)
        try:
            return json.loads(snippet), snippet
        except json.JSONDecodeError:
            return None, snippet
    return None, None


def validate_plan(
    plan: dict[str, object],
    allowed_paths: Iterable[str],
) -> tuple[list[str], list[dict[str, object]]]:
    """Validate structure and return normalized subtasks plus errors."""
    errors: list[str] = []
    normalized: list[dict[str, object]] = []
    allowed_set = set(allowed_paths)
    subtasks = plan.get("subtasks")
    if not isinstance(subtasks, list):
        errors.append("subtasks must be a list of objects.")
        return errors, normalized
    if len(subtasks) < 3 or len(subtasks) > 6:
        errors.append("subtasks list must contain between 3 and 6 items.")
    file_counter: Counter[str] = Counter()
    for idx, raw in enumerate(subtasks, start=1):
        if not isinstance(raw, dict):
            errors.append(f"subtask {idx} must be an object.")
            continue
        title = str(raw.get("title") or "").strip()
        description = str(raw.get("description") or "").strip()
        acceptance = str(raw.get("acceptance_criteria") or "").strip()
        target_files = raw.get("target_files") or []
        if not title:
            errors.append(f"subtask {idx} missing title.")
        if not description:
            errors.append(f"subtask {idx} missing description.")
        if not acceptance:
            errors.append(f"subtask {idx} missing acceptance criteria.")
        if isinstance(target_files, str):
            target_files = [target_files]
        if not isinstance(target_files, list):
            errors.append(f"subtask {idx} target_files must be a list.")
            continue
        normalized_files: list[str] = []
        for path in target_files:
            if not isinstance(path, str):
                continue
            candidate = path.strip()
            if candidate:
                normalized_files.append(candidate)
        if not normalized_files:
            errors.append(f"subtask {idx} must reference at least one target file.")
            continue
        if len(normalized_files) > 3:
            errors.append(f"subtask {idx} targets more than 3 files.")
        unknown = [path for path in normalized_files if path not in allowed_set]
        if unknown:
            errors.append(
                f"subtask {idx} references unauthorized files: {', '.join(unknown)}."
            )
        for path in normalized_files:
            file_counter[path] += 1
        if not any(word in acceptance.lower() for word in ACCEPTANCE_KEYWORDS):
            errors.append(
                f"subtask {idx} acceptance criteria should mention tests, responses, "
                "migrations, or lint."
            )
        try:
            estimated_lines = int(raw.get("estimated_lines") or 0)
        except (ValueError, TypeError):
            estimated_lines = 0
        normalized.append(
            {
                "title": title,
                "description": description,
                "acceptance_criteria": acceptance,
                "target_files": normalized_files,
                "estimated_lines": max(0, estimated_lines),
            }
        )
    for path, count in file_counter.items():
        if count >= 3:
            errors.append(f"file {path} appears in {count} subtasks; spread the work more.")
    if errors:
        return errors, []
    return errors, normalized


def compute_run_hash(
    feature_id: str, feature_description: str, context_files: Iterable[ContextFile]
) -> str:
    digest = sha256()
    digest.update(feature_id.encode("utf-8"))
    digest.update(feature_description.encode("utf-8"))
    for file in sorted(context_files, key=lambda cf: cf.path):
        digest.update(file.path.encode("utf-8"))
        digest.update(file.content.encode("utf-8"))
    return digest.hexdigest()


def context_reasons(context_files: Iterable[ContextFile]) -> dict[str, str]:
    return {file.path: file.reason for file in context_files}
