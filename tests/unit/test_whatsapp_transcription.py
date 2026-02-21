from pathlib import Path

import pytest

from jarvis.channels.whatsapp.transcription import (
    FasterWhisperTranscriber,
    StubVoiceTranscriber,
    VoiceTranscriptionError,
    build_voice_transcriber,
    transcribe_with_timeout,
)
from jarvis.config import Settings


@pytest.mark.asyncio
async def test_stub_transcriber_returns_deterministic_text(tmp_path: Path) -> None:
    file_path = tmp_path / "voice.ogg"
    file_path.write_bytes(b"voice")
    transcriber = StubVoiceTranscriber()
    transcript = await transcriber.transcribe(file_path=file_path, mime_type="audio/ogg")
    assert transcript == "[stub: transcription not configured]"


@pytest.mark.asyncio
async def test_stub_transcriber_errors_when_file_missing(tmp_path: Path) -> None:
    transcriber = StubVoiceTranscriber()
    with pytest.raises(VoiceTranscriptionError) as exc:
        await transcriber.transcribe(file_path=tmp_path / "missing.ogg", mime_type="audio/ogg")
    assert exc.value.reason == "voice_transcription_input_missing"


@pytest.mark.asyncio
async def test_transcribe_with_timeout_raises_for_zero_timeout(tmp_path: Path) -> None:
    file_path = tmp_path / "voice.ogg"
    file_path.write_bytes(b"voice")
    transcriber = StubVoiceTranscriber()
    with pytest.raises(VoiceTranscriptionError) as exc:
        await transcribe_with_timeout(
            transcriber=transcriber,
            file_path=file_path,
            mime_type="audio/ogg",
            timeout_seconds=0,
        )
    assert exc.value.reason == "voice_transcription_timeout"


@pytest.mark.asyncio
async def test_build_voice_transcriber_returns_faster_whisper_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    file_path = tmp_path / "voice.ogg"
    file_path.write_bytes(b"voice")

    class _Segment:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Model:
        def transcribe(self, _path: str, **_kwargs: object) -> tuple[list[_Segment], object]:
            return ([_Segment("hello"), _Segment("world")], object())

    monkeypatch.setattr(
        "jarvis.channels.whatsapp.transcription._load_faster_whisper_model",
        lambda **_kwargs: _Model(),
    )

    settings = Settings(
        WHATSAPP_VOICE_TRANSCRIBE_BACKEND="faster_whisper",
        WHATSAPP_VOICE_MODEL="base",
        WHATSAPP_VOICE_DEVICE="cpu",
        WHATSAPP_VOICE_COMPUTE_TYPE="int8",
        WHATSAPP_VOICE_LANGUAGE="",
    )
    transcriber = build_voice_transcriber(settings)
    assert isinstance(transcriber, FasterWhisperTranscriber)

    transcript = await transcriber.transcribe(file_path=file_path, mime_type="audio/ogg")
    assert transcript == "hello world"


@pytest.mark.asyncio
async def test_faster_whisper_backend_maps_transcription_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    file_path = tmp_path / "voice.ogg"
    file_path.write_bytes(b"voice")

    class _Model:
        def transcribe(self, _path: str, **_kwargs: object) -> tuple[list[object], object]:
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "jarvis.channels.whatsapp.transcription._load_faster_whisper_model",
        lambda **_kwargs: _Model(),
    )

    settings = Settings(
        WHATSAPP_VOICE_TRANSCRIBE_BACKEND="faster_whisper",
        WHATSAPP_VOICE_MODEL="base",
        WHATSAPP_VOICE_DEVICE="cpu",
        WHATSAPP_VOICE_COMPUTE_TYPE="int8",
        WHATSAPP_VOICE_LANGUAGE="",
    )
    transcriber = build_voice_transcriber(settings)

    with pytest.raises(VoiceTranscriptionError) as exc:
        await transcriber.transcribe(file_path=file_path, mime_type="audio/ogg")
    assert exc.value.reason == "voice_transcription_failed"
