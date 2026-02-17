#!/usr/bin/env python3
"""
gemini.py — Gemini CLI OAuth + Code Assist consumer-path inference

What this script does:
- Uses the same OAuth approach as Gemini CLI / OpenClaw google-gemini-cli-auth (PKCE, offline refresh token)
- BOOTSTRAPS via cloudcode-pa.googleapis.com v1internal:loadCodeAssist to obtain cloudaicompanionProject
  (this is required for the "consumer path" routing/quota/entitlement that Gemini CLI uses)
- Streams inference via v1internal:streamGenerateContent?alt=sse

Commands:
  python gemini.py login --manual
  python gemini.py infer --model gemini-2.5-flash --prompt "Say hi"

Important:
- For consumer path, do NOT set GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_PROJECT_ID.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import platform
import random
import re
import socketserver
import string
import sys
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

# --- OAuth endpoints ---
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo?alt=json"

# --- Code Assist endpoints (Gemini CLI backend) ---
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
CODE_ASSIST_VERSION = "v1internal"
LOAD_CODE_ASSIST_URL = f"{CODE_ASSIST_ENDPOINT}/{CODE_ASSIST_VERSION}:loadCodeAssist"
STREAM_URL = f"{CODE_ASSIST_ENDPOINT}/{CODE_ASSIST_VERSION}:streamGenerateContent?alt=sse"

# --- OAuth redirect (manual paste mode uses this redirect URL too) ---
REDIRECT_HOST = "localhost"
REDIRECT_PORT = 8085
REDIRECT_PATH = "/oauth2callback"
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}{REDIRECT_PATH}"

# IMPORTANT: Gemini CLI / Code Assist scopes only (do NOT add generative-language scopes)
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# Optional env overrides (same names OpenClaw checks)
ENV_CLIENT_ID_KEYS = ["OPENCLAW_GEMINI_OAUTH_CLIENT_ID", "GEMINI_CLI_OAUTH_CLIENT_ID"]
ENV_CLIENT_SECRET_KEYS = ["OPENCLAW_GEMINI_OAUTH_CLIENT_SECRET", "GEMINI_CLI_OAUTH_CLIENT_SECRET"]

# Token cache path
DEFAULT_STORE_DIR = Path.home() / ".config" / "gemini-cli-oauth"
DEFAULT_TOKEN_PATH = DEFAULT_STORE_DIR / "token.json"

SCRIPT_VERSION = "py-consumer-1.3"


@dataclass
class OAuthClientConfig:
    client_id: str
    client_secret: Optional[str] = None


@dataclass
class TokenCache:
    access_token: str
    refresh_token: str
    expires_at_ms: int
    email: Optional[str] = None

    # Required for consumer routing/quota/entitlement
    cloudaicompanion_project: Optional[str] = None

    # Optional debugging fields
    current_tier_id: Optional[str] = None
    current_tier_name: Optional[str] = None


# ---------------------------
# Utilities
# ---------------------------

def _resolve_env(keys: list[str]) -> Optional[str]:
    for k in keys:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return None


def _is_wsl2() -> bool:
    if platform.system().lower() != "linux":
        return False
    try:
        txt = Path("/proc/version").read_text(encoding="utf-8").lower()
        return ("wsl2" in txt) or ("microsoft-standard" in txt)
    except Exception:
        return False


def _find_in_path(exe: str) -> Optional[Path]:
    path = os.environ.get("PATH") or ""
    exts = [""] if os.name != "nt" else [".cmd", ".bat", ".exe", ""]
    for p in path.split(os.pathsep):
        p = p.strip()
        if not p:
            continue
        for ext in exts:
            candidate = Path(p) / f"{exe}{ext}"
            if candidate.exists():
                return candidate
    return None


def _find_file(root: Path, name: str, depth: int) -> Optional[Path]:
    if depth <= 0:
        return None
    try:
        for entry in root.iterdir():
            if entry.is_file() and entry.name == name:
                return entry
            if entry.is_dir() and not entry.name.startswith("."):
                found = _find_file(entry, name, depth - 1)
                if found:
                    return found
    except Exception:
        return None
    return None


def _rand_id(prefix: str = "") -> str:
    core = "".join(random.choices(string.ascii_lowercase + string.digits, k=24))
    return f"{prefix}{core}" if prefix else core


# ---------------------------
# OAuth client config extraction (OpenClaw-style)
# ---------------------------

def extract_gemini_cli_oauth2_config() -> Optional[OAuthClientConfig]:
    """
    Best-effort extraction of OAuth client_id/secret from installed `gemini` CLI
    by locating an oauth2.js file and regex extracting values (OpenClaw-style).
    """
    gemini = _find_in_path("gemini")
    if not gemini:
        return None

    try:
        resolved = gemini.resolve()
    except Exception:
        resolved = gemini

    # Similar to OpenClaw plugin: go up two directories from the executable
    gemini_cli_dir = resolved.parent.parent

    search_paths = [
        gemini_cli_dir / "node_modules" / "@google" / "gemini-cli-core" / "dist" / "src" / "code_assist" / "oauth2.js",
        gemini_cli_dir / "node_modules" / "@google" / "gemini-cli-core" / "dist" / "code_assist" / "oauth2.js",
    ]

    content: Optional[str] = None
    for p in search_paths:
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="ignore")
            break

    if content is None:
        found = _find_file(gemini_cli_dir, "oauth2.js", depth=10)
        if found and found.exists():
            content = found.read_text(encoding="utf-8", errors="ignore")

    if content is None:
        return None

    id_match = re.search(r"(\d+-[a-z0-9]+\.apps\.googleusercontent\.com)", content)
    secret_match = re.search(r"(GOCSPX-[A-Za-z0-9_-]+)", content)
    if not id_match or not secret_match:
        return None

    return OAuthClientConfig(client_id=id_match.group(1), client_secret=secret_match.group(1))


def resolve_oauth_client_config() -> OAuthClientConfig:
    env_id = _resolve_env(ENV_CLIENT_ID_KEYS)
    env_secret = _resolve_env(ENV_CLIENT_SECRET_KEYS)
    if env_id:
        return OAuthClientConfig(client_id=env_id, client_secret=env_secret or None)

    extracted = extract_gemini_cli_oauth2_config()
    if extracted:
        return extracted

    raise RuntimeError(
        "Could not find Gemini CLI OAuth client config.\n"
        "Install Gemini CLI (npm install -g @google/gemini-cli) OR set GEMINI_CLI_OAUTH_CLIENT_ID.\n"
        "Optionally set GEMINI_CLI_OAUTH_CLIENT_SECRET."
    )


# ---------------------------
# PKCE + OAuth flow
# ---------------------------

def generate_pkce() -> Tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return verifier, challenge


def build_auth_url(cfg: OAuthClientConfig, challenge: str, state: str) -> str:
    params = {
        "client_id": cfg.client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def parse_callback_input(input_str: str, expected_state: str) -> Dict[str, str]:
    s = (input_str or "").strip()
    if not s:
        raise RuntimeError("No input provided")

    try:
        url = urllib.parse.urlparse(s)
        qs = urllib.parse.parse_qs(url.query)
        code = (qs.get("code") or [None])[0]
        state = (qs.get("state") or [expected_state])[0]
        if not code:
            raise RuntimeError("Missing 'code' parameter in URL")
        if not state:
            raise RuntimeError("Missing 'state' parameter. Paste the full URL.")
        return {"code": code, "state": state}
    except Exception:
        # fallback: treat as raw code
        return {"code": s, "state": expected_state}


def exchange_code_for_tokens(cfg: OAuthClientConfig, code: str, verifier: str) -> Dict[str, Any]:
    body = {
        "client_id": cfg.client_id,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }
    if cfg.client_secret:
        body["client_secret"] = cfg.client_secret

    r = requests.post(TOKEN_URL, data=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Token exchange failed: HTTP {r.status_code} {r.text}")

    data = r.json()
    if not data.get("refresh_token"):
        raise RuntimeError("No refresh_token received. Try login again (ensure consent is shown).")
    return data


def refresh_access_token(cfg: OAuthClientConfig, refresh_token: str) -> Tuple[str, int]:
    body = {
        "client_id": cfg.client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if cfg.client_secret:
        body["client_secret"] = cfg.client_secret

    r = requests.post(TOKEN_URL, data=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Token refresh failed: HTTP {r.status_code} {r.text}")

    data = r.json()
    access = data.get("access_token")
    if not access:
        raise RuntimeError(f"Refresh response missing access_token: {data}")

    expires_in = int(data.get("expires_in", 3600))
    # refresh 5 minutes early
    expires_at_ms = int(time.time() * 1000) + expires_in * 1000 - 5 * 60 * 1000
    return access, expires_at_ms


def get_user_email(access_token: str) -> Optional[str]:
    try:
        r = requests.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
        if r.ok:
            return (r.json() or {}).get("email")
    except Exception:
        pass
    return None


# ---------------------------
# Token cache
# ---------------------------

def save_token_cache(path: Path, cache: TokenCache) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "access_token": cache.access_token,
                "refresh_token": cache.refresh_token,
                "expires_at_ms": cache.expires_at_ms,
                "email": cache.email,
                "cloudaicompanion_project": cache.cloudaicompanion_project,
                "current_tier_id": cache.current_tier_id,
                "current_tier_name": cache.current_tier_name,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def load_token_cache(path: Path) -> Optional[TokenCache]:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))

    access = data.get("access_token")
    refresh = data.get("refresh_token")
    expires_at_ms = int(data.get("expires_at_ms", 0))
    if not access or not refresh:
        raise RuntimeError(f"Token cache missing access/refresh fields: {path}")

    return TokenCache(
        access_token=str(access),
        refresh_token=str(refresh),
        expires_at_ms=expires_at_ms,
        email=data.get("email"),
        cloudaicompanion_project=data.get("cloudaicompanion_project"),
        current_tier_id=data.get("current_tier_id"),
        current_tier_name=data.get("current_tier_name"),
    )


def ensure_valid_access(cfg: OAuthClientConfig, cache: TokenCache, token_path: Path) -> TokenCache:
    now_ms = int(time.time() * 1000)
    if cache.expires_at_ms and now_ms < cache.expires_at_ms:
        return cache

    new_access, new_expires = refresh_access_token(cfg, cache.refresh_token)
    updated = TokenCache(
        access_token=new_access,
        refresh_token=cache.refresh_token,
        expires_at_ms=new_expires,
        email=cache.email,
        cloudaicompanion_project=cache.cloudaicompanion_project,
        current_tier_id=cache.current_tier_id,
        current_tier_name=cache.current_tier_name,
    )
    save_token_cache(token_path, updated)
    return updated


# ---------------------------
# Code Assist bootstrap + streaming inference
# ---------------------------

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


def build_client_metadata() -> Dict[str, Any]:
    return {
        "ideType": "GEMINI_CLI",
        "pluginType": "GEMINI",
        "platform": _platform_enum(),
        "pluginVersion": SCRIPT_VERSION,
        "ideVersion": platform.python_version(),
        "ideName": "python",
        "updateChannel": "custom",
    }


def load_code_assist_bootstrap(access_token: str, existing_project: Optional[str]) -> Dict[str, Any]:
    """
    Calls v1internal:loadCodeAssist.
    Even for "consumer path", Gemini CLI uses this to obtain cloudaicompanionProject for routing.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": f"GeminiCLI/{SCRIPT_VERSION} ({platform.system().lower()}; {platform.machine().lower()})",
        "x-goog-api-client": f"gl-python/{platform.python_version()}",
    }
    body: Dict[str, Any] = {"metadata": build_client_metadata()}
    if existing_project:
        body["cloudaicompanionProject"] = existing_project

    r = requests.post(LOAD_CODE_ASSIST_URL, headers=headers, json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"loadCodeAssist failed: HTTP {r.status_code} {r.text}")
    return r.json()


