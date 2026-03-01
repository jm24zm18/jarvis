"""FastAPI dependencies for web session auth."""
from dataclasses import dataclass

from fastapi import Cookie, Header, HTTPException, status

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
    return UserContext(user_id=auth_data)
