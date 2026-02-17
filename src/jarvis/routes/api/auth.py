"""Web auth API routes."""

import asyncio
import json
import re
import shutil
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from jarvis.auth.dependencies import UserContext, _extract_bearer, require_admin, require_auth
from jarvis.auth.google_onboarding import (
    complete_google_flow,
    create_google_flow,
    get_google_flow_status,
    mark_google_flow_error,
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
from jarvis.providers.google_gemini_cli import GeminiCodeAssistProvider
from jarvis.tasks.system import enqueue_settings_reload

router = APIRouter(prefix="/auth", tags=["api-auth"])
_PLACEHOLDER_VALUES = {
    "",
    "client-id",
    "client-secret",
    "refresh-token",
    "your-client-id",
    "your-client-secret",
}
_ALLOWED_PRIMARY_PROVIDERS = {"gemini", "sglang"}
_GEMINI_CLI_MODEL_FILE_CANDIDATES = (
    "node_modules/@google/gemini-cli-core/dist/src/config/models.js",
    "node_modules/@google/gemini-cli-core/dist/config/models.js",
)
_GEMINI_MODEL_VERIFY_TTL_SECONDS = 300
_gemini_model_verify_cache: dict[str, tuple[float, dict[str, str]]] = {}


def _load_env(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text().splitlines()


def _save_env_values(values: dict[str, str]) -> None:
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


def _find_gemini_cli_models_js() -> Path | None:
    gemini_bin = shutil.which("gemini")
    if not gemini_bin:
        return None
    resolved = Path(gemini_bin).resolve()
    package_root = resolved.parent.parent
    for rel_path in _GEMINI_CLI_MODEL_FILE_CANDIDATES:
        candidate = package_root / rel_path
        if candidate.exists():
            return candidate
    return None


def _load_gemini_models_from_cli() -> list[str]:
    path = _find_gemini_cli_models_js()
    if path is None:
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    found = re.findall(r"'(gemini-[a-z0-9.\-]+)'", content)
    seen: set[str] = set()
    models: list[str] = []
    for model in found:
        if model.endswith("-"):
            continue
        if "embedding" in model:
            continue
        if model in seen:
            continue
        seen.add(model)
        models.append(model)
    return models


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


def _gemini_token_cache_fingerprint(path: Path) -> str:
    try:
        stat = path.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return "missing"


async def _verify_gemini_models_for_account(models: list[str]) -> dict[str, str]:
    settings = get_settings()
    token_path = Path(settings.gemini_code_assist_token_path).expanduser()
    if not token_path.exists():
        return {model: "missing_oauth" for model in models}
    timeout_seconds = min(max(15, int(settings.gemini_cli_timeout_seconds)), 45)
    cache_key = "|".join(
        [
            _gemini_token_cache_fingerprint(token_path),
            str(timeout_seconds),
            *models,
        ]
    )
    now_mono = time.monotonic()
    cached = _gemini_model_verify_cache.get(cache_key)
    if cached and (now_mono - cached[0]) < _GEMINI_MODEL_VERIFY_TTL_SECONDS:
        return cached[1]

    statuses: dict[str, str] = {}
    for model in models:
        provider = GeminiCodeAssistProvider(
            model=model,
            token_path=settings.gemini_code_assist_token_path,
            timeout_seconds=timeout_seconds,
            quota_plan_tier=settings.gemini_code_assist_plan_tier,
            requests_per_minute=settings.gemini_code_assist_requests_per_minute,
            requests_per_day=settings.gemini_code_assist_requests_per_day,
            quota_cooldown_default_seconds=settings.gemini_quota_cooldown_default_seconds,
        )
        try:
            _ = await provider.generate(
                [{"role": "user", "content": "Return OK."}],
                tools=[],
                temperature=0.0,
                max_tokens=8,
            )
            statuses[model] = "ok"
        except Exception as exc:  # noqa: BLE001
            detail = str(exc).lower()
            if "quota" in detail or "429" in detail:
                statuses[model] = "quota"
            elif (
                "not found" in detail
                or "permission" in detail
                or "unsupported" in detail
                or "invalid" in detail
                or "access" in detail
            ):
                statuses[model] = "unavailable"
            else:
                statuses[model] = "error"
    _gemini_model_verify_cache[cache_key] = (now_mono, statuses)
    return statuses


@router.post("/login")
def login(payload: dict[str, str]) -> dict[str, str]:
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
    with get_conn() as conn:
        user_id = ensure_user(conn, external_id)
        admin_count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE role='admin'"
        ).fetchone()
        admin_count = int(admin_count_row["n"]) if admin_count_row is not None else 0
        if admin_count == 0:
            conn.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))
        role_row = conn.execute("SELECT role FROM users WHERE id=? LIMIT 1", (user_id,)).fetchone()
        role = str(role_row["role"]) if role_row is not None else "user"
        session_id, token = create_session(conn, user_id, role)
    return {"token": token, "session_id": session_id, "user_id": user_id, "role": role}


