"""Deterministic fallback splitter for broad feature requests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayerTemplate:
    layer: str
    title_prefix: str
    description: str
    acceptance: str
    target_files: tuple[str, ...]


_LAYER_TEMPLATES: dict[str, LayerTemplate] = {
    "web": LayerTemplate(
        layer="web",
        title_prefix="Web UI",
        description=(
            "Implement the web UI surface for this feature using existing "
            "style/theme patterns."
        ),
        acceptance=(
            "UI renders correctly in existing routes, follows theme styles, and adds/updates tests "
            "for affected UI behavior."
        ),
        target_files=(
            "web/src/App.tsx",
            "web/src/pages/chat/index.tsx",
            "web/src/styles.css",
        ),
    ),
    "api": LayerTemplate(
        layer="api",
        title_prefix="API",
        description="Add or update API endpoints/contracts needed to support this feature.",
        acceptance=(
            "API contract is implemented with auth/ownership checks and integration tests cover "
            "admin/non-admin behavior."
        ),
        target_files=(
            "src/jarvis/routes/api/bugs.py",
            "src/jarvis/services/feature_requests.py",
            "tests/integration/test_feature_requests_api.py",
        ),
    ),
    "db": LayerTemplate(
        layer="db",
        title_prefix="Data Model",
        description=(
            "Add schema/query changes required for this feature with "
            "append-only migration safety."
        ),
        acceptance=(
            "Migration is append-only, query layer updated, and migration/unit tests "
            "validate new persisted behavior."
        ),
        target_files=(
            "src/jarvis/db/migrations",
            "src/jarvis/db/queries.py",
            "tests/unit/test_db_queries.py",
        ),
    ),
    "skills": LayerTemplate(
        layer="skills",
        title_prefix="Skill Infrastructure",
        description=(
            "Implement skill persistence/runtime wiring and policy-safe tool "
            "exposure for this feature."
        ),
        acceptance=(
            "Skill APIs/runtime behavior are updated with allow+deny-path tests "
            "and no policy bypass regressions."
        ),
        target_files=(
            "src/jarvis/memory/skills.py",
            "src/jarvis/tools/runtime.py",
            "tests/unit/test_skills_service.py",
        ),
    ),
    "docs": LayerTemplate(
        layer="docs",
        title_prefix="Docs",
        description=(
            "Update operator and user-facing docs to reflect the implemented "
            "behavior and workflows."
        ),
        acceptance="Documentation is updated across affected guides and passes docs checks.",
        target_files=(
            "docs/architecture.md",
            "docs/configuration.md",
            "docs/web-admin-guide.md",
        ),
    ),
    "tests": LayerTemplate(
        layer="tests",
        title_prefix="Quality Gates",
        description="Add or adjust tests to verify end-to-end behavior and prevent regressions.",
        acceptance="Targeted unit/integration tests cover happy path and failure path scenarios.",
        target_files=(
            "tests/unit",
            "tests/integration",
            "tests/unit/test_feature_build_task.py",
        ),
    ),
}

_LAYER_HINTS: dict[str, tuple[str, ...]] = {
    "web": ("web", "ui", "frontend", "theme", "styles", "react", "vite"),
    "api": ("api", "endpoint", "route", "http", "webhook"),
    "db": ("db", "database", "sqlite", "migration", "schema", "persist"),
    "skills": ("skill", "skills", "tooling", "prompt", "agent bundle"),
    "docs": ("docs", "documentation", "runbook", "guide"),
    "tests": ("test", "tests", "coverage", "lint", "typecheck"),
}


def build_fallback_subtasks(
    *,
    feature_title: str,
    feature_description: str,
    layer_strict: bool = True,
) -> list[dict[str, object]]:
    """Build deterministic child subtasks when RLM decomposition fails."""
    del layer_strict  # deterministic splitter is one-layer-per-child by design.
    text = f"{feature_title}\n{feature_description}".lower()
    layers: list[str] = []
    for layer, hints in _LAYER_HINTS.items():
        if any(token in text for token in hints):
            layers.append(layer)
    if not layers:
        layers = ["web", "api", "skills"]
    for required in ("docs", "tests"):
        if required not in layers:
            layers.append(required)
        if len(layers) >= 3:
            break
    layers = layers[:6]
    subtasks: list[dict[str, object]] = []
    for idx, layer in enumerate(layers, start=1):
        template = _LAYER_TEMPLATES[layer]
        subtasks.append(
            {
                "title": f"{template.title_prefix}: {feature_title} ({idx}/{len(layers)})",
                "description": template.description,
                "acceptance_criteria": template.acceptance,
                "target_files": list(template.target_files),
                "estimated_lines": 80,
            }
        )
    return subtasks
