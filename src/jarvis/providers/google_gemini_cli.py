"""Gemini provider that uses the Gemini CLI's OAuth credentials with the REST API.

Uses the CLI binary only for auth setup and health probing.  Actual inference
goes through the Gemini REST API so that native function/tool calling works.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from jarvis.providers._gemini_common import build_request_body, parse_response
from jarvis.providers.base import ModelResponse

logger = logging.getLogger(__name__)

# Cache extracted credentials for the process lifetime.
_extracted_client_id: str | None = None
_extracted_client_secret: str | None = None


def _find_cli_package_root() -> Path | None:
    """Locate the Gemini CLI npm package root from the binary on PATH."""
    binary = shutil.which("gemini")
    if binary is None:
        return None
    resolved = Path(binary).resolve()
    # Walk up to find a package.json with @google/gemini-cli
    for parent in [resolved.parent, *resolved.parents]:
        pj = parent / "package.json"
        if pj.exists():
            try:
                data = json.loads(pj.read_text())
                if data.get("name") == "@google/gemini-cli":
                    return parent
            except (json.JSONDecodeError, OSError):
                pass
        # Also check node_modules layout: binary is often in .bin,
        # the real package lives at lib/node_modules/@google/gemini-cli
        candidate = parent / "lib" / "node_modules" / "@google" / "gemini-cli"
        if candidate.is_dir():
            return candidate
    return None


def _extract_oauth_from_cli() -> tuple[str, str] | None:
    """Extract OAuth client_id/secret from the CLI's bundled oauth2.js."""
    pkg_root = _find_cli_package_root()
    if pkg_root is None:
        return None
    oauth_js = (
        pkg_root
        / "node_modules"
        / "@google"
        / "gemini-cli-core"
        / "dist"
        / "src"
        / "code_assist"
        / "oauth2.js"
    )
    if not oauth_js.exists():
        # Try alternate flat layout
        oauth_js = pkg_root / "dist" / "src" / "code_assist" / "oauth2.js"
    if not oauth_js.exists():
        return None
    try:
        content = oauth_js.read_text()
    except OSError:
        return None
    id_match = re.search(r'OAUTH_CLIENT_ID\s*=\s*["\']([^"\']+)["\']', content)
    secret_match = re.search(r'OAUTH_CLIENT_SECRET\s*=\s*["\']([^"\']+)["\']', content)
    if id_match and secret_match:
        return id_match.group(1), secret_match.group(1)
    return None


def _get_client_credentials() -> tuple[str, str]:
    """Get OAuth client_id and secret with fallback chain."""
    global _extracted_client_id, _extracted_client_secret
    if _extracted_client_id and _extracted_client_secret:
        return _extracted_client_id, _extracted_client_secret

    # 1. Try runtime extraction from CLI
    extracted = _extract_oauth_from_cli()
    if extracted:
        _extracted_client_id, _extracted_client_secret = extracted
        return _extracted_client_id, _extracted_client_secret

    # 2. Env var override
    env_id = os.environ.get("GEMINI_CLI_OAUTH_CLIENT_ID", "")
    env_secret = os.environ.get("GEMINI_CLI_OAUTH_CLIENT_SECRET", "")
    if env_id and env_secret:
        _extracted_client_id, _extracted_client_secret = env_id, env_secret
        return env_id, env_secret

    raise RuntimeError(
        "Gemini CLI OAuth client credentials were not found. "
        "Set GEMINI_CLI_OAUTH_CLIENT_ID and GEMINI_CLI_OAUTH_CLIENT_SECRET."
    )


