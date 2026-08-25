"""
Capa de voz de Entangle: cliente de ElevenLabs para Text-to-Speech (TTS)
y Speech-to-Text (STT, modelo Scribe).

Módulo OPCIONAL: si ``ELEVENLABS_API_KEY`` no está configurada,
``is_configured()`` devuelve ``False`` y los endpoints de ``/voice`` responden
503 sin afectar al resto de la aplicación. Usa ``requests`` (ya presente en el
proyecto) para no añadir un SDK adicional, igual que el cliente de Azure AI
Foundry.

Uso libre / plan gratuito de ElevenLabs: recuerda la atribución
("Voice by ElevenLabs") y que el uso gratuito no es comercial.
"""
from __future__ import annotations

from typing import Optional

import requests

from ..core.config import config
from ..core.logger import logger

_BASE_URL = "https://api.elevenlabs.io/v1"
_TIMEOUT = 30  # segundos

# Cache de la voz auto-resuelta para no llamar a /voices en cada request.
_cached_voice_id: Optional[str] = None


class VoiceError(RuntimeError):
    """Error de la capa de voz (config ausente o datos inválidos)."""


def is_configured() -> bool:
    """True si hay API key de ElevenLabs configurada."""
    return bool(config.ELEVENLABS_API_KEY)


def _headers() -> dict:
    return {"xi-api-key": config.ELEVENLABS_API_KEY}


def resolve_voice_id() -> str:
    """Devuelve el ``voice_id`` a usar.

    Prioridad: ``ELEVENLABS_VOICE_ID`` del entorno; si está vacío, consulta
    ``/v1/voices`` y usa la primera voz disponible (cacheada). Así el demo
    funciona sin configurar un ID concreto.
    """
    global _cached_voice_id
    if config.ELEVENLABS_VOICE_ID:
        return config.ELEVENLABS_VOICE_ID
    if _cached_voice_id:
        return _cached_voice_id
    if not is_configured():
        raise VoiceError("ELEVENLABS_API_KEY no configurada")

    resp = requests.get(f"{_BASE_URL}/voices", headers=_headers(), timeout=_TIMEOUT)
    resp.raise_for_status()
    voices = resp.json().get("voices", [])
    if not voices:
        raise VoiceError("No hay voces disponibles en la cuenta de ElevenLabs")
    _cached_voice_id = voices[0]["voice_id"]
    logger.info(
        "🔊 Voz de ElevenLabs auto-seleccionada: %s",
        voices[0].get("name", _cached_voice_id),
    )
    return _cached_voice_id


def text_to_speech(
    text: str,
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None,
) -> bytes:
    """Convierte texto en audio MP3 con ElevenLabs.

    Args:
        text: texto a locutar (la respuesta del agente, por ejemplo).
        voice_id: voz concreta; si es ``None`` se resuelve automáticamente.
        model_id: modelo TTS; por defecto el multilingüe (ES/EN).

    Returns:
        Bytes del audio MP3.

    Raises:
        VoiceError: si no hay API key o el texto está vacío.
        requests.HTTPError: si la API de ElevenLabs responde con error.
    """
    if not is_configured():
        raise VoiceError("ELEVENLABS_API_KEY no configurada")
    if not text or not text.strip():
        raise VoiceError("El texto para TTS está vacío")

    vid = voice_id or resolve_voice_id()
    model = model_id or config.ELEVENLABS_TTS_MODEL
    url = f"{_BASE_URL}/text-to-speech/{vid}"
    payload = {
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    headers = {**_headers(), "Content-Type": "application/json", "Accept": "audio/mpeg"}

    resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
    resp.raise_for_status()
    logger.info("🔊 TTS generado: %d chars → %d bytes de audio", len(text), len(resp.content))
    return resp.content


def speech_to_text(
    audio: bytes,
    filename: str = "audio.webm",
    content_type: str = "audio/webm",
    model_id: Optional[str] = None,
) -> str:
    """Transcribe audio a texto con ElevenLabs Scribe (STT).

    Args:
        audio: bytes del audio grabado por el usuario.
        filename / content_type: metadatos del fichero multipart.
        model_id: modelo STT; por defecto ``scribe_v1``.

    Returns:
        Transcripción (texto).

    Raises:
        VoiceError: si no hay API key o el audio está vacío.
        requests.HTTPError: si la API de ElevenLabs responde con error.
    """
    if not is_configured():
        raise VoiceError("ELEVENLABS_API_KEY no configurada")
    if not audio:
        raise VoiceError("El audio para STT está vacío")

    model = model_id or config.ELEVENLABS_STT_MODEL
    url = f"{_BASE_URL}/speech-to-text"
    files = {"file": (filename, audio, content_type)}
    data = {"model_id": model}

    resp = requests.post(url, headers=_headers(), files=files, data=data, timeout=_TIMEOUT)
    resp.raise_for_status()
    text = resp.json().get("text", "")
    logger.info("🎤 STT transcrito: %d bytes → %d chars", len(audio), len(text))
    return text
