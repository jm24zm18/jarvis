"""Web auth API routes."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from jarvis.auth.dependencies import UserContext, _extract_bearer, require_auth
from jarvis.auth.google_onboarding import (
    complete_google_flow,
    create_google_flow,
    get_google_flow_status,
    import_google_creds_from_local_gemini,
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


def _refresh_settings_runtime() -> dict[str, bool]:
    get_settings.cache_clear()
    _ = get_settings()
    return {"api_reloaded": True, "worker_reload_enqueued": enqueue_settings_reload()}


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
def me(ctx: UserContext = Depends(require_auth)) -> dict[str, str]:
    return {"user_id": ctx.user_id, "role": ctx.role}


@router.post("/logout")
def logout(
    ctx: UserContext = Depends(require_auth),
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
def google_config(ctx: UserContext = Depends(require_auth)) -> dict[str, object]:
    del ctx
    settings = get_settings()
    client_id = settings.google_oauth_client_id.strip()
    client_secret = settings.google_oauth_client_secret.strip()
    refresh_token = settings.google_oauth_refresh_token.strip()
    has_real_client = bool(
        client_id
        and client_secret
        and client_id.lower() not in _PLACEHOLDER_VALUES
        and client_secret.lower() not in _PLACEHOLDER_VALUES
    )
    has_real_refresh = bool(refresh_token and refresh_token.lower() not in _PLACEHOLDER_VALUES)
    configured = bool(
        has_real_client
        and has_real_refresh
    )
    return {"configured": configured, "has_client_credentials": has_real_client}


@router.post("/google/start")
def google_start(
    payload: dict[str, str],
    request: Request,
    ctx: UserContext = Depends(require_auth),
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
def google_status(state: str, ctx: UserContext = Depends(require_auth)) -> dict[str, str]:
    del ctx
    return get_google_flow_status(state)


@router.post("/google/import-local")
def google_import_local(ctx: UserContext = Depends(require_auth)) -> dict[str, str]:
    del ctx
    try:
        result = import_google_creds_from_local_gemini()
        runtime = _refresh_settings_runtime()
        return {
            **result,
            "api_reloaded": "true" if runtime["api_reloaded"] else "false",
            "worker_reload_enqueued": "true" if runtime["worker_reload_enqueued"] else "false",
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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
