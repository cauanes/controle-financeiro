import base64
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.errors import DomainError, require

MAX_BYTES = 15 * 1024 * 1024
MAX_SECONDS = 300


@dataclass
class TranscriptionResult:
    text: str
    provider: str
    confidence: float | None = None
    duration_seconds: float | None = None
    model_version: str | None = None


class TranscriptionProvider(Protocol):
    async def transcribe(self, audio: bytes, mime_type: str) -> TranscriptionResult: ...


def validate_audio(audio, mime_type, duration=None):
    require(0 < len(audio) <= MAX_BYTES, "Áudio vazio ou maior que 15 MB.")
    allowed = {
        "audio/ogg": audio.startswith(b"OggS"),
        "audio/wav": audio.startswith(b"RIFF") and audio[8:12] == b"WAVE",
        "audio/mpeg": audio.startswith(b"ID3") or audio[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
        "audio/mp4": len(audio) > 12 and audio[4:8] == b"ftyp",
    }
    mime_type = mime_type.split(";")[0].strip()
    require(allowed.get(mime_type, False), "Formato real do áudio não corresponde a um formato permitido.")
    if duration is not None:
        require(0 < float(duration) <= MAX_SECONDS, "Áudio excede cinco minutos.")
    return mime_type


class HttpTranscriptionProvider:
    """Configured private speech service; audio is never kept on local disk."""

    async def transcribe(self, audio, mime_type):
        require(
            settings.transcription_url,
            "Transcrição ainda não configurada. Envie texto.",
            "PROVIDER_UNAVAILABLE",
            503,
        )
        validate_audio(audio, mime_type)
        parsed = urlparse(settings.transcription_url)
        require(
            parsed.scheme == "https" or (settings.environment != "production" and parsed.scheme == "http"),
            "URL de transcrição precisa usar HTTPS em produção.",
        )
        headers = (
            {"Authorization": "Bearer " + settings.transcription_api_key}
            if settings.transcription_api_key
            else {}
        )
        ext = {
            "audio/ogg": "ogg",
            "audio/wav": "wav",
            "audio/mpeg": "mp3",
            "audio/mp4": "m4a",
        }.get(mime_type, "ogg")
        async with httpx.AsyncClient(timeout=90, follow_redirects=False) as client:
            res = await client.post(
                settings.transcription_url,
                files={"file": (f"audio.{ext}", audio, mime_type)},
                data={"model": settings.transcription_model or "whisper-large-v3", "language": "pt"},
                headers=headers,
            )
        require(
            res.is_success,
            "Falha na transcrição. Envie texto ou tente novamente.",
            "TRANSCRIPTION_FAILED",
            503,
        )
        result = res.json()
        text = result.get("text", "").strip()
        require(text and len(text) <= 8000, "Não foi possível entender o áudio.")
        duration = result.get("duration_seconds", result.get("duration"))
        if duration is not None:
            require(0 < float(duration) <= MAX_SECONDS, "Áudio excede cinco minutos.")
        confidence = result.get("confidence")
        if confidence is not None:
            require(0 <= confidence <= 1, "Confiança de transcrição inválida.")
        return TranscriptionResult(
            text, "configured_http", confidence, duration, settings.transcription_model or None
        )


class FakeTranscriptionProvider:
    def __init__(self, text, confidence=None):
        self.text, self.confidence = text, confidence

    async def transcribe(self, audio, mime_type):
        validate_audio(audio, mime_type)
        return TranscriptionResult(self.text, "test", self.confidence, 1)


def decode_audio(encoded, mime_type, duration=None):
    require(isinstance(encoded, str) and len(encoded) <= MAX_BYTES * 4 // 3 + 8, "Áudio excede o limite.")
    try:
        audio = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise DomainError("Áudio codificado inválido.") from None
    validate_audio(audio, mime_type, duration)
    return audio
