"""
Rutas de la API para el chat con IA.
Endpoint que permite al usuario hacer preguntas sobre los datos del ecosistema cuántico.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from ..ai.agent import chat
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