def call_code_assist_stream(
    access_token: str,
    model: str,
    prompt: str,
    cloudaicompanion_project: str,
    session_id: Optional[str] = None,
) -> str:
    """
    Streams response over SSE from v1internal:streamGenerateContent?alt=sse.

    Request shape is:
      {
        "model": "...",
        "project": "...",
        "user_prompt_id": "...",
        "request": {
          "contents": [...],
          "session_id": "..."
        }
      }
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": f"GeminiCLI/{SCRIPT_VERSION} ({platform.system().lower()}; {platform.machine().lower()})",
        "x-goog-api-client": f"gl-python/{platform.python_version()}",
    }

    if not session_id:
        session_id = _rand_id("s_")

    body: Dict[str, Any] = {
        "model": model,
        "project": cloudaicompanion_project,
        "user_prompt_id": _rand_id("up_"),
        "request": {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "session_id": session_id,
        },
    }

    r = requests.post(STREAM_URL, headers=headers, json=body, stream=True, timeout=120)
    if not r.ok:
        raise RuntimeError(f"streamGenerateContent failed: HTTP {r.status_code} {r.text}")

    out: list[str] = []
    for raw in r.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if data == "[DONE]":
            break
        try:
            evt = json.loads(data)
        except Exception:
            continue

        # Sometimes streamed chunks have "response": {...}, sometimes direct "candidates"
        candidates = (evt.get("response", {}) or {}).get("candidates") or evt.get("candidates") or []
        for cand in candidates:
            content = (cand or {}).get("content") or {}
            for part in (content.get("parts") or []):
                t = (part or {}).get("text")
                if t:
                    out.append(t)

    return "".join(out)


# ---------------------------
# CLI commands
# ---------------------------

def login_manual(token_path: Path) -> TokenCache:
    # Consumer path requirement: user must NOT force project via env vars
    if os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT_ID"):
        raise RuntimeError(
            "Unset GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_PROJECT_ID for consumer-path login:\n"
            "  unset GOOGLE_CLOUD_PROJECT GOOGLE_CLOUD_PROJECT_ID"
        )

    cfg = resolve_oauth_client_config()
    verifier, challenge = generate_pkce()
    auth_url = build_auth_url(cfg, challenge, state=verifier)

    print("\n== Gemini CLI OAuth (consumer path) ==\n")
    print("Open this URL in your LOCAL browser:\n")
    print(auth_url)
    print("\nAfter consenting, paste the FULL redirect URL here.\n")

    pasted = input("Redirect URL (or code): ").strip()
    parsed = parse_callback_input(pasted, verifier)
    if parsed["state"] != verifier:
        raise RuntimeError("OAuth state mismatch - try again")

    token_data = exchange_code_for_tokens(cfg, parsed["code"], verifier)

    access = token_data["access_token"]
    refresh = token_data["refresh_token"]
    expires_in = int(token_data.get("expires_in", 3600))
    expires_at_ms = int(time.time() * 1000) + expires_in * 1000 - 5 * 60 * 1000

    email = get_user_email(access)

    # Bootstrap: get cloudaicompanionProject for consumer routing
    lca = load_code_assist_bootstrap(access, None)
    cap = lca.get("cloudaicompanionProject")
    current_tier = lca.get("currentTier") or {}
    tier_id = current_tier.get("id")
    tier_name = current_tier.get("name")

    cache = TokenCache(
        access_token=access,
        refresh_token=refresh,
        expires_at_ms=expires_at_ms,
        email=email,
        cloudaicompanion_project=cap,
        current_tier_id=tier_id,
        current_tier_name=tier_name,
    )
    save_token_cache(token_path, cache)

    print("\nLogin complete.")
    if email:
        print(f"  Email:      {email}")
    print(f"  Token cache: {token_path}")
    print(f"  cloudaicompanionProject: {cap}")
    if tier_id:
        print(f"  Tier:       {tier_id} ({tier_name or 'n/a'})")

    return cache


def infer(token_path: Path, model: str, prompt: str) -> str:
    if os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT_ID"):
        raise RuntimeError(
            "Unset GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_PROJECT_ID for consumer-path infer:\n"
            "  unset GOOGLE_CLOUD_PROJECT GOOGLE_CLOUD_PROJECT_ID"
        )

    cfg = resolve_oauth_client_config()
    cache = load_token_cache(token_path)
    if not cache:
        raise RuntimeError(f"No token cache found at {token_path}. Run: python gemini.py login --manual")

    cache = ensure_valid_access(cfg, cache, token_path)

    # Ensure we have cloudaicompanionProject
    if not cache.cloudaicompanion_project:
        lca = load_code_assist_bootstrap(cache.access_token, None)
        cache.cloudaicompanion_project = lca.get("cloudaicompanionProject")
        current_tier = lca.get("currentTier") or {}
        cache.current_tier_id = current_tier.get("id")
        cache.current_tier_name = current_tier.get("name")
        save_token_cache(token_path, cache)

    if not cache.cloudaicompanion_project:
        raise RuntimeError(
            "loadCodeAssist did not return cloudaicompanionProject. "
            "Your account may be ineligible for the individual (consumer) tier."
        )

    return call_code_assist_stream(
        access_token=cache.access_token,
        model=model,
        prompt=prompt,
        cloudaicompanion_project=cache.cloudaicompanion_project,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_login = sub.add_parser("login", help="OAuth login (manual paste) + consumer bootstrap")
    ap_login.add_argument("--token-path", default=str(DEFAULT_TOKEN_PATH))
    ap_login.add_argument("--manual", action="store_true", help="kept for compatibility (login is manual anyway)")

    ap_infer = sub.add_parser("infer", help="Inference via Code Assist SSE (consumer path)")
    ap_infer.add_argument("--token-path", default=str(DEFAULT_TOKEN_PATH))
    ap_infer.add_argument("--model", default="gemini-2.5-flash")
    ap_infer.add_argument("--prompt", required=True)

    args = ap.parse_args()
    token_path = Path(args.token_path).expanduser()

    if args.cmd == "login":
        login_manual(token_path)
        return

    if args.cmd == "infer":
        text = infer(token_path, args.model, args.prompt)
        print(text)
        return


if __name__ == "__main__":
    main()

