"""FastAPI dependencies for web session auth."""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from jarvis.auth.service import validate_token
from jarvis.db.connection import get_conn


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


@dataclass(frozen=True, slots=True)
class UserContext:
    user_id: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def require_auth(authorization: str | None = Header(default=None)) -> UserContext:
    raw_token = _extract_bearer(authorization)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    with get_conn() as conn:
        auth_data = validate_token(conn, raw_token)
    if auth_data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    user_id, role = auth_data
    return UserContext(user_id=user_id, role=role)


def require_admin(ctx: UserContext = Depends(require_auth)) -> UserContext:  # noqa: B008
    if not ctx.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin required")
    return ctx
