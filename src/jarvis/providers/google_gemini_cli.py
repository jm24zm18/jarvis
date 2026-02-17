"""Gemini provider that uses Code Assist consumer-path routing."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import platform
import random
import re
import secrets
import shutil
import string
import subprocess
import time
import urllib.parse
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from jarvis.db.connection import get_conn
from jarvis.events.models import EventInput
from jarvis.events.writer import emit_event, redact_payload
from jarvis.ids import new_id
from jarvis.providers._gemini_common import (
    build_request_body,
    parse_candidate_parts,
)
from jarvis.providers.base import ModelResponse

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_CODE_ASSIST_BASE = "https://cloudcode-pa.googleapis.com"
_LOAD_CODE_ASSIST_URL = f"{_CODE_ASSIST_BASE}/v1internal:loadCodeAssist"
_STREAM_GENERATE_URL = f"{_CODE_ASSIST_BASE}/v1internal:streamGenerateContent?alt=sse"
_REDIRECT_URI = "http://localhost:8085/oauth2callback"
_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)
_SCRIPT_VERSION = "jarvis-code-assist-1"
_DEFAULT_QUOTA_COOLDOWN_SECONDS = 60
_DEFAULT_PLAN_TIER = "free"
_CLOUDCODE_DOMAINS = {
    "cloudcode-pa.googleapis.com",
    "staging-cloudcode-pa.googleapis.com",
    "autopush-cloudcode-pa.googleapis.com",
}
_TIER_LIMITS: dict[str, tuple[int, int]] = {
    "free": (60, 1000),
    "pro": (120, 1500),
    "ultra": (120, 2000),
    "standard": (120, 1500),
    "enterprise": (120, 2000),
}

# Cache extracted credentials for the process lifetime.
_extracted_client_id: str | None = None
_extracted_client_secret: str | None = None
_detected_cli_version: str | None = None
_detected_node_version: str | None = None


def _find_cli_package_root() -> Path | None:
    """Locate the Gemini CLI npm package root from the binary on PATH."""
    binary = shutil.which("gemini")
    if binary is None:
        return None
    resolved = Path(binary).resolve()
    for parent in [resolved.parent, *resolved.parents]:
        pj = parent / "package.json"
        if pj.exists():
            try:
                data = json.loads(pj.read_text())
                if data.get("name") == "@google/gemini-cli" and (parent / "node_modules").is_dir():
                    return parent
            except (json.JSONDecodeError, OSError):
                pass
        candidate = parent / "lib" / "node_modules" / "@google" / "gemini-cli"
        if candidate.is_dir():
            return candidate
    return None


def _detect_cli_version() -> str:
    """Return the installed Gemini CLI version, with stable fallback."""
    global _detected_cli_version
    if _detected_cli_version is not None:
        return _detected_cli_version
    pkg_root = _find_cli_package_root()
    if pkg_root is not None:
        pkg_json = pkg_root / "package.json"
        if pkg_json.exists():
            try:
                payload = json.loads(pkg_json.read_text(encoding="utf-8"))
                version = str(payload.get("version", "")).strip()
                if version:
                    _detected_cli_version = version
                    return version
            except (json.JSONDecodeError, OSError):
                pass
    _detected_cli_version = _SCRIPT_VERSION
    return _detected_cli_version


def _detect_node_version() -> str | None:
    """Return local Node.js semver without leading v, if available."""
    global _detected_node_version
    if _detected_node_version is not None:
        return _detected_node_version
    if shutil.which("node") is None:
        return None
    try:
        completed = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1.5,
        )
        raw = (completed.stdout or completed.stderr or "").strip()
    except Exception:
        return None
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", raw)
    if not match:
        return None
    _detected_node_version = match.group(1)
    return _detected_node_version


def _build_user_agent(model: str) -> str:
    version = _detect_cli_version()
    return (
        f"GeminiCLI/{version}/{model} "
        f"({platform.system().lower()}; {platform.machine().lower()})"
    )


def _build_api_client_header() -> str:
    # Match the Node CLI transport path when Node is available.
    node_version = _detect_node_version()
    if node_version:
        return f"gl-node/{node_version}"
    return f"gl-python/{platform.python_version()}"


def _code_assist_headers(*, access_token: str, model: str, expect_json: bool) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": _build_user_agent(model),
        "x-goog-api-client": _build_api_client_header(),
    }
    if expect_json:
        headers["Accept"] = "application/json"
    return headers


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

    extracted = _extract_oauth_from_cli()
    if extracted:
        _extracted_client_id, _extracted_client_secret = extracted
        return _extracted_client_id, _extracted_client_secret

    env_id = os.environ.get("GEMINI_CLI_OAUTH_CLIENT_ID", "")
    env_secret = os.environ.get("GEMINI_CLI_OAUTH_CLIENT_SECRET", "")
    if env_id and env_secret:
        _extracted_client_id, _extracted_client_secret = env_id, env_secret
        return env_id, env_secret

    raise RuntimeError(
        "Gemini CLI OAuth client credentials were not found. "
        "Set GEMINI_CLI_OAUTH_CLIENT_ID and GEMINI_CLI_OAUTH_CLIENT_SECRET."
    )


def _platform_enum() -> str:
    sysname = platform.system().lower()
    machine = platform.machine().lower()
    if sysname == "linux":
        return "LINUX_ARM64" if ("aarch" in machine or "arm" in machine) else "LINUX_AMD64"
    if sysname == "darwin":
        return "DARWIN_ARM64" if "arm" in machine else "DARWIN_AMD64"
    if sysname == "windows":
        return "WINDOWS_AMD64"
    return "PLATFORM_UNSPECIFIED"


def _build_client_metadata() -> dict[str, Any]:
    return {
        "ideType": "GEMINI_CLI",
        "pluginType": "GEMINI",
        "platform": _platform_enum(),
        "pluginVersion": _SCRIPT_VERSION,
        "ideVersion": platform.python_version(),
        "ideName": "python",
        "updateChannel": "custom",
    }


def _generate_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return verifier, challenge


def _random_id(prefix: str = "") -> str:
    core = "".join(random.choices(string.ascii_lowercase + string.digits, k=24))
    return f"{prefix}{core}" if prefix else core


def _parse_callback_input(input_str: str, expected_state: str) -> dict[str, str]:
    value = (input_str or "").strip()
    if not value:
        raise RuntimeError("no input provided")

    try:
        parsed = urllib.parse.urlparse(value)
        qs = urllib.parse.parse_qs(parsed.query)
        code = (qs.get("code") or [""])[0]
        state = (qs.get("state") or [expected_state])[0]
        if not code:
            raise RuntimeError("missing 'code' parameter in URL")
        if not state:
            raise RuntimeError("missing 'state' parameter in URL")
        return {"code": code, "state": state}
    except Exception:
        return {"code": value, "state": expected_state}


class GeminiCodeAssistProvider:
    _quota_block_until_monotonic: float = 0.0
    _quota_block_reason: str = ""
    _request_timestamps_monotonic: deque[float] = deque()
    _daily_count_utc: int = 0
    _daily_count_date_utc: str = ""
    _last_refresh_attempt_at_utc: str = ""
    _last_refresh_status_global: str = ""

    def __init__(
        self,
        model: str,
        *,
        token_path: str = "",
        timeout_seconds: int = 120,
        quota_plan_tier: str = _DEFAULT_PLAN_TIER,
        requests_per_minute: int = 0,
        requests_per_day: int = 0,
        quota_cooldown_default_seconds: int = _DEFAULT_QUOTA_COOLDOWN_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self.token_path = token_path.strip()
        self.timeout_seconds = max(10, timeout_seconds)
        self.quota_plan_tier = self._normalize_plan_tier(quota_plan_tier)
        self.requests_per_minute_limit = max(0, int(requests_per_minute))
        self.requests_per_day_limit = max(0, int(requests_per_day))
        if self.requests_per_minute_limit <= 0 or self.requests_per_day_limit <= 0:
            default_rpm, default_rpd = self._plan_limits(self.quota_plan_tier)
            if self.requests_per_minute_limit <= 0:
                self.requests_per_minute_limit = default_rpm
            if self.requests_per_day_limit <= 0:
                self.requests_per_day_limit = default_rpd
        self.quota_cooldown_default_seconds = max(5, int(quota_cooldown_default_seconds))
        self._transport = transport
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0
        self._last_refresh_attempt_at: str = ""
        self._last_refresh_status: str = ""

    @staticmethod
    def _normalize_plan_tier(plan_tier: str) -> str:
        value = str(plan_tier or "").strip().lower()
        if value in _TIER_LIMITS:
            return value
        return _DEFAULT_PLAN_TIER

    @staticmethod
    def _plan_limits(plan_tier: str) -> tuple[int, int]:
        normalized = GeminiCodeAssistProvider._normalize_plan_tier(plan_tier)
        return _TIER_LIMITS[normalized]

    def _consume_local_quota(self) -> None:
        cls = type(self)
        now_mono = time.monotonic()
        while cls._request_timestamps_monotonic and (
            now_mono - cls._request_timestamps_monotonic[0]
        ) >= 60:
            cls._request_timestamps_monotonic.popleft()

        if self.requests_per_minute_limit > 0 and (
            len(cls._request_timestamps_monotonic) >= self.requests_per_minute_limit
        ):
            wait_seconds = max(1, int(60 - (now_mono - cls._request_timestamps_monotonic[0])))
            self._emit_provider_event(
                "provider.quota.local.minute",
                {
                    "quota_plan_tier": self.quota_plan_tier,
                    "requests_per_minute_limit": self.requests_per_minute_limit,
                    "retry_after_seconds": wait_seconds,
                },
            )
            logger.warning(
                "gemini local minute quota reached",
                extra={
                    "provider": "google_gemini_cli",
                    "quota_plan_tier": self.quota_plan_tier,
                    "requests_per_minute_limit": self.requests_per_minute_limit,
                    "retry_after_seconds": wait_seconds,
                },
            )
            raise RuntimeError(
                f"gemini local quota reached ({self.requests_per_minute_limit}/min, "
                f"tier={self.quota_plan_tier}); retry in {wait_seconds}s"
            )

        today_utc = datetime.now(UTC).date().isoformat()
        if cls._daily_count_date_utc != today_utc:
            cls._daily_count_date_utc = today_utc
            cls._daily_count_utc = 0
        if self.requests_per_day_limit > 0 and cls._daily_count_utc >= self.requests_per_day_limit:
            self._emit_provider_event(
                "provider.quota.local.day",
                {
                    "quota_plan_tier": self.quota_plan_tier,
                    "requests_per_day_limit": self.requests_per_day_limit,
                    "quota_day_utc": cls._daily_count_date_utc,
                },
            )
            logger.warning(
                "gemini local daily quota reached",
                extra={
                    "provider": "google_gemini_cli",
                    "quota_plan_tier": self.quota_plan_tier,
                    "requests_per_day_limit": self.requests_per_day_limit,
                    "quota_day_utc": cls._daily_count_date_utc,
                },
            )
            raise RuntimeError(
                f"gemini local daily quota reached ({self.requests_per_day_limit}/day, "
                f"tier={self.quota_plan_tier}); waiting for UTC day rollover"
            )

        cls._request_timestamps_monotonic.append(now_mono)
        cls._daily_count_utc += 1

    def _token_cache_path(self) -> Path:
        if self.token_path:
            return Path(self.token_path).expanduser()
        return Path.home() / ".config" / "gemini-cli-oauth" / "token.json"

    def _load_token_cache(self) -> dict[str, Any]:
        path = self._token_cache_path()
        if not path.exists():
            raise RuntimeError(
                f"gemini token cache not found at {path}; run `jarvis gemini-login`"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"failed to read gemini token cache: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("gemini token cache payload must be an object")
        return payload

    def _save_token_cache(self, payload: dict[str, Any]) -> None:
        path = self._token_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    async def _refresh_token(self, cache: dict[str, Any]) -> dict[str, Any]:
        refresh_token = str(cache.get("refresh_token", "")).strip()
        if not refresh_token:
            raise RuntimeError("gemini token cache missing refresh_token")

        started = time.perf_counter()
        self._last_refresh_attempt_at = datetime.now(UTC).isoformat()
        type(self)._last_refresh_attempt_at_utc = self._last_refresh_attempt_at
        self._emit_provider_event(
            "provider.auth.refresh.start",
            {
                "attempted_at_utc": self._last_refresh_attempt_at,
            },
        )
        client_id, client_secret = _get_client_credentials()
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            async with httpx.AsyncClient(timeout=20, transport=self._transport) as client:
                response = await client.post(_TOKEN_URL, data=payload)
        except Exception as exc:
            self._last_refresh_status = "refresh_network_error"
            type(self)._last_refresh_status_global = self._last_refresh_status
            self._emit_provider_event(
                "provider.auth.refresh.error",
                {
                    "kind": "refresh_network_error",
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "message_preview": str(exc)[:240],
                },
            )
            raise
        if response.status_code >= 400:
            status = int(response.status_code)
            body_preview = response.text[:500]
            if status == 400 and "invalid_grant" in body_preview.lower():
                self._last_refresh_status = "refresh_invalid_grant"
            elif status == 429:
                self._last_refresh_status = "refresh_rate_limited"
            else:
                self._last_refresh_status = "refresh_unknown"
            type(self)._last_refresh_status_global = self._last_refresh_status
            self._emit_provider_event(
                "provider.auth.refresh.error",
                {
                    "kind": self._last_refresh_status,
                    "status_code": status,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "detail_preview": body_preview[:240],
                },
            )
            raise RuntimeError(
                f"gemini token refresh failed {response.status_code}: {body_preview}"
            )

        body = response.json()
        access_token = body.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            self._last_refresh_status = "refresh_unknown"
            type(self)._last_refresh_status_global = self._last_refresh_status
            self._emit_provider_event(
                "provider.auth.refresh.error",
                {
                    "kind": "refresh_unknown",
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "detail_preview": "refresh response missing access_token",
                },
            )
            raise RuntimeError("gemini token refresh missing access_token")

        now = time.time()
        expires_in = int(body.get("expires_in", 3600))
        expires_at_ms = int((now + expires_in) * 1000) - (5 * 60 * 1000)
        cache["access_token"] = access_token
        cache["expires_at_ms"] = expires_at_ms
        self._save_token_cache(cache)
        self._access_token = access_token
        self._access_token_expires_at = now + max(1, expires_in - 60)
        self._last_refresh_status = "ok"
        type(self)._last_refresh_status_global = self._last_refresh_status
        self._emit_provider_event(
            "provider.auth.refresh.end",
            {
                "kind": "ok",
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "expires_in_seconds": int(expires_in),
            },
        )
        return cache

    async def _get_valid_cache(self) -> dict[str, Any]:
        now = time.time()
        if self._access_token and now < self._access_token_expires_at:
            cache = self._load_token_cache()
            expires_at_ms = int(cache.get("expires_at_ms", 0) or 0)
            self._emit_provider_event(
                "provider.auth.token_state",
                {
                    "token_cache_exists": True,
                    "has_access_token": bool(self._access_token),
                    "has_refresh_token": bool(str(cache.get("refresh_token", "")).strip()),
                    "seconds_to_expiry": max(0, int((expires_at_ms / 1000.0) - now)),
                    "refresh_attempted": False,
                },
            )
            return cache

        cache = self._load_token_cache()
        access_token = str(cache.get("access_token", "")).strip()
        expires_at_ms = int(cache.get("expires_at_ms", 0) or 0)
        seconds_to_expiry = max(0, int((expires_at_ms / 1000.0) - now))
        self._emit_provider_event(
            "provider.auth.token_state",
            {
                "token_cache_exists": True,
                "has_access_token": bool(access_token),
                "has_refresh_token": bool(str(cache.get("refresh_token", "")).strip()),
                "seconds_to_expiry": seconds_to_expiry,
                "refresh_attempted": seconds_to_expiry <= 60,
            },
        )
        if access_token and expires_at_ms > int((now + 60) * 1000):
            self._access_token = access_token
            self._access_token_expires_at = max(now + 1, (expires_at_ms / 1000.0) - 60)
            return cache

        return await self._refresh_token(cache)

    async def _bootstrap(self, access_token: str, existing_project: str | None) -> dict[str, Any]:
        headers = _code_assist_headers(
            access_token=access_token,
            model=self.model,
            expect_json=True,
        )
        body: dict[str, Any] = {"metadata": _build_client_metadata()}
        if existing_project:
            body["cloudaicompanionProject"] = existing_project

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.post(
                _LOAD_CODE_ASSIST_URL,
                headers=headers,
                content=json.dumps(body),
            )
        if response.status_code >= 400:
            detail = response.text[:500]
            self._raise_api_error("loadCodeAssist", response.status_code, detail)
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("gemini loadCodeAssist response is not an object")
        return payload

    @staticmethod
    def _extract_event_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        response_obj = payload.get("response")
        if isinstance(response_obj, dict):
            nested = response_obj.get("candidates")
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict):
                        candidates.append(item)
        direct = payload.get("candidates")
        if isinstance(direct, list):
            for item in direct:
                if isinstance(item, dict):
                    candidates.append(item)
        return candidates

    async def _stream_generate(
        self,
        *,
        request_id: str,
        access_token: str,
        cloudaicompanion_project: str,
        body: dict[str, Any],
    ) -> ModelResponse:
        headers = _code_assist_headers(
            access_token=access_token,
            model=self.model,
            expect_json=False,
        )
        request_body: dict[str, Any] = {
            "model": self.model,
            "project": cloudaicompanion_project,
            "user_prompt_id": _random_id("up_"),
            "request": body,
        }
        if isinstance(request_body["request"], dict):
            request_body["request"].setdefault("session_id", _random_id("s_"))

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        thought_text_parts: list[str] = []
        thought_parts: list[dict[str, Any]] = []
        chunk_count = 0
        started = time.perf_counter()
        self._emit_provider_event(
            "provider.request.start",
            {
                "request_id": request_id,
                "operation": "streamGenerateContent",
                "model": self.model,
                "timeout_seconds": self.timeout_seconds,
                "has_tools": bool(body.get("tools")),
                "message_count": len(body.get("contents", [])),
            },
        )

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "POST",
                    _STREAM_GENERATE_URL,
                    headers=headers,
                    content=json.dumps(request_body),
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                        self._raise_api_error("streamGenerateContent", response.status_code, detail)
                    async for raw in response.aiter_lines():
                        if not raw:
                            continue
                        line = raw.strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            break
                        chunk_count += 1
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(event, dict):
                            continue
                        for candidate in self._extract_event_candidates(event):
                            content = candidate.get("content")
                            if not isinstance(content, dict):
                                continue
                            (
                                chunk_text,
                                chunk_calls,
                                chunk_thought_text,
                                chunk_thought_parts,
                            ) = parse_candidate_parts(content.get("parts"))
                            text_parts.extend(chunk_text)
                            tool_calls.extend(chunk_calls)
                            thought_text_parts.extend(chunk_thought_text)
                            thought_parts.extend(chunk_thought_parts)
        except httpx.TimeoutException as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._emit_provider_event(
                "provider.request.timeout",
                {
                    "request_id": request_id,
                    "operation": "streamGenerateContent",
                    "duration_ms": duration_ms,
                    "timeout_seconds": self.timeout_seconds,
                },
            )
            self._emit_provider_event(
                "provider.error.classified",
                {
                    "request_id": request_id,
                    "operation": "streamGenerateContent",
                    "status_code": 0,
                    "kind": "timeout",
                    "retry_seconds": 0,
                    "has_validation_link": False,
                    "message_preview": "gemini Code Assist stream timed out",
                    "detail_preview": "",
                },
            )
            raise RuntimeError("gemini Code Assist stream timed out") from exc

        final_text = "".join(text_parts)
        self._emit_provider_event(
            "provider.request.end",
            {
                "request_id": request_id,
                "operation": "streamGenerateContent",
                "status_code": 200,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "stream_chunks": chunk_count,
                "text_chars": len(final_text),
                "tool_calls_count": len(tool_calls),
            },
        )
        return ModelResponse(
            text=final_text,
            tool_calls=tool_calls,
            reasoning_text="".join(thought_text_parts),
            reasoning_parts=thought_parts,
        )

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ModelResponse:
        request_id = _random_id("req_")
        now_mono = time.monotonic()
        if now_mono < self._quota_block_until_monotonic:
            self._emit_provider_event(
                "provider.quota.cooldown.active",
                {
                    "request_id": request_id,
                    "seconds_remaining": max(
                        0,
                        int(self._quota_block_until_monotonic - time.monotonic()),
                    ),
                    "reason": self._quota_block_reason,
                },
            )
            raise RuntimeError(self._quota_block_reason or "gemini quota temporarily exhausted")
        self._consume_local_quota()

        cache = await self._get_valid_cache()
        access_token = str(cache.get("access_token", "")).strip()
        if not access_token:
            raise RuntimeError("gemini token cache missing access_token")

        cloudaicompanion_project = str(cache.get("cloudaicompanion_project", "")).strip()
        if not cloudaicompanion_project:
            bootstrap = await self._bootstrap(access_token, None)
            project = bootstrap.get("cloudaicompanionProject")
            if not isinstance(project, str) or not project.strip():
                raise RuntimeError(
                    "loadCodeAssist did not return cloudaicompanionProject; "
                    "consumer-path entitlement may be unavailable"
                )
            cloudaicompanion_project = project.strip()
            cache["cloudaicompanion_project"] = cloudaicompanion_project
            current_tier = bootstrap.get("currentTier")
            if isinstance(current_tier, dict):
                cache["current_tier_id"] = current_tier.get("id")
                cache["current_tier_name"] = current_tier.get("name")
            self._save_token_cache(cache)

        body = build_request_body(messages, tools, temperature, max_tokens)
        return await self._stream_generate(
            request_id=request_id,
            access_token=access_token,
            cloudaicompanion_project=cloudaicompanion_project,
            body=body,
        )

    async def health_check(self) -> bool:
        if time.monotonic() < self._quota_block_until_monotonic:
            return False
        return self._token_cache_path().exists()

    @staticmethod
    def _parse_possible_json(text: str) -> dict[str, Any] | None:
        value = (text or "").strip()
        if not value:
            return None
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            first = value.find("{")
            last = value.rfind("}")
            if first >= 0 and last > first:
                snippet = value[first : last + 1]
                try:
                    parsed = json.loads(snippet)
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
            return None

    @staticmethod
    def _detail_by_type(details: list[dict[str, Any]], type_name: str) -> dict[str, Any] | None:
        target = f"type.googleapis.com/{type_name}"
        for item in details:
            if str(item.get("@type", "")).strip() == target:
                return item
        return None

    @staticmethod
    def _duration_to_seconds(token: str) -> int:
        value = str(token or "").strip().lower()
        if not value:
            return 0
        if simple := re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s)", value):
            amount = float(simple.group(1))
            unit = simple.group(2)
            if unit == "ms":
                return max(1, int(amount / 1000))
            return max(1, int(amount))

        total = 0.0
        for amount, unit in re.findall(r"(\d+(?:\.\d+)?)(h|m|s)", value):
            qty = float(amount)
            if unit == "h":
                total += qty * 3600
            elif unit == "m":
                total += qty * 60
            else:
                total += qty
        return int(total) if total > 0 else 0

    def _classify_google_api_error(self, status_code: int, detail: str) -> dict[str, Any]:
        payload = self._parse_possible_json(detail)
        code = status_code
        message = detail.strip()
        details: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            error_obj = payload.get("error")
            if isinstance(error_obj, dict):
                if isinstance(error_obj.get("code"), int):
                    code = int(error_obj["code"])
                msg = error_obj.get("message")
                if isinstance(msg, str) and msg.strip():
                    message = msg.strip()
                raw_details = error_obj.get("details")
                if isinstance(raw_details, list):
                    details = [d for d in raw_details if isinstance(d, dict)]

        lower_message = message.lower()
        if "timed out" in lower_message or "timeout" in lower_message:
            return {
                "kind": "timeout",
                "code": code,
                "message": message,
                "retry_seconds": 0,
                "validation_link": "",
            }
        error_info = self._detail_by_type(details, "google.rpc.ErrorInfo") or {}
        help_info = self._detail_by_type(details, "google.rpc.Help") or {}
        quota_failure = self._detail_by_type(details, "google.rpc.QuotaFailure") or {}
        retry_info = self._detail_by_type(details, "google.rpc.RetryInfo") or {}
        domain = str(error_info.get("domain", "")).strip().lower()
        reason = str(error_info.get("reason", "")).strip().upper()
        metadata = error_info.get("metadata")
        metadata_map = metadata if isinstance(metadata, dict) else {}

        links = help_info.get("links")
        validation_link = ""
        if isinstance(links, list):
            for item in links:
                if isinstance(item, dict):
                    url = item.get("url")
                    if isinstance(url, str) and url.strip():
                        validation_link = url.strip()
                        break
        if not validation_link:
            candidate = metadata_map.get("validation_link")
            if isinstance(candidate, str):
                validation_link = candidate.strip()

        retry_delay = retry_info.get("retryDelay")
        retry_seconds = (
            self._duration_to_seconds(str(retry_delay))
            if isinstance(retry_delay, str)
            else 0
        )
        if retry_seconds <= 0:
            retry_seconds = self._parse_reset_seconds(f"{message} {detail}")

        violations = quota_failure.get("violations")
        quota_ids: list[str] = []
        if isinstance(violations, list):
            for item in violations:
                if isinstance(item, dict):
                    qid = item.get("quotaId")
                    if isinstance(qid, str):
                        quota_ids.append(qid)
        quota_ids_lower = ",".join(quota_ids).lower()
        quota_limit = str(metadata_map.get("quota_limit", "")).lower()

        if (
            code == 403
            and reason == "VALIDATION_REQUIRED"
            and domain in _CLOUDCODE_DOMAINS
        ):
            return {
                "kind": "validation_required",
                "code": code,
                "message": message,
                "retry_seconds": retry_seconds,
                "validation_link": validation_link,
            }
        if code == 404:
            return {
                "kind": "model_not_found",
                "code": code,
                "message": message,
                "retry_seconds": retry_seconds,
                "validation_link": validation_link,
            }
        if code == 400 and (
            "request contains an invalid argument" in lower_message
            or "invalid argument" in lower_message
        ):
            return {
                "kind": "invalid_argument",
                "code": code,
                "message": message,
                "retry_seconds": retry_seconds,
                "validation_link": validation_link,
            }
        if code == 429:
            terminal = (
                reason == "QUOTA_EXHAUSTED"
                or "perday" in quota_ids_lower
                or "daily" in quota_ids_lower
            )
            retryable = (
                reason == "RATE_LIMIT_EXCEEDED"
                or "perminute" in quota_ids_lower
                or "perminute" in quota_limit
                or retry_seconds > 0
            )
            if terminal:
                return {
                    "kind": "quota_terminal",
                    "code": code,
                    "message": message,
                    "retry_seconds": retry_seconds,
                    "validation_link": validation_link,
                }
            if retryable:
                return {
                    "kind": "quota_retryable",
                    "code": code,
                    "message": message,
                    "retry_seconds": retry_seconds,
                    "validation_link": validation_link,
                }
            return {
                "kind": "quota_retryable",
                "code": code,
                "message": message,
                "retry_seconds": retry_seconds,
                "validation_link": validation_link,
            }
        if code in {401, 403}:
            return {
                "kind": "auth_or_permission",
                "code": code,
                "message": message,
                "retry_seconds": retry_seconds,
                "validation_link": validation_link,
            }
        return {
            "kind": "generic",
            "code": code,
            "message": message,
            "retry_seconds": retry_seconds,
            "validation_link": validation_link,
        }

    def _raise_api_error(self, operation: str, status_code: int, detail: str) -> None:
        request_id = _random_id("req_")
        classified = self._classify_google_api_error(status_code, detail)
        kind = str(classified.get("kind", "generic"))
        message = str(classified.get("message", detail))
        retry_seconds = int(classified.get("retry_seconds", 0) or 0)
        validation_link = str(classified.get("validation_link", "") or "").strip()
        self._emit_provider_event(
            "provider.error.classified",
            {
                "operation": operation,
                "request_id": request_id,
                "status_code": status_code,
                "kind": kind,
                "retry_seconds": retry_seconds,
                "has_validation_link": bool(validation_link),
                "message_preview": message[:240],
                "detail_preview": detail[:240],
            },
        )
        logger.warning(
            "gemini api error classified",
            extra={
                "provider": "google_gemini_cli",
                "operation": operation,
                "status_code": status_code,
                "classified_kind": kind,
                "retry_seconds": retry_seconds,
                "has_validation_link": bool(validation_link),
                "message_preview": message[:240],
                "detail_preview": detail[:240],
            },
        )

        if kind == "validation_required":
            link_note = f" ({validation_link})" if validation_link else ""
            raise RuntimeError(f"gemini validation required: {message}{link_note}")
        if kind == "model_not_found":
            raise RuntimeError(f"gemini model unavailable: {message}")
        if kind == "invalid_argument":
            raise RuntimeError(f"gemini invalid argument: {message}")
        if kind == "quota_terminal":
            self._maybe_set_quota_block(
                detail=detail,
                status_code=status_code,
                seconds_override=retry_seconds,
                terminal=True,
            )
            raise RuntimeError(f"gemini quota exhausted (terminal): {message}")
        if kind == "quota_retryable":
            self._maybe_set_quota_block(
                detail=detail,
                status_code=status_code,
                seconds_override=retry_seconds,
                terminal=False,
            )
            raise RuntimeError(f"gemini quota exceeded: {message}")
        if kind == "auth_or_permission":
            raise RuntimeError(f"gemini auth/permission error {status_code}: {message}")
        if kind == "timeout":
            raise RuntimeError(f"gemini timeout: {message}")
        raise RuntimeError(f"gemini {operation} failed {status_code}: {detail}")

    def _maybe_set_quota_block(
        self,
        detail: str,
        status_code: int,
        *,
        seconds_override: int = 0,
        terminal: bool = False,
    ) -> None:
        text = detail.lower()
        if (
            status_code != 429
            and "quota" not in text
            and "capacity" not in text
            and "429" not in text
        ):
            return
        seconds = max(0, int(seconds_override))
        if seconds <= 0:
            seconds = self._parse_reset_seconds(detail)
        if seconds <= 0:
            if terminal:
                seconds = max(300, self.quota_cooldown_default_seconds)
            else:
                seconds = self.quota_cooldown_default_seconds
        cls = type(self)
        cls._quota_block_until_monotonic = time.monotonic() + seconds
        reset_at = datetime.now(UTC).timestamp() + seconds
        reset_iso = datetime.fromtimestamp(reset_at, tz=UTC).isoformat()
        prefix = "gemini quota exhausted" if terminal else "gemini quota exceeded"
        cls._quota_block_reason = f"{prefix}; skipping primary until {reset_iso} UTC"
        self._emit_provider_event(
            "provider.quota.blocked",
            {
                "status_code": status_code,
                "terminal": terminal,
                "cooldown_seconds": seconds,
                "reset_utc": reset_iso,
                "reason": cls._quota_block_reason,
            },
        )
        logger.warning(
            "gemini quota cooldown set",
            extra={
                "provider": "google_gemini_cli",
                "status_code": status_code,
                "terminal": terminal,
                "cooldown_seconds": seconds,
                "reset_utc": reset_iso,
                "reason": cls._quota_block_reason,
            },
        )

    def _emit_provider_event(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            with get_conn() as conn:
                redacted = redact_payload(payload)
                emit_event(
                    conn,
                    EventInput(
                        trace_id=new_id("trc"),
                        span_id=new_id("spn"),
                        parent_span_id=None,
                        thread_id=None,
                        event_type=event_type,
                        component="providers.gemini",
                        actor_type="agent",
                        actor_id="main",
                        payload_json=json.dumps(payload),
                        payload_redacted_json=json.dumps(redacted),
                    ),
                )
        except Exception:
            logger.exception(
                "failed to emit gemini provider event",
                extra={"event_type": event_type},
            )

    @staticmethod
    def _parse_reset_seconds(detail: str) -> int:
        text = detail.lower()
        if retry_after := re.search(r"retry[-\s]*after[:=\s]+(\d+(?:\.\d+)?)", text):
            return max(1, int(float(retry_after.group(1))))
        if retry_delay := re.search(r'"retrydelay"\s*:\s*"([^"]+)"', text):
            return GeminiCodeAssistProvider._duration_to_seconds(retry_delay.group(1))
        if please_retry := re.search(r"please retry in\s+(\d+(?:\.\d+)?(?:ms|s))", text):
            return GeminiCodeAssistProvider._duration_to_seconds(please_retry.group(1))
        match = re.search(
            r"(?:reset after|retry in)\s+((?:\d+h)?(?:\d+m)?(?:\d+(?:\.\d+)?s)?)",
            text,
            re.I,
        )
        if not match:
            return 0
        return GeminiCodeAssistProvider._duration_to_seconds(match.group(1) or "")

    @classmethod
    def quota_status(cls) -> dict[str, object]:
        remaining = max(0, int(cls._quota_block_until_monotonic - time.monotonic()))
        return {
            "blocked": remaining > 0,
            "seconds_remaining": remaining,
            "reason": cls._quota_block_reason,
            "last_refresh_attempt_at": cls._last_refresh_attempt_at_utc,
            "last_refresh_status": cls._last_refresh_status_global,
        }


async def run_manual_login(token_path: Path) -> dict[str, str]:
    """Run manual OAuth+PKCE login and persist the Code Assist token cache."""
    if os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT_ID"):
        raise RuntimeError(
            "Unset GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_PROJECT_ID for consumer-path login"
        )

    client_id, client_secret = _get_client_credentials()
    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": _REDIRECT_URI,
            "scope": " ".join(_SCOPES),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    auth_url = f"{_AUTH_URL}?{query}"

    print("Open this URL in your browser, then paste the full redirect URL (or just code):")
    print(auth_url)
    pasted = input("Redirect URL (or code): ").strip()
    parsed = _parse_callback_input(pasted, state)
    if parsed.get("state") != state:
        raise RuntimeError("oauth state mismatch")

    payload: dict[str, str] = {
        "client_id": client_id,
        "code": parsed["code"],
        "grant_type": "authorization_code",
        "redirect_uri": _REDIRECT_URI,
        "code_verifier": verifier,
        "client_secret": client_secret,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(_TOKEN_URL, data=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"token exchange failed {response.status_code}: {response.text[:500]}")

    body = response.json()
    access_token = body.get("access_token")
    refresh_token = body.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("token exchange missing access_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError("token exchange missing refresh_token")

    expires_in = int(body.get("expires_in", 3600))
    expires_at_ms = int(time.time() * 1000) + (expires_in * 1000) - (5 * 60 * 1000)

    provider = GeminiCodeAssistProvider(model="gemini-2.5-flash", token_path=str(token_path))
    bootstrap = await provider._bootstrap(access_token, None)
    project = bootstrap.get("cloudaicompanionProject")
    if not isinstance(project, str) or not project.strip():
        raise RuntimeError(
            "loadCodeAssist did not return cloudaicompanionProject; "
            "consumer-path entitlement may be unavailable"
        )

    current_tier = bootstrap.get("currentTier")
    cache: dict[str, Any] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at_ms": expires_at_ms,
        "cloudaicompanion_project": project.strip(),
    }
    if isinstance(current_tier, dict):
        cache["current_tier_id"] = current_tier.get("id")
        cache["current_tier_name"] = current_tier.get("name")

    provider._save_token_cache(cache)
    return {
        "token_path": str(token_path),
        "cloudaicompanion_project": project.strip(),
    }
