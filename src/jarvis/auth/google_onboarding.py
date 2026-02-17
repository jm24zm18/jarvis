"""Google OAuth onboarding flow for Jarvis web setup."""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

from jarvis.config import get_settings

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CODE_ASSIST_BASE = "https://cloudcode-pa.googleapis.com"
_LOAD_CODE_ASSIST_URL = f"{_CODE_ASSIST_BASE}/v1internal:loadCodeAssist"
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


def _save_token_cache(path: Path, values: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=2), encoding="utf-8")


def _build_client_metadata() -> dict[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        platform_name = "LINUX_ARM64" if ("aarch" in machine or "arm" in machine) else "LINUX_AMD64"
    elif system == "darwin":
        platform_name = "DARWIN_ARM64" if "arm" in machine else "DARWIN_AMD64"
    elif system == "windows":
        platform_name = "WINDOWS_AMD64"
    else:
        platform_name = "PLATFORM_UNSPECIFIED"
    return {
        "ideType": "GEMINI_CLI",
        "pluginType": "GEMINI",
        "platform": platform_name,
        "pluginVersion": "jarvis-code-assist-1",
        "ideVersion": platform.python_version(),
        "ideName": "python",
        "updateChannel": "custom",
    }


async def _load_code_assist_bootstrap(
    *,
    access_token: str,
    timeout_seconds: int,
    existing_project: str | None = None,
) -> dict[str, object]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": (
            f"GeminiCLI/jarvis-code-assist-1 "
            f"({platform.system().lower()}; {platform.machine().lower()})"
        ),
        "x-goog-api-client": f"gl-python/{platform.python_version()}",
    }
    body: dict[str, object] = {"metadata": _build_client_metadata()}
    if existing_project:
        body["cloudaicompanionProject"] = existing_project
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            _LOAD_CODE_ASSIST_URL,
            headers=headers,
            content=json.dumps(body),
        )
    if response.status_code >= 400:
        detail = response.text.strip()[:400] or response.reason_phrase
        raise RuntimeError(f"loadCodeAssist failed: {detail}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("loadCodeAssist returned non-object response")
    return payload


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
    source = "request" if requested_client_id else "env"
    if not resolved_client_id or not resolved_client_secret:
        extracted = _extract_gemini_cli_credentials()
        if extracted is not None:
            extracted_client_id, extracted_client_secret = extracted
            if not resolved_client_id and extracted_client_id:
                resolved_client_id = extracted_client_id
                source = "gemini-cli"
            if (
                not resolved_client_secret
                and extracted_client_secret
                and resolved_client_id == extracted_client_id
            ):
                resolved_client_secret = extracted_client_secret
    elif not requested_client_secret:
        # Keep env-sourced client_id, but prefer a live Gemini CLI secret when it
        # matches the same OAuth client. This avoids stale secrets in .env.
        extracted = _extract_gemini_cli_credentials()
        if extracted is not None:
            extracted_client_id, extracted_client_secret = extracted
            if extracted_client_secret and resolved_client_id == extracted_client_id:
                resolved_client_secret = extracted_client_secret
    if not resolved_client_id:
        raise RuntimeError("missing Google OAuth client credentials")
    if not resolved_client_secret:
        raise RuntimeError(
            "missing Google OAuth client secret for selected client_id; "
            "set GOOGLE_OAUTH_CLIENT_SECRET (or provide client_secret) and retry"
        )

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
    settings = get_settings()
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
    if response.status_code >= 400:
        detail = response.text.strip()[:400] or response.reason_phrase
        with _lock:
            current = _flows.get(state)
            if current is not None:
                current.status = "error"
                current.detail = f"Token exchange failed: {detail}"
        raise RuntimeError(f"token exchange failed: {detail}")

    body = response.json()
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        with _lock:
            current = _flows.get(state)
            if current is not None:
                current.status = "error"
                current.detail = "No access token returned."
        raise RuntimeError("access token not returned")
    refresh_token = body.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        with _lock:
            current = _flows.get(state)
            if current is not None:
                current.status = "error"
                current.detail = "No refresh token returned. Retry and grant consent."
        raise RuntimeError("refresh token not returned")

    bootstrap = await _load_code_assist_bootstrap(
        access_token=access_token.strip(),
        timeout_seconds=max(10, int(settings.gemini_cli_timeout_seconds)),
    )
    cloudaicompanion_project = bootstrap.get("cloudaicompanionProject")
    if not isinstance(cloudaicompanion_project, str) or not cloudaicompanion_project.strip():
        with _lock:
            current = _flows.get(state)
            if current is not None:
                current.status = "error"
                current.detail = "loadCodeAssist did not return cloudaicompanionProject."
        raise RuntimeError("loadCodeAssist did not return cloudaicompanionProject")

    expires_in = int(body.get("expires_in", 3600))
    expires_at_ms = int(time.time() * 1000) + (expires_in * 1000) - (5 * 60 * 1000)
    current_tier = bootstrap.get("currentTier")
    token_cache: dict[str, object] = {
        "access_token": access_token.strip(),
        "refresh_token": refresh_token.strip(),
        "expires_at_ms": expires_at_ms,
        "cloudaicompanion_project": cloudaicompanion_project.strip(),
    }
    if isinstance(current_tier, dict):
        token_cache["current_tier_id"] = current_tier.get("id")
        token_cache["current_tier_name"] = current_tier.get("name")
    token_path = Path(settings.gemini_code_assist_token_path).expanduser()
    _save_token_cache(token_path, token_cache)

    env_values = {"GOOGLE_OAUTH_CLIENT_ID": flow.client_id}
    if flow.client_secret:
        env_values["GOOGLE_OAUTH_CLIENT_SECRET"] = flow.client_secret
    _save_env_values(env_values)
    with _lock:
        current = _flows.get(state)
        if current is not None:
            current.status = "success"
            current.detail = (
                "Google OAuth complete. Credentials saved and Code Assist token cache written. "
                "Restart API/worker."
            )


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
