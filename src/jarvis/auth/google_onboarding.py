"""Google OAuth onboarding flow for Jarvis web setup."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

from jarvis.config import get_settings

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)
_FLOW_TTL = timedelta(minutes=15)
_PLACEHOLDER_VALUES = {
    "",
    "client-id",
    "client-secret",
    "refresh-token",
    "your-client-id",
    "your-client-secret",
}


@dataclass
class PendingFlow:
    verifier: str
    client_id: str
    client_secret: str
    redirect_uri: str
    created_at: datetime
    status: str = "pending"
    detail: str = ""


_flows: dict[str, PendingFlow] = {}
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def _clean_expired_flows() -> None:
    cutoff = _now() - _FLOW_TTL
    expired = [state for state, flow in _flows.items() if flow.created_at < cutoff]
    for state in expired:
        _flows.pop(state, None)


def _base64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


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


def _extract_client_id_from_gemini_oauth_creds() -> str | None:
    creds_path = Path.home() / ".gemini" / "oauth_creds.json"
    if not creds_path.exists():
        return None
    try:
        payload = json.loads(creds_path.read_text())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    id_token = payload.get("id_token")
    if not isinstance(id_token, str) or "." not in id_token:
        return None
    parts = id_token.split(".")
    if len(parts) < 2:
        return None
    encoded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
        claims = json.loads(decoded)
    except Exception:
        return None
    if not isinstance(claims, dict):
        return None
    for key in ("azp", "aud"):
        value = claims.get(key)
        if isinstance(value, str) and value.endswith(".apps.googleusercontent.com"):
            return value
    return None


def _extract_refresh_token_from_gemini_oauth_creds() -> str | None:
    creds_path = Path.home() / ".gemini" / "oauth_creds.json"
    if not creds_path.exists():
        return None
    try:
        payload = json.loads(creds_path.read_text())
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    token = payload.get("refresh_token")
    if not isinstance(token, str):
        return None
    token = token.strip()
    return token or None


def _extract_gemini_cli_credentials() -> tuple[str, str] | None:
    gemini_bin = _which("gemini")
    if gemini_bin is None:
        return None

    base = gemini_bin.parent.parent
    candidates = [
        base
        / "node_modules"
        / "@google"
        / "gemini-cli-core"
        / "dist"
        / "src"
        / "code_assist"
        / "oauth2.js",
        base
        / "node_modules"
        / "@google"
        / "gemini-cli-core"
        / "dist"
        / "code_assist"
        / "oauth2.js",
    ]
    for path in candidates:
        if not path.exists():
            continue
        content = path.read_text(errors="ignore")
        client_id = _find_regex(content, r"(\d+-[a-z0-9]+\.apps\.googleusercontent\.com)")
        client_secret = _find_regex(content, r"(GOCSPX-[A-Za-z0-9_-]+)")
        if client_id and client_secret:
            return client_id, client_secret
    found = _find_file(base, "oauth2.js", depth=10)
    if found is not None:
        content = found.read_text(errors="ignore")
        client_id = _find_regex(content, r"(\d+-[a-z0-9]+\.apps\.googleusercontent\.com)")
        client_secret = _find_regex(content, r"(GOCSPX-[A-Za-z0-9_-]+)")
        if client_id and client_secret:
            return client_id, client_secret
    fallback_client_id = _extract_client_id_from_gemini_oauth_creds()
    if fallback_client_id:
        return fallback_client_id, ""
    return None


def _which(binary: str) -> Path | None:
    path_env = Path("/nonexistent")
    import os

    raw = os.environ.get("PATH", "")
    for segment in raw.split(":"):
        if not segment:
            continue
        path_env = Path(segment) / binary
        if path_env.exists():
            return path_env.resolve()
    return None


def _find_regex(content: str, pattern: str) -> str | None:
    match = re.search(pattern, content)
    if not match:
        return None
    return match.group(1)


def _find_file(root: Path, name: str, depth: int) -> Path | None:
    if depth <= 0 or not root.exists() or not root.is_dir():
        return None
    try:
        for item in root.iterdir():
            if item.is_file() and item.name == name:
                return item
            if item.is_dir() and not item.name.startswith("."):
                found = _find_file(item, name, depth - 1)
                if found is not None:
                    return found
    except Exception:
        return None
    return None


def create_google_flow(
    *,
    redirect_uri: str,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> dict[str, str]:
    settings = get_settings()
    requested_client_id = (client_id or "").strip()
    requested_client_secret = (client_secret or "").strip()
    env_client_id = settings.google_oauth_client_id.strip()
    env_client_secret = settings.google_oauth_client_secret.strip()

    resolved_client_id = requested_client_id or (
        "" if env_client_id.lower() in _PLACEHOLDER_VALUES else env_client_id
    )
    resolved_client_secret = requested_client_secret or (
        "" if env_client_secret.lower() in _PLACEHOLDER_VALUES else env_client_secret
    )
    source = "env"
    if not resolved_client_id or not resolved_client_secret:
        extracted = _extract_gemini_cli_credentials()
        if extracted is not None:
            resolved_client_id, resolved_client_secret = extracted
            source = "gemini-cli"
    if not resolved_client_id or not resolved_client_secret:
        raise RuntimeError("missing Google OAuth client credentials")

    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = _base64url_sha256(verifier)
    query = urlencode(
        {
            "client_id": resolved_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    with _lock:
        _clean_expired_flows()
        _flows[state] = PendingFlow(
            verifier=verifier,
            client_id=resolved_client_id,
            client_secret=resolved_client_secret,
            redirect_uri=redirect_uri,
            created_at=_now(),
        )
    return {
        "state": state,
        "auth_url": f"{_AUTH_URL}?{query}",
        "redirect_uri": redirect_uri,
        "client_id_source": source,
    }


async def complete_google_flow(*, state: str, code: str) -> None:
    with _lock:
        _clean_expired_flows()
        flow = _flows.get(state)
        if flow is None:
            raise RuntimeError("oauth state is missing or expired")
        flow.status = "pending"
        flow.detail = "Exchanging code for tokens..."

    payload = {
        "client_id": flow.client_id,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": flow.redirect_uri,
        "code_verifier": flow.verifier,
    }
    if flow.client_secret:
        payload["client_secret"] = flow.client_secret
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(_TOKEN_URL, data=payload)
        if response.status_code >= 400 and flow.client_secret and "invalid_client" in response.text:
            retry_payload = dict(payload)
            retry_payload.pop("client_secret", None)
            response = await client.post(_TOKEN_URL, data=retry_payload)
    if response.status_code >= 400:
        detail = response.text.strip()[:400] or response.reason_phrase
        with _lock:
            current = _flows.get(state)
            if current is not None:
                current.status = "error"
                current.detail = f"Token exchange failed: {detail}"
        raise RuntimeError(f"token exchange failed: {detail}")

    body = response.json()
    refresh_token = body.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        with _lock:
            current = _flows.get(state)
            if current is not None:
                current.status = "error"
                current.detail = "No refresh token returned. Retry and grant consent."
        raise RuntimeError("refresh token not returned")

    _save_env_values(
        {
            "GOOGLE_OAUTH_CLIENT_ID": flow.client_id,
            "GOOGLE_OAUTH_CLIENT_SECRET": flow.client_secret,
            "GOOGLE_OAUTH_REFRESH_TOKEN": refresh_token.strip(),
        }
    )
    with _lock:
        current = _flows.get(state)
        if current is not None:
            current.status = "success"
            current.detail = "Google OAuth credentials saved to .env. Restart API/worker."


def mark_google_flow_error(*, state: str, detail: str) -> None:
    with _lock:
        flow = _flows.get(state)
        if flow is not None:
            flow.status = "error"
            flow.detail = detail


def get_google_flow_status(state: str) -> dict[str, str]:
    with _lock:
        _clean_expired_flows()
        flow = _flows.get(state)
        if flow is None:
            return {"status": "missing", "detail": "No active flow for this state"}
        return {"status": flow.status, "detail": flow.detail}


def import_google_creds_from_local_gemini() -> dict[str, str]:
    refresh_token = _extract_refresh_token_from_gemini_oauth_creds()
    if not refresh_token:
        raise RuntimeError("no refresh_token found in ~/.gemini/oauth_creds.json")

    client_id = _extract_client_id_from_gemini_oauth_creds() or ""
    client_secret = ""
    extracted = _extract_gemini_cli_credentials()
    if extracted is not None:
        client_id = extracted[0] or client_id
        client_secret = extracted[1]
    if not client_id:
        raise RuntimeError("unable to determine Google OAuth client_id from local Gemini CLI")

    values = {
        "GOOGLE_OAUTH_CLIENT_ID": client_id,
        "GOOGLE_OAUTH_REFRESH_TOKEN": refresh_token,
    }
    if client_secret:
        values["GOOGLE_OAUTH_CLIENT_SECRET"] = client_secret
    _save_env_values(values)
    return {
        "ok": "true",
        "client_id": client_id,
        "has_client_secret": "true" if bool(client_secret) else "false",
    }
