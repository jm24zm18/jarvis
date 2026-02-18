#!/usr/bin/env python3
"""Resilient web dependency install with actionable diagnostics."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("NPM_CONFIG_CACHE", "/tmp/npm-cache")
    env.setdefault("XDG_CACHE_HOME", "/tmp/.cache")
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _classify_failure(output: str) -> tuple[str, list[str]]:
    text = output.lower()
    if "exit handler never called!" in text:
        return (
            "npm_internal_exit_handler",
            [
                "Clear npm cache: npm cache clean --force",
                "Retry with a clean cache dir: npm install --cache /tmp/npm-cache --prefer-offline=false",
                "If using a restricted shell/network, retry in a normal networked shell.",
            ],
        )
    if "enotfound" in text or "eai_again" in text or "name resolution" in text:
        return (
            "dns_or_network_resolution",
            [
                "Verify outbound DNS/network connectivity.",
                "Retry with explicit registry: npm install --registry https://registry.npmjs.org/",
            ],
        )
    if "econnreset" in text or "etimedout" in text or "network timeout" in text:
        return (
            "network_timeout_or_reset",
            [
                "Retry with a stable connection.",
                "Increase npm timeouts: npm config set fetch-retries 5 && npm config set fetch-timeout 120000",
            ],
        )
    if "connect eperm" in text or ("errno eperm" in text and "syscall connect" in text):
        return (
            "network_blocked_or_sandboxed",
            [
                "Retry in a non-restricted shell with outbound network access.",
                "Verify local firewall/sandbox settings allow npm registry traffic.",
            ],
        )
    if "eacces" in text or "permission denied" in text:
        return (
            "filesystem_permission",
            [
                "Fix ownership/permissions for the project and npm cache directories.",
                "Avoid sudo npm installs inside this repo.",
            ],
        )
    if "enospc" in text:
        return (
            "disk_full",
            [
                "Free disk space and retry.",
                "Clean npm cache and old build artifacts.",
            ],
        )
    if "enotempty" in text:
        return (
            "filesystem_conflict",
            [
                "Remove conflicting package folder and retry (example: rm -rf web/node_modules/chokidar).",
                "If conflicts persist, remove `web/node_modules` and rerun `make web-install`.",
            ],
        )
    if "log files were not written due to an error writing to the directory" in text:
        return (
            "npm_log_permission",
            [
                "Ensure npm cache/log directories are writable.",
                "Retry with temporary cache/log dirs in /tmp.",
            ],
        )
    return (
        "unknown",
        [
            "Inspect npm and wrapper logs for full stack traces.",
            "Retry with: cd web && npm install --verbose",
        ],
    )


def _extract_npm_debug_log(output: str) -> str | None:
    match = re.search(r"(/\S*-debug-0\.log)", output)
    if match:
        return match.group(1)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-dir", default="web")
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--log-path", default="/tmp/jarvis-web-install.log")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    web_dir = (project_root / args.web_dir).resolve()
    log_path = Path(args.log_path)
    attempts = max(1, args.attempts)

    if not web_dir.is_dir():
        print(f"web-install failed: web dir not found: {web_dir}", file=sys.stderr)
        return 2

    preflight = [
        ("node", ["node", "--version"]),
        ("npm", ["npm", "--version"]),
    ]
    for name, cmd in preflight:
        result = _run(cmd)
        if result.returncode != 0:
            print(
                f"web-install preflight failed: {name} unavailable on PATH. "
                f"Install Node.js + npm first.",
                file=sys.stderr,
            )
            return 2

    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    npm_cmd = ["npm", "install", "--no-audit", "--no-fund"]
    all_output: list[str] = []
    for attempt in range(1, attempts + 1):
        print(f"web-install: attempt {attempt}/{attempts}")
        result = _run(npm_cmd, cwd=web_dir)
        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        all_output.append(combined)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"=== attempt {attempt}/{attempts} ===\n")
            handle.write(combined)
            handle.write("\n")
        if result.returncode == 0:
            print("web-install ok: npm dependencies installed.")
            print(f"web-install log: {log_path}")
            return 0
        print(f"web-install attempt {attempt} failed with exit code {result.returncode}.")

    joined_output = "\n".join(all_output)
    category, hints = _classify_failure(joined_output)
    print(
        f"web-install failed after {attempts} attempts (category: {category}).",
        file=sys.stderr,
    )
    debug_log = _extract_npm_debug_log(joined_output)
    if debug_log:
        print(f"npm debug log: {debug_log}", file=sys.stderr)
    print(f"wrapper log: {log_path}", file=sys.stderr)
    print("Suggested remediation:", file=sys.stderr)
    for hint in hints:
        print(f"- {hint}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
