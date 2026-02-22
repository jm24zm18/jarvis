"""FastAPI dependencies for web session auth."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, status

from jarvis.auth.service import validate_token
from jarvis.db.connection import get_conn


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def extract_session_token(
    authorization: str | None,
    jarvis_session: str | None,
) -> str | None:
    bearer = _extract_bearer(authorization)
    if bearer:
        return bearer
    if jarvis_session:
        token = jarvis_session.strip()
        if token:
            return token
    return None


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    role: str
    scopes: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def has_scope(self, scope: str) -> bool:
        if "*" in self.scopes or scope in self.scopes:
            return True
        ns = scope.split(":")[0]
        return f"{ns}:*" in self.scopes


def require_auth(
    authorization: str | None = Header(default=None),
    jarvis_session: str | None = Cookie(default=None),
) -> UserContext:
    raw_token = extract_session_token(authorization, jarvis_session)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing session token",
        )
    with get_conn() as conn:
        auth_data = validate_token(conn, raw_token)
    if auth_data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    user_id, role, scopes = auth_data
    return UserContext(user_id=user_id, role=role, scopes=scopes)


def require_admin(ctx: UserContext = Depends(require_auth)) -> UserContext:  # noqa: B008
    if not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    return ctx


def require_scope(scope: str) -> Callable[[UserContext], UserContext]:
    """Dependency factory: requires the caller to hold the given CBAC scope."""
    def _dep(ctx: UserContext = Depends(require_auth)) -> UserContext:  # noqa: B008
        if not ctx.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"scope required: {scope}",
            )
        return ctx
    return _dep
