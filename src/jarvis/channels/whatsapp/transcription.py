"""Voice-note transcription adapters for WhatsApp inbound media."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from jarvis.config import Settings


class VoiceTranscriptionError(RuntimeError):
    """Raised when a voice transcript cannot be produced."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class VoiceTranscriber(Protocol):
    async def transcribe(self, file_path: Path, mime_type: str) -> str: ...


class StubVoiceTranscriber:
    async def transcribe(self, file_path: Path, mime_type: str) -> str:
        if not file_path.exists():
            raise VoiceTranscriptionError("voice_transcription_input_missing")
        _ = mime_type
        return "[stub: transcription not configured]"


@lru_cache(maxsize=4)
def _load_faster_whisper_model(
    *,
    model_name: str,
    device: str,
    compute_type: str,
) -> object:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # pragma: no cover - optional dependency import path
        raise VoiceTranscriptionError("voice_transcription_backend_unavailable") from exc

    try:
        return WhisperModel(model_name, device=device, compute_type=compute_type)
    except Exception as exc:
        raise VoiceTranscriptionError("voice_transcription_backend_unavailable") from exc


class FasterWhisperTranscriber:
    def __init__(
        self,
        *,
        model_name: str,
        device: str,
        compute_type: str,
        language: str,
    ) -> None:
        self._model = _load_faster_whisper_model(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
        )
        self._language = language.strip().lower()

    def _transcribe_sync(self, *, file_path: Path) -> str:
        kwargs: dict[str, object] = {"beam_size": 1}
        if self._language:
            kwargs["language"] = self._language

        try:
            segments, _ = self._model.transcribe(str(file_path), **kwargs)  # type: ignore[attr-defined]
        except Exception as exc:
            raise VoiceTranscriptionError("voice_transcription_failed") from exc

        parts = [
            str(getattr(segment, "text", "")).strip()
            for segment in segments
            if str(getattr(segment, "text", "")).strip()
        ]
        transcript = " ".join(parts).strip()
        if not transcript:
            raise VoiceTranscriptionError("voice_transcription_failed")
        return transcript

    async def transcribe(self, file_path: Path, mime_type: str) -> str:
        if not file_path.exists():
            raise VoiceTranscriptionError("voice_transcription_input_missing")
        _ = mime_type
        return await asyncio.to_thread(self._transcribe_sync, file_path=file_path)


def build_voice_transcriber(settings: Settings) -> VoiceTranscriber:
    backend = settings.whatsapp_voice_transcribe_backend.strip().lower()
    if backend in {"", "stub"}:
        return StubVoiceTranscriber()
    if backend in {"faster_whisper", "faster-whisper"}:
        return FasterWhisperTranscriber(
            model_name=settings.whatsapp_voice_model.strip() or "base",
            device=settings.whatsapp_voice_device.strip() or "cpu",
            compute_type=settings.whatsapp_voice_compute_type.strip() or "int8",
            language=settings.whatsapp_voice_language,
        )
    raise VoiceTranscriptionError("voice_transcription_backend_unsupported")


async def transcribe_with_timeout(
    *,
    transcriber: VoiceTranscriber,
    file_path: Path,
    mime_type: str,
    timeout_seconds: int,
) -> str:
    if timeout_seconds <= 0:
        raise VoiceTranscriptionError("voice_transcription_timeout")
    try:
        return await asyncio.wait_for(
            transcriber.transcribe(file_path=file_path, mime_type=mime_type),
            timeout=float(timeout_seconds),
        )
    except TimeoutError as exc:
        raise VoiceTranscriptionError("voice_transcription_timeout") from exc
