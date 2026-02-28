"""Human-display formatting helpers for CLI and other text surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TextIO

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def _parse_timestamp(value: str | datetime) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def format_timestamp_human(value: str | datetime) -> str:
    """Format an ISO timestamp or datetime for concise human display."""
    dt = _parse_timestamp(value)
    if dt is None:
        return str(value)
    local = dt.astimezone()
    day = str(local.day)
    return f"{local.strftime('%b')} {day}, {local.strftime('%Y %H:%M %Z')}"


def format_bytes_human(value: int | float) -> str:
    """Format byte counts with one decimal place for non-bytes."""
    size = float(value)
    unit_idx = 0
    while abs(size) >= 1024 and unit_idx < len(_UNITS) - 1:
        size /= 1024.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(round(size)):,} {_UNITS[unit_idx]}"
    return f"{size:.1f} {_UNITS[unit_idx]}"


def format_duration_human(seconds: float) -> str:
    """Format durations into compact, readable units."""
    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    days, hrs = divmod(hours, 24)
    return f"{days}d {hrs}h" if hrs else f"{days}d"


def format_percent(value: float, decimals: int = 2) -> str:
    return f"{value:.{max(0, int(decimals))}f}%"


def format_int_human(value: int) -> str:
    return f"{int(value):,}"


def supports_utf8(stream: TextIO | None) -> bool:
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return False
    return "utf" in encoding.lower()


def symbol(name: str, *, ascii_only: bool = False) -> str:
    utf8 = {
        "arrow": "->",
        "bullet": "•",
        "check": "✓",
        "cross": "✗",
        "skip": "⊘",
    }
    ascii_map = {
        "arrow": "->",
        "bullet": "*",
        "check": "[ok]",
        "cross": "[x]",
        "skip": "[-]",
    }
    mapping = ascii_map if ascii_only else utf8
    return mapping.get(name, name)
