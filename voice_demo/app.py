"""
Demo AUTÓNOMO de la capa de voz de Entangle con ElevenLabs.

Se ejecuta SOLO con una API key gratuita de ElevenLabs — sin Azure, sin
MongoDB, sin el backend completo. Sirve para probar y grabar la integración
de voz (TTS + STT) en local en un par de minutos.

Ejecutar (desde la raíz del repo):
    pip install fastapi uvicorn requests python-dotenv python-multipart
    # PowerShell:  $env:ELEVENLABS_API_KEY="tu_key"
    # bash:        export ELEVENLABS_API_KEY=tu_key
    python voice_demo/app.py
    # abre http://localhost:8100

Este demo replica la lógica de ``src/ai/voice.py`` de forma independiente
para poder correr sin el resto del proyecto. Uso libre / plan gratuito:
atribución "Voice by ElevenLabs", uso no comercial.
"""
import os
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

load_dotenv()

API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "")
TTS_MODEL = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_turbo_v2_5")
STT_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1")
BASE = "https://api.elevenlabs.io/v1"

app = FastAPI(title="Entangle Voice Demo (ElevenLabs)")
_cached_voice: Optional[str] = None


def _voice_id() -> str:
    global _cached_voice
    if VOICE_ID:
        return VOICE_ID
    if _cached_voice:
        return _cached_voice
    r = requests.get(f"{BASE}/voices", headers={"xi-api-key": API_KEY}, timeout=30)
    r.raise_for_status()
    voices = r.json().get("voices", [])
    if not voices:
        raise RuntimeError("No hay voces en la cuenta de ElevenLabs")
    _cached_voice = voices[0]["voice_id"]
    return _cached_voice


class TTSReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice_id: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
def index():
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.get("/status")
def status():
    return {"configured": bool(API_KEY), "tts_model": TTS_MODEL, "stt_model": STT_MODEL}


@app.post("/tts")
def tts(req: TTSReq):
    if not API_KEY:
        raise HTTPException(503, "ELEVENLABS_API_KEY no configurada")
    try:
        vid = req.voice_id or _voice_id()
        r = requests.post(
            f"{BASE}/text-to-speech/{vid}",
            headers={"xi-api-key": API_KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            json={
                "text": req.text,
                "model_id": TTS_MODEL,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=30,
        )
        r.raise_for_status()
    except requests.HTTPError as e:
        raise HTTPException(502, f"ElevenLabs TTS error: {e}")
    return Response(content=r.content, media_type="audio/mpeg")


@app.post("/stt")
async def stt(file: UploadFile = File(...)):
    if not API_KEY:
        raise HTTPException(503, "ELEVENLABS_API_KEY no configurada")
    audio = await file.read()
    try:
        r = requests.post(
            f"{BASE}/speech-to-text",
            headers={"xi-api-key": API_KEY},
            files={"file": (file.filename or "audio.webm", audio, file.content_type or "audio/webm")},
            data={"model_id": STT_MODEL},
            timeout=30,
        )
        r.raise_for_status()
    except requests.HTTPError as e:
        raise HTTPException(502, f"ElevenLabs STT error: {e}")
    return {"text": r.json().get("text", "")}


if __name__ == "__main__":
    import uvicorn

    print("\n  Entangle Voice Demo → http://localhost:8100")
    print(f"  ElevenLabs key configurada: {bool(API_KEY)}\n")
    uvicorn.run(app, host="127.0.0.1", port=8100)
