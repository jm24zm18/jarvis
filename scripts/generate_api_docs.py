#!/usr/bin/env python3
"""Generate docs/api-reference.md from FastAPI OpenAPI."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from fastapi.routing import APIRoute

from jarvis.main import app

OUT_PATH = Path("docs/api-reference.md")


def _infer_auth(route: APIRoute) -> str:
    names: set[str] = set()
    for dep in route.dependant.dependencies:
        call = getattr(dep, "call", None)
        name = getattr(call, "__name__", "") if call is not None else ""
        if name:
            names.add(name)
    if "require_admin" in names:
        return "admin"
    if "require_auth" in names:
        return "auth"
    if route.path == "/ws":
        return "ws-token"
    return "public"


def _route_auth_index() -> dict[tuple[str, str], str]:
    index: dict[tuple[str, str], str] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        auth = _infer_auth(route)
        for method in route.methods or set():
            if method.upper() in {"HEAD", "OPTIONS"}:
                continue
            index[(route.path, method.lower())] = auth
    return index


def _request_summary(operation: dict[str, object]) -> str:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return "-"
    content = request_body.get("content")
    if not isinstance(content, dict) or not content:
        return "body"
    return ", ".join(sorted(str(item) for item in content.keys()))


def _response_summary(operation: dict[str, object]) -> str:
    responses = operation.get("responses")
    if not isinstance(responses, dict) or not responses:
        return "-"
    codes = sorted(str(code) for code in responses.keys())
    return ", ".join(codes)


def _iter_operations(paths: dict[str, object]) -> Iterable[tuple[str, str, dict[str, object]]]:
    for path in sorted(paths.keys()):
        methods = paths[path]
        if not isinstance(methods, dict):
            continue
        for method in sorted(methods.keys()):
            operation = methods[method]
            if not isinstance(operation, dict):
                continue
            yield path, method, operation


def render_api_reference() -> str:
    spec = app.openapi()
    auth_index = _route_auth_index()
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise RuntimeError("OpenAPI paths missing")

    lines: list[str] = []
    lines.append("# API Reference")
    lines.append("")
    lines.append("Generated from FastAPI OpenAPI via `scripts/generate_api_docs.py`.")
    lines.append("Regenerate with `make docs-generate`.")
    lines.append("")
    lines.append("Auth levels:")
    lines.append("- `public`: no bearer token required")
    lines.append("- `auth`: authenticated user token required")
    lines.append("- `admin`: authenticated admin token required")
    lines.append("- `ws-token`: token required in WebSocket query string")
    lines.append("")
    lines.append("| Method | Path | Auth | Operation ID | Request | Responses |")
    lines.append("| --- | --- | --- | --- | --- | --- |")

    for path, method, operation in _iter_operations(paths):
        auth = auth_index.get((path, method), "public")
        operation_id = str(operation.get("operationId", "-")).replace("|", "\\|")
        request = _request_summary(operation).replace("|", "\\|")
        responses = _response_summary(operation).replace("|", "\\|")
        lines.append(
            f"| `{method.upper()}` | `{path}` | `{auth}` | `{operation_id}` | `{request}` | `{responses}` |"
        )

    lines.append("")
    lines.append("## OpenAPI JSON")
    lines.append("")
    lines.append("- Runtime endpoint: `GET /openapi.json`")
    lines.append("- Human docs endpoint: `GET /docs`")
    lines.append("")

    # Keep one compact machine-readable block for debugging diffs.
    version = spec.get("info", {}).get("version", "") if isinstance(spec.get("info"), dict) else ""
    title = spec.get("info", {}).get("title", "") if isinstance(spec.get("info"), dict) else ""
    lines.append("## Spec Metadata")
    lines.append("")
    lines.append(f"- `title`: `{title}`")
    lines.append(f"- `version`: `{version}`")
    lines.append(f"- `path_count`: `{len(paths)}`")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps({"title": title, "version": version, "path_count": len(paths)}, indent=2))
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT_PATH), help="Output path")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_api_reference(), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
