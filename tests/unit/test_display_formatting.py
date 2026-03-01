from __future__ import annotations

from io import StringIO

from jarvis.formatting import (
    format_bytes_human,
    format_duration_human,
    format_int_human,
    format_percent,
    format_timestamp_human,
    supports_utf8,
    symbol,
)


def test_format_bytes_human() -> None:
    assert format_bytes_human(1024) == "1.0 KB"
    assert format_bytes_human(1_536) == "1.5 KB"


def test_format_duration_human() -> None:
    assert format_duration_human(59) == "59s"
    assert format_duration_human(61) == "1m 1s"
    assert format_duration_human(3660) == "1h 1m"


def test_format_int_and_percent() -> None:
    assert format_int_human(1024000) == "1,024,000"
    assert format_percent(95.4242) == "95.42%"


def test_format_timestamp_human_handles_iso() -> None:
    out = format_timestamp_human("2026-02-27T11:50:53Z")
    assert "2026" in out


def test_utf8_and_symbol_fallback() -> None:
    class _Stream(StringIO):
        encoding = "UTF-8"

    stream = _Stream()
    assert supports_utf8(stream) is True
    assert symbol("check", ascii_only=False) != symbol("check", ascii_only=True)