@router.get("/me")
def me(ctx: UserContext = Depends(require_auth)) -> dict[str, str]:  # noqa: B008
    return {"user_id": ctx.user_id, "role": ctx.role}


@router.post("/logout")
def logout(
    ctx: UserContext = Depends(require_auth),  # noqa: B008
    authorization: str | None = Header(default=None),
) -> dict[str, bool]:
    del ctx
    raw = _extract_bearer(authorization)
    if raw:
        with get_conn() as conn:
            item = session_from_token(conn, raw)
            if item is not None:
                delete_session(conn, item[0])
            else:
                delete_session_by_token(conn, raw)
    return {"ok": True}


@router.get("/google/config")
def google_config(ctx: UserContext = Depends(require_auth)) -> dict[str, object]:  # noqa: B008
    del ctx
    settings = get_settings()
    token_path = Path(settings.gemini_code_assist_token_path).expanduser()
    client_id = settings.google_oauth_client_id.strip()
    client_secret = settings.google_oauth_client_secret.strip()
    has_real_client_id = bool(
        client_id
        and client_id.lower() not in _PLACEHOLDER_VALUES
    )
    has_real_client_secret = bool(
        client_secret
        and client_secret.lower() not in _PLACEHOLDER_VALUES
    )
    has_client_credentials = has_real_client_id and has_real_client_secret
    token_cache_exists = token_path.exists()
    configured = has_client_credentials and token_cache_exists

    has_refresh_token = False
    access_expires_at_ms = 0
    current_tier_id = ""
    current_tier_name = ""
    if token_cache_exists:
        try:
            payload = json.loads(token_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                has_refresh_token = bool(str(payload.get("refresh_token", "")).strip())
                access_expires_at_ms = int(payload.get("expires_at_ms", 0) or 0)
                current_tier_id = str(payload.get("current_tier_id", "") or "").strip()
                current_tier_name = str(payload.get("current_tier_name", "") or "").strip()
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            pass
    now_ms = int(time.time() * 1000)
    seconds_until_access_expiry = max(0, int((access_expires_at_ms - now_ms) / 1000))
    quota = GeminiCodeAssistProvider.quota_status()
    seconds_remaining_raw = quota.get("seconds_remaining")
    quota_block_seconds_remaining = (
        int(seconds_remaining_raw)
        if isinstance(seconds_remaining_raw, int | float | str)
        else 0
    )
    return {
        "configured": configured,
        "has_client_credentials": has_client_credentials,
        "token_cache_exists": token_cache_exists,
        "has_refresh_token": has_refresh_token,
        "auto_refresh_enabled": has_client_credentials and has_refresh_token,
        "access_expires_at_ms": access_expires_at_ms,
        "seconds_until_access_expiry": seconds_until_access_expiry,
        "token_seconds_to_expiry": seconds_until_access_expiry,
        "current_tier_id": current_tier_id,
        "current_tier_name": current_tier_name,
        "quota_blocked": bool(quota.get("blocked")),
        "quota_block_seconds_remaining": quota_block_seconds_remaining,
        "quota_block_reason": str(quota.get("reason", "") or ""),
        "last_refresh_attempt_at": str(quota.get("last_refresh_attempt_at", "") or ""),
        "last_refresh_status": str(quota.get("last_refresh_status", "") or ""),
    }


@router.post("/google/start")
def google_start(
    payload: dict[str, str],
    request: Request,
    ctx: UserContext = Depends(require_auth),  # noqa: B008
) -> dict[str, str]:
    del ctx
    redirect_uri = str(payload.get("redirect_uri", "")).strip()
    if not redirect_uri:
        redirect_uri = f"{request.base_url}api/v1/auth/google/callback"
    try:
        return create_google_flow(
            redirect_uri=redirect_uri,
            client_id=str(payload.get("client_id", "")).strip() or None,
            client_secret=str(payload.get("client_secret", "")).strip() or None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/google/status")
def google_status(state: str, ctx: UserContext = Depends(require_auth)) -> dict[str, str]:  # noqa: B008
    del ctx
    return get_google_flow_status(state)


@router.get("/providers/config")
def providers_config(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
) -> dict[str, object]:
    del ctx
    settings = get_settings()
    primary_provider = settings.primary_provider.strip().lower()
    if primary_provider not in _ALLOWED_PRIMARY_PROVIDERS:
        primary_provider = "gemini"
    return {
        "primary_provider": primary_provider,
        "gemini_model": settings.gemini_model,
        "sglang_model": settings.sglang_model,
        "available_primary_providers": sorted(_ALLOWED_PRIMARY_PROVIDERS),
    }


@router.get("/providers/models")
async def providers_models(
    ctx: UserContext = Depends(require_admin),  # noqa: B008
    verify_gemini: bool = True,
) -> dict[str, object]:
    del ctx
    settings = get_settings()
    sglang_models_task = asyncio.create_task(_load_sglang_models())
    gemini_models = _load_gemini_models_from_cli()
    sglang_models = await sglang_models_task
    if settings.gemini_model not in gemini_models:
        gemini_models = [settings.gemini_model, *gemini_models]
    if settings.sglang_model and settings.sglang_model not in sglang_models:
        sglang_models = [settings.sglang_model, *sglang_models]
    gemini_verification: dict[str, str] = {}
    gemini_verified_models: list[str] = []
    if verify_gemini and gemini_models:
        gemini_verification = await _verify_gemini_models_for_account(gemini_models)
        gemini_verified_models = [
            model for model in gemini_models if gemini_verification.get(model) == "ok"
        ]
    return {
        "gemini_models": gemini_models,
        "gemini_verified_models": gemini_verified_models,
        "gemini_verification": gemini_verification,
        "sglang_models": sglang_models,
        "gemini_source": "gemini-cli-core",
        "sglang_source": "sglang-/models",
    }


@router.post("/providers/config")
def update_providers_config(
    payload: dict[str, str],
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
    if "gemini_model" in payload:
        gemini_model = str(payload.get("gemini_model", "")).strip()
        if not gemini_model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="gemini_model is required",
            )
        updates["GEMINI_MODEL"] = gemini_model
    if "sglang_model" in payload:
        sglang_model = str(payload.get("sglang_model", "")).strip()
        if not sglang_model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sglang_model is required",
            )
        updates["SGLANG_MODEL"] = sglang_model

    if updates:
        _save_env_values(updates)
    runtime = _refresh_settings_runtime()
    settings = get_settings()
    primary_provider = settings.primary_provider.strip().lower()
    if primary_provider not in _ALLOWED_PRIMARY_PROVIDERS:
        primary_provider = "gemini"
    return {
        "ok": True,
        "updated": sorted(updates.keys()),
        "primary_provider": primary_provider,
        "gemini_model": settings.gemini_model,
        "sglang_model": settings.sglang_model,
        **runtime,
    }


@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(state: str = "", code: str = "", error: str = "") -> HTMLResponse:
    if not state:
        return HTMLResponse("<h3>Missing OAuth state.</h3>", status_code=400)
    if error:
        mark_google_flow_error(state=state, detail=f"OAuth error: {error}")
        return HTMLResponse(
            "<h3>Google OAuth failed.</h3><p>You can close this tab.</p>",
            status_code=400,
        )
    if not code:
        mark_google_flow_error(state=state, detail="OAuth callback missing code")
        return HTMLResponse("<h3>Google OAuth failed (missing code).</h3>", status_code=400)
    try:
        await complete_google_flow(state=state, code=code)
        _refresh_settings_runtime()
    except RuntimeError as exc:
        return HTMLResponse(
            f"<h3>Google OAuth failed.</h3><p>{str(exc)}</p><p>You can close this tab.</p>",
            status_code=400,
        )
    return HTMLResponse(
        "<h3>Google OAuth complete.</h3>"
        "<p>Credentials were saved to .env. Restart API and worker, then return to Jarvis.</p>"
    )
