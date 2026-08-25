"""
Rutas de la API para la capa de voz (ElevenLabs): estado, Text-to-Speech
y Speech-to-Text (Scribe).

Es una capa OPCIONAL sobre el agente conversacional: ``/voice/tts`` locuta el
texto de una respuesta y ``/voice/stt`` transcribe la voz del usuario para
enviarla al chat. Si ElevenLabs no está configurado, ``/voice/status`` lo
indica y los endpoints de audio responden 503 (el resto de la app sigue
funcionando).
"""
from typing import Optional

import requests
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..ai import voice
from ..core.config import config
from ..core.logger import logger

voice_router = APIRouter()


class TTSRequest(BaseModel):
    """Request de Text-to-Speech."""
    text: str = Field(..., min_length=1, max_length=5000, description="Texto a locutar")
    voice_id: Optional[str] = Field(default=None, description="Voz concreta (opcional)")


class VoiceStatusResponse(BaseModel):
    """Estado de la capa de voz."""
    configured: bool
    tts_model: str
    stt_model: str


class STTResponse(BaseModel):
    """Transcripción devuelta por Scribe."""
    text: str


@voice_router.get("/voice/status", response_model=VoiceStatusResponse)
async def voice_status():
    """Indica si la capa de voz está configurada, para que el frontend
    muestre u oculte el botón de voz."""
    return VoiceStatusResponse(
        configured=voice.is_configured(),
        tts_model=config.ELEVENLABS_TTS_MODEL,
        stt_model=config.ELEVENLABS_STT_MODEL,
    )


@voice_router.post("/voice/tts")
async def voice_tts(request: TTSRequest):
    """Convierte texto en audio MP3 con ElevenLabs y lo devuelve."""
    if not voice.is_configured():
        raise HTTPException(status_code=503, detail="Capa de voz no configurada (ELEVENLABS_API_KEY ausente)")
    try:
        audio = voice.text_to_speech(request.text, voice_id=request.voice_id)
    except voice.VoiceError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except requests.HTTPError as e:
        body = getattr(e.response, "text", "")[:500] if e.response is not None else ""
        code = getattr(e.response, "status_code", "?") if e.response is not None else "?"
        logger.error("Error TTS de ElevenLabs: HTTP %s — %s", code, body)
        raise HTTPException(status_code=502, detail=f"ElevenLabs TTS error (HTTP {code}): {body}")
    return Response(content=audio, media_type="audio/mpeg")


@voice_router.post("/voice/stt", response_model=STTResponse)
async def voice_stt(file: UploadFile = File(...)):
    """Transcribe audio (subido por el usuario) a texto con Scribe."""
    if not voice.is_configured():
        raise HTTPException(status_code=503, detail="Capa de voz no configurada (ELEVENLABS_API_KEY ausente)")
    audio = await file.read()
    try:
        text = voice.speech_to_text(
            audio,
            filename=file.filename or "audio.webm",
            content_type=file.content_type or "audio/webm",
        )
    except voice.VoiceError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except requests.HTTPError as e:
        logger.error("Error STT de ElevenLabs: %s", e)
        raise HTTPException(status_code=502, detail="Error al transcribir el audio con ElevenLabs")
    return STTResponse(text=text)
