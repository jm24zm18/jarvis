#!/usr/bin/env python3
"""Fail-fast host port preflight for local docker dependencies."""

from __future__ import annotations

import json
import re
import subprocess
import sys

REQUIRED_PORTS = (11434, 30000, 8080)


def _list_listening_ports() -> set[int]:
    ports: set[int] = set()
    cmd_variants = (
        ["ss", "-ltnH"],
        ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
    )
    output = ""
    for cmd in cmd_variants:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            continue
        if proc.returncode != 0:
            continue
        output = proc.stdout
        if output.strip():
            break
    if not output.strip():
        return ports

    for line in output.splitlines():
        for match in re.finditer(r":(\d+)\b", line):
            try:
                ports.add(int(match.group(1)))
            except ValueError:
                continue
    return ports


def _is_port_available(port: int, listening_ports: set[int]) -> bool:
    if port not in listening_ports:
        return True
    cmd = ["docker", "compose", "ps", "--format", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    if proc.returncode != 0:
        return False
    for line in proc.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        publishers = payload.get("Publishers")
        if not isinstance(publishers, list):
            continue
        for publisher in publishers:
            if not isinstance(publisher, dict):
                continue
            published = publisher.get("PublishedPort")
            if isinstance(published, int) and published == port:
                return True
    return False


def main() -> int:
    listening_ports = _list_listening_ports()
    conflicts = [
        port for port in REQUIRED_PORTS if not _is_port_available(port, listening_ports)
    ]
    if not conflicts:
        print("dev preflight ok: ports 11434, 30000, 8080 are available.")
        return 0

    ports = ", ".join(str(port) for port in conflicts)
    print(f"dev preflight failed: occupied host port(s): {ports}", file=sys.stderr)
    print("Resolve conflicts, then re-run `make dev`.", file=sys.stderr)
    print("Helpful checks:", file=sys.stderr)
    print(f"  lsof -nP -iTCP:{conflicts[0]} -sTCP:LISTEN", file=sys.stderr)
    print("  ss -ltnp | rg ':(11434|30000|8080)'", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
