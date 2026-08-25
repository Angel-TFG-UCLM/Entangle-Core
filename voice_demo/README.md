# Entangle Voice Demo (ElevenLabs)

Demo **autónomo** de la capa de voz: prueba el Text-to-Speech y el
Speech-to-Text de ElevenLabs sobre una respuesta del agente de Entangle,
**sin necesidad de Azure, MongoDB ni el backend completo**. Solo una API key
gratuita.

## Requisitos

- Python 3.11+
- Una API key gratuita de ElevenLabs → https://elevenlabs.io (Perfil → *API Keys*)

## Cómo ejecutarlo (2 minutos)

```bash
# desde la raíz del repo
pip install fastapi uvicorn requests python-dotenv python-multipart

# PowerShell
$env:ELEVENLABS_API_KEY="tu_key"
# bash
export ELEVENLABS_API_KEY=tu_key

python voice_demo/app.py
```

Abre **http://localhost:8100**:

- **🔊 Escuchar** → convierte el texto en voz (TTS multilingüe ES/EN).
- **🎤 Grabar pregunta** → graba con el micrófono, transcribe con **Scribe** (STT)
  y, opcionalmente, locuta la respuesta.

> Alternativa: `uvicorn voice_demo.app:app --port 8100 --reload`

## Plan gratuito de ElevenLabs

- ~10.000 créditos/mes (≈ 10 min de TTS). Suficiente para decenas de clips cortos.
- **Uso NO comercial** y **atribución obligatoria** ("Voice by ElevenLabs").
- Solo voces del catálogo (el clonado de voz es de pago; no se necesita aquí).

## Relación con el backend

Este demo replica de forma independiente la lógica de `src/ai/voice.py` para
poder correr aislado. La integración real en la API vive en:

- `src/ai/voice.py` — cliente ElevenLabs (TTS + STT).
- `src/api/voice_routes.py` — endpoints `/api/v1/voice/status|tts|stt`.

Consulta `docs/VOICE.md` para el detalle y para conectar el frontend
(Entangle-Visualizer).

## Idea para grabar (candidatura)

Graba un clip corto: escribe una respuesta del agente, pulsa **Escuchar**,
y luego prueba **Grabar pregunta** dictando algo y escuchando la respuesta.
Con eso tienes material real para enseñar la integración.
