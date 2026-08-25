# Capa de voz (ElevenLabs) — TTS + STT

Capa **opcional** que añade voz al asistente conversacional de Entangle usando
[ElevenLabs](https://elevenlabs.io):

- **Text-to-Speech (TTS):** locuta la respuesta del agente (voz multilingüe ES/EN).
- **Speech-to-Text (STT, Scribe):** transcribe la voz del usuario para enviarla al chat.

Si `ELEVENLABS_API_KEY` no está configurada, la capa se desactiva de forma
transparente (los endpoints `/voice` responden `503`) y el resto de la
aplicación funciona igual.

## Componentes

| Archivo | Rol |
|---------|-----|
| `src/ai/voice.py` | Cliente de ElevenLabs (TTS + STT) usando `requests`. |
| `src/api/voice_routes.py` | Endpoints `GET /voice/status`, `POST /voice/tts`, `POST /voice/stt`. |
| `voice_demo/` | Demo autónomo (solo requiere la API key). |
| `tests/test_voice.py` | Tests unitarios y de rutas (HTTP mockeado). |

## Configuración (`.env`)

```env
ELEVENLABS_API_KEY=            # obligatoria para activar la voz
ELEVENLABS_VOICE_ID=           # vacío = auto-seleccionar la primera voz
ELEVENLABS_TTS_MODEL=eleven_multilingual_v2
ELEVENLABS_STT_MODEL=scribe_v1
```

API key gratuita en https://elevenlabs.io (Perfil → *API Keys*).

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/v1/voice/status` | `{configured, tts_model, stt_model}` — para mostrar/ocultar el botón de voz. |
| POST | `/api/v1/voice/tts` | Body `{text, voice_id?}` → audio `audio/mpeg`. |
| POST | `/api/v1/voice/stt` | `multipart/form-data` con `file` (audio) → `{text}`. |

## Conectar el frontend (Entangle-Visualizer)

Tras recibir la respuesta del agente, pide el audio y reprodúcelo:

```js
async function speak(text) {
  const r = await fetch(`${API_BASE}/api/v1/voice/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) return;                    // 503 → voz no configurada, se ignora
  const audio = new Audio(URL.createObjectURL(await r.blob()));
  audio.play();
}
```

Para la entrada por voz, graba con `MediaRecorder`, envía el blob a
`/api/v1/voice/stt` y usa el `text` devuelto como mensaje del chat
(ver `voice_demo/index.html` para un ejemplo completo).

## Plan gratuito y licencia de uso

El plan gratuito de ElevenLabs permite ~10.000 créditos/mes (≈ 10 min de TTS),
es de **uso no comercial** y exige **atribución** ("Voice by ElevenLabs"). El
clonado de voz no está incluido (se usan voces del catálogo).
