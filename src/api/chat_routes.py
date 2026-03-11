"""
Rutas de la API para el chat con IA.
Incluye endpoint clásico (POST) y streaming SSE para razonamiento en tiempo real.
"""
import asyncio
import json as _json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from ..ai.agent import chat, chat_stream
from ..core.logger import logger

chat_router = APIRouter()


class ChatRequest(BaseModel):
    """Modelo de request para el chat."""
    message: str = Field(..., min_length=1, max_length=2000, description="Pregunta del usuario")
    history: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Historial de conversación previo",
    )


class ChatResponse(BaseModel):
    """Modelo de response del chat."""
    reply: str
    history: List[Dict[str, Any]]
    tools_used: List[str]


@chat_router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Envía una pregunta al asistente de IA y recibe una respuesta
    basada en datos reales de la base de datos.
    """
    logger.info(f"💬 Chat request: {request.message[:100]}...")

    try:
        result = chat(
            user_message=request.message,
            conversation_history=request.history,
        )
        return ChatResponse(**result)

    except Exception as e:
        logger.error(f"Error en chat endpoint: {e}")
        raise HTTPException(status_code=500, detail="Error al procesar la consulta de IA.")


@chat_router.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, req: Request):
    """
    Endpoint de streaming SSE con flush real por evento.
    Ejecuta el generador síncrono (bloqueante) en un thread pool
    y envía cada evento al cliente de forma inmediata.
    """
    logger.info(f"💬 Chat stream request: {request.message[:100]}...")

    loop = asyncio.get_event_loop()
    q: asyncio.Queue[str | None] = asyncio.Queue()

    def _produce():
        """Ejecuta el generador síncrono en un hilo del pool."""
        try:
            for event in chat_stream(
                user_message=request.message,
                conversation_history=request.history,
            ):
                loop.call_soon_threadsafe(q.put_nowait, event)
        except Exception as exc:
            err = _json.dumps({"type": "error", "content": str(exc)})
            loop.call_soon_threadsafe(q.put_nowait, err)
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)  # sentinel

    # Lanzar productor en thread pool
    asyncio.ensure_future(loop.run_in_executor(None, _produce))

    async def event_generator():
        while True:
            event = await q.get()
            if event is None:
                break
            if await req.is_disconnected():
                logger.info("🛑 Cliente desconectó — cancelando razonamiento del agente")
                break
            # Padding para superar buffers TCP/proxy (~256 bytes extra)
            padding = " " * max(0, 256 - len(event))
            yield f"data: {event}{padding}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
