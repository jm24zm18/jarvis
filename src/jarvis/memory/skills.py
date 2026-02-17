"""Reusable skills storage and retrieval."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from jarvis.ids import new_id


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    text = raw.lstrip()
    if not text.startswith("---\n"):
        return {}, raw.strip()
    lines = text.splitlines()
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}, raw.strip()

    metadata: dict[str, str] = {}
    for line in lines[1:end_idx]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    body = "\n".join(lines[end_idx + 1 :]).strip()
    return metadata, body


def _extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            if title:
                return title
    return fallback


def _coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _parse_manifest_text(raw: str) -> dict[str, object]:
    parsed: dict[str, object] = {}
    current_list: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_list is None:
                continue
            existing = parsed.get(current_list)
            if not isinstance(existing, list):
                existing = []
                parsed[current_list] = existing
            existing.append(stripped[2:].strip())
            continue
        current_list = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            parsed[key] = []
            current_list = key
        else:
            parsed[key] = value
    return parsed


class SkillsService:
    @staticmethod
    def _fts_query(text: str) -> str:
        tokens = [token.strip() for token in text.replace('"', " ").split() if token.strip()]
        if not tokens:
            return ""
        return " OR ".join(tokens[:8])

    @staticmethod
    def _normalize_scope(scope: str | None) -> str:
        clean = (scope or "global").strip()
        return clean or "global"

    @staticmethod
    def _scopes_for_query(scope: str | None) -> tuple[str, ...]:
        clean = SkillsService._normalize_scope(scope)
        if clean == "global":
            return ("global",)
        return (clean, "global")

    def put(
        self,
        conn: sqlite3.Connection,
        *,
        slug: str,
        title: str,
        content: str,
        scope: str = "global",
        owner_id: str | None = None,
        pinned: bool = False,
        source: str = "agent",
    ) -> dict[str, object]:
        clean_slug = slug.strip()
        clean_title = title.strip()
        clean_content = content.strip()
        clean_scope = self._normalize_scope(scope)
        clean_owner = owner_id.strip() if isinstance(owner_id, str) and owner_id.strip() else None
        clean_source = source.strip() if source.strip() else "agent"
        if clean_source not in {"seed", "agent"}:
            raise ValueError("source must be 'seed' or 'agent'")
        if not clean_slug:
            raise ValueError("slug is required")
        if not clean_title:
            raise ValueError("title is required")
        if not clean_content:
            raise ValueError("content is required")

        now = datetime.now(UTC).isoformat()
        existing = conn.execute(
            "SELECT id, version FROM skills WHERE slug=? AND scope=? LIMIT 1",
            (clean_slug, clean_scope),
        ).fetchone()
        if existing is None:
            skill_id = new_id("skl")
            version = 1
            conn.execute(
                (
                    "INSERT INTO skills("
                    "id, slug, title, content, scope, owner_id, pinned, version, source, "
                    "created_at, updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?)"
                ),
                (
                    skill_id,
                    clean_slug,
                    clean_title,
                    clean_content,
                    clean_scope,
                    clean_owner,
                    1 if pinned else 0,
                    version,
                    clean_source,
                    now,
                    now,
                ),
            )
        else:
            skill_id = str(existing["id"])
            version = int(existing["version"]) + 1
            conn.execute(
                (
                    "UPDATE skills "
                    "SET title=?, content=?, owner_id=?, pinned=?, source=?, "
                    "version=?, updated_at=? "
                    "WHERE id=?"
                ),
                (
                    clean_title,
                    clean_content,
                    clean_owner,
                    1 if pinned else 0,
                    clean_source,
                    version,
                    now,
                    skill_id,
                ),
            )
        conn.execute(
            (
                "INSERT OR REPLACE INTO skills_fts("
                "skill_id, slug, title, content, scope"
                ") VALUES(?,?,?,?,?)"
            ),
            (skill_id, clean_slug, clean_title, clean_content, clean_scope),
        )
        return {
            "id": skill_id,
            "slug": clean_slug,
            "scope": clean_scope,
            "version": version,
            "pinned": bool(pinned),
        }

    def get(
        self, conn: sqlite3.Connection, slug: str, scope: str = "global"
    ) -> dict[str, object] | None:
        clean_slug = slug.strip()
        if not clean_slug:
            return None
        scopes = self._scopes_for_query(scope)
        placeholders = ",".join("?" for _ in scopes)
        row = conn.execute(
            (
                "SELECT id, slug, title, content, scope, owner_id, pinned, version, "
                "source, package_version, manifest_json, installed_at, install_source, updated_at "
                "FROM skills WHERE slug=? AND scope IN ("
                f"{placeholders}"
                ") ORDER BY CASE WHEN scope=? THEN 0 ELSE 1 END, updated_at DESC LIMIT 1"
            ),
            (clean_slug, *scopes, self._normalize_scope(scope)),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "slug": str(row["slug"]),
            "title": str(row["title"]),
            "content": str(row["content"]),
            "scope": str(row["scope"]),
            "owner_id": str(row["owner_id"]) if row["owner_id"] is not None else None,
            "pinned": bool(int(row["pinned"])),
            "version": int(row["version"]),
            "source": str(row["source"]),
            "package_version": (
                str(row["package_version"]) if row["package_version"] is not None else None
            ),
            "manifest_json": (
                str(row["manifest_json"]) if row["manifest_json"] is not None else None
            ),
            "installed_at": (
                str(row["installed_at"]) if row["installed_at"] is not None else None
            ),
            "install_source": (
                str(row["install_source"]) if row["install_source"] is not None else None
            ),
            "updated_at": str(row["updated_at"]),
        }

    def list_skills(
        self,
        conn: sqlite3.Connection,
        *,
        scope: str | None = None,
        pinned_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        scopes = self._scopes_for_query(scope)
        placeholders = ",".join("?" for _ in scopes)
        pinned_clause = "AND pinned=1" if pinned_only else ""
        rows = conn.execute(
            (
                "SELECT slug, title, scope, pinned, version, source, updated_at "
                "FROM skills WHERE scope IN ("
                f"{placeholders}"
                f") {pinned_clause} "
                "ORDER BY pinned DESC, updated_at DESC LIMIT ?"
            ),
            (*scopes, max(1, min(limit, 200))),
        ).fetchall()
        return [
            {
                "slug": str(row["slug"]),
                "title": str(row["title"]),
                "scope": str(row["scope"]),
                "pinned": bool(int(row["pinned"])),
                "version": int(row["version"]),
                "source": str(row["source"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def search(
        self,
        conn: sqlite3.Connection,
        *,
        query: str,
        scope: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, object]]:
        clean_query = query.strip()
        if not clean_query:
            return []
        fts_query = self._fts_query(clean_query)
        scopes = self._scopes_for_query(scope)
        placeholders = ",".join("?" for _ in scopes)
        clean_scope = self._normalize_scope(scope)
        max_limit = max(1, min(limit, 50))
        try:
            rows = conn.execute(
                (
                    "SELECT s.slug, s.title, s.content, s.scope, s.pinned, s.version, "
                    "s.source, s.updated_at "
                    "FROM skills_fts sf "
                    "JOIN skills s ON s.id=sf.skill_id "
                    "WHERE skills_fts MATCH ? AND s.scope IN ("
                    f"{placeholders}"
                    ") "
                    "ORDER BY CASE WHEN s.scope=? THEN 0 ELSE 1 END, "
                    "bm25(skills_fts), s.updated_at DESC LIMIT ?"
                ),
                (fts_query, *scopes, clean_scope, max_limit),
            ).fetchall()
        except sqlite3.OperationalError:
            like = f"%{clean_query}%"
            rows = conn.execute(
                (
                    "SELECT slug, title, content, scope, pinned, version, source, updated_at "
                    "FROM skills WHERE scope IN ("
                    f"{placeholders}"
                    ") AND (slug LIKE ? OR title LIKE ? OR content LIKE ?) "
                    "ORDER BY CASE WHEN scope=? THEN 0 ELSE 1 END, updated_at DESC LIMIT ?"
                ),
                (*scopes, like, like, like, clean_scope, max_limit),
            ).fetchall()
        return [
            {
                "slug": str(row["slug"]),
                "title": str(row["title"]),
                "content": str(row["content"]),
                "scope": str(row["scope"]),
                "pinned": bool(int(row["pinned"])),
                "version": int(row["version"]),
                "source": str(row["source"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def get_pinned(
        self, conn: sqlite3.Connection, *, scope: str | None = None
    ) -> list[dict[str, object]]:
        scopes = self._scopes_for_query(scope)
        placeholders = ",".join("?" for _ in scopes)
        clean_scope = self._normalize_scope(scope)
        rows = conn.execute(
            (
                "SELECT slug, title, content, scope, pinned, version, source, updated_at "
                "FROM skills WHERE pinned=1 AND scope IN ("
                f"{placeholders}"
                ") ORDER BY CASE WHEN scope=? THEN 0 ELSE 1 END, updated_at DESC"
            ),
            (*scopes, clean_scope),
        ).fetchall()
        return [
            {
                "slug": str(row["slug"]),
                "title": str(row["title"]),
                "content": str(row["content"]),
                "scope": str(row["scope"]),
                "pinned": bool(int(row["pinned"])),
                "version": int(row["version"]),
                "source": str(row["source"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def delete(self, conn: sqlite3.Connection, slug: str, scope: str = "global") -> bool:
        clean_slug = slug.strip()
        clean_scope = self._normalize_scope(scope)
        row = conn.execute(
            "SELECT id FROM skills WHERE slug=? AND scope=? LIMIT 1",
            (clean_slug, clean_scope),
        ).fetchone()
        if row is None:
            return False
        skill_id = str(row["id"])
        conn.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        conn.execute("DELETE FROM skills_fts WHERE skill_id=?", (skill_id,))
        return True

    def sync_from_disk(
        self, conn: sqlite3.Connection, skills_dir: Path
    ) -> dict[str, int]:
        inserted = 0
        updated = 0
        skipped = 0
        if not skills_dir.exists():
            return {"inserted": 0, "updated": 0, "skipped": 0}

        for path in sorted(skills_dir.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            metadata, body = _parse_frontmatter(raw)
            slug = metadata.get("slug", path.stem).strip() or path.stem
            pinned_raw = metadata.get("pinned", "false").strip().lower()
            pinned = pinned_raw in {"1", "true", "yes", "on"}
            title = _extract_title(body, slug.replace("-", " ").title())
            existing = conn.execute(
                "SELECT title, content, pinned, source FROM skills WHERE slug=? AND scope='global'",
                (slug,),
            ).fetchone()
            if (
                existing is not None
                and str(existing["content"]) == body
                and str(existing["title"]) == title
                and int(existing["pinned"]) == (1 if pinned else 0)
                and str(existing["source"]) == "seed"
            ):
                skipped += 1
                continue
            previous_version = 0
            if existing is not None:
                version_row = conn.execute(
                    "SELECT version FROM skills WHERE slug=? AND scope='global'",
                    (slug,),
                ).fetchone()
                previous_version = int(version_row["version"]) if version_row is not None else 0
            result = self.put(
                conn,
                slug=slug,
                title=title,
                content=body,
                scope="global",
                owner_id=None,
                pinned=pinned,
                source="seed",
            )
            if existing is None:
                inserted += 1
            else:
                current_version = result.get("version")
                version_num = int(current_version) if isinstance(current_version, int | str) else 0
                if version_num > previous_version:
                    updated += 1
                else:
                    skipped += 1
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    def install_package(
        self,
        conn: sqlite3.Connection,
        *,
        package_path: str,
        scope: str = "global",
        actor_id: str = "system",
        install_source: str = "local",
    ) -> dict[str, object]:
        base = Path(package_path)
        if base.is_file():
            base = base.parent
        manifest_path = base / "manifest.yaml"
        if not manifest_path.is_file():
            raise ValueError("manifest.yaml not found")
        manifest = _parse_manifest_text(manifest_path.read_text(encoding="utf-8"))
        slug = str(manifest.get("slug", "")).strip()
        title = str(manifest.get("title", "")).strip()
        package_version = str(manifest.get("version", "")).strip()
        if not slug or not title or not package_version:
            raise ValueError("manifest requires slug, title, and version")

        files_raw = manifest.get("files", [])
        files: list[str] = []
        if isinstance(files_raw, list):
            files = [str(item).strip() for item in files_raw if str(item).strip()]
        if not files:
            default_skill = base / "SKILL.md"
            if default_skill.is_file():
                files = ["SKILL.md"]
            else:
                files = [path.name for path in sorted(base.glob("*.md"))]
        if not files:
            raise ValueError("package has no skill files")

        chunks: list[str] = []
        for rel in files:
            path = (base / rel).resolve()
            if not path.is_file():
                raise ValueError(f"missing package file: {rel}")
            try:
                path.relative_to(base.resolve())
            except ValueError:
                raise ValueError(f"invalid package file path: {rel}") from None
            chunks.append(path.read_text(encoding="utf-8").strip())
        content = "\n\n".join(chunk for chunk in chunks if chunk).strip()
        if not content:
            raise ValueError("package skill content is empty")

        existing = self.get(conn, slug=slug, scope=scope)
        from_version = (
            str(existing["package_version"])
            if isinstance(existing, dict) and existing.get("package_version") is not None
            else None
        )

        result = self.put(
            conn,
            slug=slug,
            title=title,
            content=content,
            scope=scope,
            pinned=_coerce_bool(manifest.get("pinned", False)),
            source="agent",
        )
        now = datetime.now(UTC).isoformat()
        conn.execute(
            (
                "UPDATE skills SET package_version=?, manifest_json=?, installed_at=?, "
                "install_source=? WHERE slug=? AND scope=?"
            ),
            (
                package_version,
                json.dumps(manifest),
                now,
                install_source,
                slug,
                self._normalize_scope(scope),
            ),
        )
        conn.execute(
            (
                "INSERT INTO skill_install_log("
                "id, skill_slug, action, from_version, to_version, source, actor_id, created_at"
                ") VALUES(?,?,?,?,?,?,?,?)"
            ),
            (
                new_id("skli"),
                slug,
                "install",
                from_version,
                package_version,
                install_source,
                actor_id,
                now,
            ),
        )

        required_tools_raw = manifest.get("tools_required", [])
        required_tools = (
            [str(item) for item in required_tools_raw if str(item).strip()]
            if isinstance(required_tools_raw, list)
            else []
        )
        allowed = {
            str(row["tool_name"])
            for row in conn.execute(
                "SELECT DISTINCT tool_name FROM tool_permissions WHERE effect='allow'"
            ).fetchall()
        }
        missing_tools = [tool for tool in required_tools if tool not in allowed]
        warnings = (
            [f"required tools missing from permissions: {', '.join(sorted(missing_tools))}"]
            if missing_tools
            else []
        )
        return {
            **result,
            "package_version": package_version,
            "manifest": manifest,
            "warnings": warnings,
        }

    def check_updates(
        self, conn: sqlite3.Connection, *, scope: str | None = None
    ) -> list[dict[str, object]]:
        scopes = self._scopes_for_query(scope)
        placeholders = ",".join("?" for _ in scopes)
        rows = conn.execute(
            (
                "SELECT slug, scope, package_version, manifest_json, updated_at "
                "FROM skills WHERE package_version IS NOT NULL AND scope IN ("
                f"{placeholders}"
                ") ORDER BY updated_at DESC"
            ),
            (*scopes,),
        ).fetchall()
        items: list[dict[str, object]] = []
        for row in rows:
            manifest_json = row["manifest_json"]
            manifest: dict[str, object] | None = None
            if isinstance(manifest_json, str) and manifest_json.strip():
                try:
                    decoded = json.loads(manifest_json)
                    if isinstance(decoded, dict):
                        manifest = decoded
                except json.JSONDecodeError:
                    manifest = None
            items.append(
                {
                    "slug": str(row["slug"]),
                    "scope": str(row["scope"]),
                    "installed_version": str(row["package_version"]),
                    "manifest": manifest,
                    "update_available": False,
                    "checked_at": datetime.now(UTC).isoformat(),
                }
            )
        return items

    def get_install_history(
        self, conn: sqlite3.Connection, *, slug: str, limit: int = 50
    ) -> list[dict[str, object]]:
        rows = conn.execute(
            (
                "SELECT action, from_version, to_version, source, actor_id, created_at "
                "FROM skill_install_log WHERE skill_slug=? "
                "ORDER BY created_at DESC LIMIT ?"
            ),
            (slug.strip(), max(1, min(limit, 200))),
        ).fetchall()
        return [
            {
                "action": str(row["action"]),
                "from_version": (
                    str(row["from_version"]) if row["from_version"] is not None else None
                ),
                "to_version": str(row["to_version"]) if row["to_version"] is not None else None,
                "source": str(row["source"]),
                "actor_id": str(row["actor_id"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
