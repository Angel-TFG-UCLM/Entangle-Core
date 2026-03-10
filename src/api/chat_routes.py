"""
Rutas de la API para el chat con IA.
Incluye endpoint clásico (POST) y streaming SSE para razonamiento en tiempo real.
"""
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
    Endpoint de streaming SSE. Envía eventos en tiempo real:
    - thinking: herramienta que está usando el agente
    - tool_result: resumen del resultado de la herramienta
    - reply: respuesta final
    - error: si algo falla

    El cliente puede cerrar la conexión (AbortController) para cancelar.
    """
    logger.info(f"💬 Chat stream request: {request.message[:100]}...")

    async def event_generator():
        for event in chat_stream(
            user_message=request.message,
            conversation_history=request.history,
        ):
            # Comprobar si el cliente se desconectó (cancelación)
            if await req.is_disconnected():
                logger.info("🛑 Cliente desconectó — cancelando razonamiento del agente")
                break
            yield f"data: {event}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
