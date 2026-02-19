from pathlib import Path

import pytest

from jarvis.channels.whatsapp.media_security import (
    MediaSecurityError,
    media_filename,
    parse_csv_set,
    resolve_media_output_path,
    validate_media_mime,
    validate_media_url,
)


def test_validate_media_url_rejects_non_https() -> None:
    with pytest.raises(MediaSecurityError) as exc:
        validate_media_url("http://cdn.example/file.png", set())
    assert exc.value.reason == "media_url_invalid"


def test_validate_media_url_enforces_host_allowlist() -> None:
    with pytest.raises(MediaSecurityError) as exc:
        validate_media_url("https://bad.example/file.png", {"cdn.example"})
    assert exc.value.reason == "media_host_denied"


def test_validate_media_mime_enforces_prefixes() -> None:
    with pytest.raises(MediaSecurityError) as exc:
        validate_media_mime("application/zip", {"audio/", "image/"})
    assert exc.value.reason == "media_mime_denied"


def test_resolve_media_output_path_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(MediaSecurityError) as exc:
        resolve_media_output_path(tmp_path, "../escape.txt")
    assert exc.value.reason == "media_path_unsafe"


def test_media_filename_is_sanitized() -> None:
    name = media_filename("msg:bad/id", "audio", "audio/ogg")
    assert name.endswith(".ogg")
    assert ":" not in name
    assert "/" not in name


def test_parse_csv_set_lowercases_and_strips() -> None:
    parsed = parse_csv_set(" Foo, BAR ,,baz ")
    assert parsed == {"foo", "bar", "baz"}

