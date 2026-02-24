"""Web auth API routes."""

import os

import httpx
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status

from jarvis.auth.dependencies import (
    UserContext,
    extract_session_token,
    require_admin,
    require_auth,
)
from jarvis.auth.service import (
    create_session,
    delete_session,
    delete_session_by_token,
    session_from_token,
)
from jarvis.config import get_settings
from jarvis.db.connection import get_conn
from jarvis.db.queries import ensure_user
from jarvis.tasks.system import enqueue_settings_reload

router = APIRouter(prefix="/auth", tags=["api-auth"])
_ALLOWED_PRIMARY_PROVIDERS = {"openrouter", "sglang"}
_MAX_EXTERNAL_ID_LENGTH = 256


def _load_env(path: object) -> list[str]:
    from pathlib import Path

    p = path if isinstance(path, Path) else Path(str(path))
    if not p.exists():
        return []
    return p.read_text().splitlines()


def _save_env_values(values: dict[str, str]) -> None:
    from pathlib import Path

    env_path = Path(".env")
    lines = _load_env(env_path)
    updated: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            updated.append(line)
            continue
        key, _, _ = line.partition("=")
        key = key.strip()
        if key in values:
            if key in seen:
                continue
            updated.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            updated.append(line)
    for key, value in values.items():
        if key not in seen:
            updated.append(f"{key}={value}")
    env_path.write_text("\n".join(updated).rstrip() + "\n")


def _refresh_settings_runtime() -> dict[str, bool]:
    get_settings.cache_clear()
    _ = get_settings()
    return {"api_reloaded": True, "worker_reload_enqueued": enqueue_settings_reload()}


def _apply_runtime_env_values(values: dict[str, str]) -> None:
    for key, value in values.items():
        os.environ[key] = value


def _mask_secret(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    if len(raw) <= 8:
        return "*" * len(raw)
    return f"{raw[:6]}{'*' * max(4, len(raw) - 10)}{raw[-4:]}"


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


async def _load_sglang_models() -> list[str]:
    settings = get_settings()
    endpoint = f"{settings.sglang_base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(endpoint)
        if response.status_code >= 400:
            return []
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        rows = payload.get("data")
        if not isinstance(rows, list):
            return []
        models: list[str] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_id = row.get("id")
            if not isinstance(model_id, str):
                continue
            item = model_id.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            models.append(item)
        return sorted(models)
    except Exception:
        return []


@router.post("/login")
def login(payload: dict[str, str], request: Request, response: Response) -> dict[str, str]:
    settings = get_settings()
    setup_password = settings.web_auth_setup_password.strip()
    if not setup_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="web auth setup password is not configured",
        )

    password = str(payload.get("password", ""))
    if password != setup_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    external_id = str(payload.get("external_id", "web_admin")).strip() or "web_admin"
    if len(external_id) > _MAX_EXTERNAL_ID_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"external_id must be at most {_MAX_EXTERNAL_ID_LENGTH} characters",
        )
    with get_conn() as conn:
        user_id = ensure_user(conn, external_id)
        admin_count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND external_id != 'system:root'"
        ).fetchone()
        admin_count = int(admin_count_row["n"]) if admin_count_row is not None else 0
        if admin_count == 0:
            conn.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))
        role_row = conn.execute("SELECT role FROM users WHERE id=? LIMIT 1", (user_id,)).fetchone()
        role = str(role_row["role"]) if role_row is not None else "user"
        session_id, token = create_session(conn, user_id, role)
    ttl_hours = max(1, settings.web_auth_token_ttl_hours)
    response.set_cookie(
        key="jarvis_session",
        value=token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=ttl_hours * 3600,
        path="/",
    )
    return {"token": token, "session_id": session_id, "user_id": user_id, "role": role}


@router.get("/me")
def me(ctx: UserContext = Depends(require_auth)) -> dict[str, str]:  # noqa: B008
    return {"user_id": ctx.user_id, "role": ctx.role}


@router.post("/logout")
def logout(
    response: Response,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
    authorization: str | None = Header(default=None),
    jarvis_session: str | None = Cookie(default=None),
) -> dict[str, bool]:
    del ctx
    raw = extract_session_token(authorization, jarvis_session)
    if raw:
        with get_conn() as conn:
            item = session_from_token(conn, raw)
            if item is not None:
                delete_session(conn, item[0])
            else:
                delete_session_by_token(conn, raw)
    response.delete_cookie(key="jarvis_session", path="/")
    return {"ok": True}


@router.get("/providers/config")
def providers_config(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    settings = get_settings()
    primary_provider = settings.primary_provider.strip().lower()
    if primary_provider not in _ALLOWED_PRIMARY_PROVIDERS:
        primary_provider = "openrouter"
    openrouter_api_key = settings.openrouter_api_key.strip()
    return {
        "primary_provider": primary_provider,
        "openrouter_model": settings.openrouter_model,
        "sglang_model": settings.sglang_model,
        "openrouter_api_key_set": bool(openrouter_api_key),
        "openrouter_api_key_masked": _mask_secret(openrouter_api_key),
        "available_primary_providers": sorted(_ALLOWED_PRIMARY_PROVIDERS),
    }


@router.get("/providers/models")
async def providers_models(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    settings = get_settings()
    sglang_models = await _load_sglang_models()
    if settings.sglang_model and settings.sglang_model not in sglang_models:
        sglang_models = [settings.sglang_model, *sglang_models]
    return {
        "sglang_models": sglang_models,
        "sglang_source": "sglang-/models",
    }


@router.post("/providers/config")
def update_providers_config(
    payload: dict[str, object],
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    updates: dict[str, str] = {}
    if "primary_provider" in payload:
        primary_provider = str(payload.get("primary_provider", "")).strip().lower()
        if primary_provider not in _ALLOWED_PRIMARY_PROVIDERS:
            allowed = ", ".join(sorted(_ALLOWED_PRIMARY_PROVIDERS))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"primary_provider must be one of: {allowed}",
            )
        updates["PRIMARY_PROVIDER"] = primary_provider
    if "openrouter_model" in payload:
        openrouter_model = str(payload.get("openrouter_model", "")).strip()
        if not openrouter_model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="openrouter_model is required",
            )
        updates["OPENROUTER_MODEL"] = openrouter_model
    if "sglang_model" in payload:
        sglang_model = str(payload.get("sglang_model", "")).strip()
        if not sglang_model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sglang_model is required",
            )
        updates["SGLANG_MODEL"] = sglang_model
    clear_openrouter_api_key = _parse_bool(payload.get("clear_openrouter_api_key"))
    if clear_openrouter_api_key:
        updates["OPENROUTER_API_KEY"] = ""
    elif "openrouter_api_key" in payload:
        openrouter_api_key = str(payload.get("openrouter_api_key", "")).strip()
        if openrouter_api_key:
            updates["OPENROUTER_API_KEY"] = openrouter_api_key

    if updates:
        _save_env_values(updates)
        _apply_runtime_env_values(updates)
    runtime = _refresh_settings_runtime()
    settings = get_settings()
    primary_provider = settings.primary_provider.strip().lower()
    if primary_provider not in _ALLOWED_PRIMARY_PROVIDERS:
        primary_provider = "openrouter"
    openrouter_api_key = settings.openrouter_api_key.strip()
    return {
        "ok": True,
        "updated": sorted(updates.keys()),
        "primary_provider": primary_provider,
        "openrouter_model": settings.openrouter_model,
        "sglang_model": settings.sglang_model,
        "openrouter_api_key_set": bool(openrouter_api_key),
        "openrouter_api_key_masked": _mask_secret(openrouter_api_key),
        **runtime,
    }