class GoogleGeminiCliProvider:
    _quota_block_until_monotonic: float = 0.0
    _quota_block_reason: str = ""

    def __init__(
        self,
        model: str,
        *,
        binary: str = "gemini",
        home_dir: str = "",
        timeout_seconds: int = 120,
    ) -> None:
        self.model = model
        self.binary = binary
        self.home_dir = home_dir.strip()
        self.timeout_seconds = max(10, timeout_seconds)
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

    def _oauth_creds_path(self) -> Path:
        if self.home_dir:
            return Path(self.home_dir) / "oauth_creds.json"
        cli_home = os.environ.get("GEMINI_CLI_HOME_DIR", "")
        if cli_home:
            return Path(cli_home) / "oauth_creds.json"
        return Path.home() / ".gemini" / "oauth_creds.json"

    def _read_oauth_creds(self) -> dict[str, Any]:
        path = self._oauth_creds_path()
        if not path.exists():
            raise RuntimeError(
                f"gemini CLI oauth credentials not found at {path}; "
                "run `gemini` interactively once to set up OAuth"
            )
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"failed to read gemini CLI oauth creds: {exc}") from exc

    async def _get_access_token(self) -> str:
        """Get a valid access token, refreshing if expired."""
        now = time.time()
        if self._access_token and now < self._access_token_expires_at:
            return self._access_token

        creds = self._read_oauth_creds()
        access_token = creds.get("access_token", "")
        expiry_date = creds.get("expiry_date", 0)  # epoch ms

        # Check if existing token is still valid (with 60s buffer)
        if access_token and isinstance(expiry_date, (int, float)):
            expiry_seconds = expiry_date / 1000.0
            if now < expiry_seconds - 60:
                self._access_token = access_token
                self._access_token_expires_at = expiry_seconds - 60
                return access_token

        # Token expired — refresh it
        refresh_token = creds.get("refresh_token", "")
        if not refresh_token:
            raise RuntimeError("gemini CLI oauth creds missing refresh_token")

        client_id, client_secret = _get_client_credentials()
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token", data=payload
            )
            response.raise_for_status()
        body = response.json()
        new_token = body.get("access_token")
        if not isinstance(new_token, str) or not new_token:
            raise RuntimeError("gemini token refresh missing access_token")

        expires_in = int(body.get("expires_in", 3600))
        new_expiry_ms = int((now + expires_in) * 1000)

        # Write back to creds file so CLI stays in sync
        creds["access_token"] = new_token
        creds["expiry_date"] = new_expiry_ms
        try:
            creds_path = self._oauth_creds_path()
            creds_path.write_text(json.dumps(creds, indent=2))
        except OSError:
            logger.warning("failed to write refreshed token back to %s", self._oauth_creds_path())

        self._access_token = new_token
        self._access_token_expires_at = now + max(1, expires_in - 60)
        return new_token

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ModelResponse:
        now_mono = time.monotonic()
        if now_mono < self._quota_block_until_monotonic:
            raise RuntimeError(
                self._quota_block_reason or "gemini quota temporarily exhausted"
            )

        access_token = await self._get_access_token()
        body = build_request_body(messages, tools, temperature, max_tokens)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    url, headers=headers, content=json.dumps(body)
                )
        except httpx.TimeoutException as exc:
            raise RuntimeError("gemini REST API timed out") from exc

        if response.status_code == 429:
            detail = response.text[:500]
            self._maybe_set_quota_block(detail)
            raise RuntimeError(f"gemini quota exceeded: {detail}")

        if response.status_code >= 400:
            detail = response.text[:500]
            self._maybe_set_quota_block(detail)
            raise RuntimeError(f"gemini REST API error {response.status_code}: {detail}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("gemini response is not an object")
        return parse_response(payload)

    async def health_check(self) -> bool:
        if time.monotonic() < self._quota_block_until_monotonic:
            return False
        if shutil.which(self.binary) is None:
            return False
        oauth_path = self._oauth_creds_path()
        return oauth_path.exists()

    @classmethod
    def _maybe_set_quota_block(cls, detail: str) -> None:
        text = detail.lower()
        if "quota" not in text and "capacity" not in text and "429" not in text:
            return
        seconds = cls._parse_reset_seconds(detail)
        if seconds <= 0:
            seconds = 30 * 60
        cls._quota_block_until_monotonic = time.monotonic() + seconds
        reset_at = datetime.now(UTC).timestamp() + seconds
        reset_iso = datetime.fromtimestamp(reset_at, tz=UTC).isoformat()
        cls._quota_block_reason = (
            f"gemini quota exhausted; skipping primary until {reset_iso} UTC"
        )

    @staticmethod
    def _parse_reset_seconds(detail: str) -> int:
        match = re.search(
            r"reset after\s+((?:\d+h)?(?:\d+m)?(?:\d+s)?)", detail, re.I
        )
        if not match:
            return 0
        token = match.group(1) or ""
        hours_match = re.search(r"(\d+)h", token)
        mins_match = re.search(r"(\d+)m", token)
        secs_match = re.search(r"(\d+)s", token)
        hours = int(hours_match.group(1)) if hours_match else 0
        mins = int(mins_match.group(1)) if mins_match else 0
        secs = int(secs_match.group(1)) if secs_match else 0
        return (hours * 3600) + (mins * 60) + secs
