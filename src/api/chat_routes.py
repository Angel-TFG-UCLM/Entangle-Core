"""
Rutas de la API para el chat con IA.
Incluye endpoint clásico (POST), streaming SSE y gestión de memoria
conversacional persistente (chat_sessions).
"""
import asyncio
import json as _json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from ..ai.agent import chat, chat_stream, _run_tooled_worker
from ..ai.workers import load_agent_config
from ..core.logger import logger
from ..core.config import config
from ..core.session_memory import (
    ensure_session_indexes,
    load_history,
    new_session_id,
    persist_turn,
    reset_session,
    session_stats,
)

chat_router = APIRouter()


# Asegura los índices al arrancar la app (idempotente)
try:
    ensure_session_indexes()
except Exception as _exc:  # pragma: no cover — best-effort en startup
    logger.warning("No pude crear índices de chat_sessions: %s", _exc)


class ChatRequest(BaseModel):
    """Modelo de request para el chat."""
    message: str = Field(..., min_length=1, max_length=2000, description="Pregunta del usuario")
    history: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Historial de conversación enviado por el cliente (opcional, redundante con session_id).",
    )
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "ID de sesión persistente. Si se omite, se crea uno nuevo y se "
            "devuelve en la respuesta. Si se aporta, el agente carga el "
            "historial guardado y persiste el nuevo turno."
        ),
        max_length=64,
    )


class ChatResponse(BaseModel):
    """Modelo de response del chat."""
    reply: str
    history: List[Dict[str, Any]]
    tools_used: List[str]
    actions: List[Dict[str, Any]] = Field(default_factory=list, description="Acciones a ejecutar en el frontend")
    session_id: str = Field(..., description="ID de sesión persistente (devolver al cliente para los próximos turnos).")


def _resolve_history(req: ChatRequest) -> tuple[str, List[Dict[str, Any]]]:
    """Decide el historial efectivo y el session_id.

    Prioridad:
      1. Si ``session_id`` viene + existe: cargar historial persistido.
         Si además el cliente envía ``history``, se ignora (la fuente de
         verdad es la sesión).
      2. Si ``session_id`` viene pero no existe: se mantiene el ID
         (será creado al persistir) y se usa ``history`` si vino.
      3. Si no viene ``session_id``: se genera uno nuevo.
    """
    if req.session_id:
        persisted = load_history(req.session_id)
        if persisted:
            return req.session_id, persisted
        return req.session_id, req.history or []
    return new_session_id(), req.history or []


@chat_router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """Envía una pregunta al asistente de IA y recibe una respuesta
    basada en datos reales de la base de datos. Persiste el turno en la
    sesión si se aporta ``session_id`` (o crea uno nuevo)."""
    logger.info("💬 Chat request: %s...", request.message[:100])
    if config.AI_PROVIDER == "disabled":
        raise HTTPException(status_code=503, detail="El proveedor de IA está deshabilitado explícitamente.")

    session_id, history = _resolve_history(request)

    try:
        result = chat(
            user_message=request.message,
            conversation_history=history,
        )
    except Exception as e:
        logger.error("Error en chat endpoint: %s", e)
        raise HTTPException(status_code=500, detail="Error al procesar la consulta de IA.")

    # Persistencia del turno: guardar la pregunta del usuario + nuevos
    # mensajes generados (assistant, tool…). Como ``result["history"]``
    # ya contiene el historial completo, persistimos solo los mensajes
    # NUEVOS añadidos en este turno.
    new_messages = result.get("history", [])[len(history):]
    try:
        persist_turn(session_id, new_messages)
    except Exception as exc:  # pragma: no cover — no es crítico
        logger.warning("persist_turn falló: %s", exc)

    return ChatResponse(**result, session_id=session_id)


@chat_router.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, req: Request):
    """Endpoint de streaming SSE con flush real por evento.
    Emite un evento ``session`` inicial con el session_id efectivo para
    que el frontend lo guarde antes de empezar a renderizar la respuesta.
    """
    logger.info("💬 Chat stream request: %s...", request.message[:100])
    if config.AI_PROVIDER == "disabled":
        raise HTTPException(status_code=503, detail="El proveedor de IA está deshabilitado explícitamente.")

    session_id, history = _resolve_history(request)

    loop = asyncio.get_event_loop()
    q: asyncio.Queue[str | None] = asyncio.Queue()
    collected_messages: List[Dict[str, Any]] = []

    def _produce():
        try:
            for event in chat_stream(
                user_message=request.message,
                conversation_history=history,
            ):
                # Capturar el último ``reply`` para reconstruir historial
                try:
                    parsed = _json.loads(event)
                    if parsed.get("type") == "reply":
                        # Mensajes nuevos = todo el history menos lo que ya teníamos
                        new_history = parsed.get("history", [])
                        nonlocal_new = new_history[len(history):]
                        collected_messages.extend(nonlocal_new)
                except Exception:
                    pass
                loop.call_soon_threadsafe(q.put_nowait, event)
        except Exception as exc:
            err = _json.dumps({"type": "error", "content": str(exc)})
            loop.call_soon_threadsafe(q.put_nowait, err)
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    _producer_task = asyncio.ensure_future(loop.run_in_executor(None, _produce))

    async def event_generator():
        # Evento inicial: session_id (para que el frontend lo guarde)
        session_event = _json.dumps({"type": "session", "session_id": session_id})
        yield f"data: {session_event}{' ' * max(0, 256 - len(session_event))}\n\n"

        while True:
            event = await q.get()
            if event is None:
                break
            if await req.is_disconnected():
                logger.info("🛑 Cliente desconectó — cancelando razonamiento del agente")
                break
            padding = " " * max(0, 256 - len(event))
            yield f"data: {event}{padding}\n\n"

        # Tras agotar el stream, persistir lo recolectado
        if collected_messages:
            try:
                persist_turn(session_id, collected_messages)
            except Exception as exc:  # pragma: no cover
                logger.warning("persist_turn(stream) falló: %s", exc)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class SessionResetResponse(BaseModel):
    deleted: bool
    session_id: str


@chat_router.delete("/chat/session/{session_id}", response_model=SessionResetResponse)
async def reset_session_endpoint(session_id: str):
    """Borra una sesión bajo demanda (botón 'Nueva conversación')."""
    deleted = reset_session(session_id)
    logger.info("🗑️ reset_session(%s) → deleted=%s", session_id, deleted)
    return SessionResetResponse(deleted=deleted, session_id=session_id)


@chat_router.get("/chat/session/{session_id}/stats")
async def session_stats_endpoint(session_id: str):
    """Devuelve metadatos de una sesión: creada, último turno, nº turnos,
    cuántas veces se enrutó a cada worker. Útil para debugging."""
    stats = session_stats(session_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return stats


class ResearchRequest(BaseModel):
    """Modelo de request para el endpoint de investigación externa."""
    message: str = Field(..., min_length=1, max_length=2000, description="Pregunta de investigación")
    session_id: Optional[str] = Field(default=None, max_length=64)


@chat_router.post("/chat/research", response_model=ChatResponse)
async def chat_research_endpoint(request: ResearchRequest):
    """Endpoint separado para preguntas de investigación externa
    (papers de arXiv, noticias web). NO pasa por el router — se invoca
    directamente al worker ``deep_research`` con su prompt restrictivo.

    Decisión consciente: tener acceso a internet en un endpoint distinto
    evita que el agente "principal" se salga del dominio del proyecto
    en preguntas convencionales."""
    logger.info("🔬 Research request: %s...", request.message[:100])

    cfg = load_agent_config().workers.get("deep_research")
    if cfg is None:
        raise HTTPException(status_code=503, detail="Worker deep_research no configurado")

    session_id = request.session_id or new_session_id()
    history = load_history(session_id) if request.session_id else []

    try:
        result = _run_tooled_worker(cfg, request.message, history)
    except Exception as e:
        logger.error("Error en research endpoint: %s", e)
        raise HTTPException(status_code=500, detail="Error al procesar la investigación.")

    new_messages = result.get("history", [])[len(history):]
    try:
        persist_turn(session_id, new_messages, intent="deep_research")
    except Exception as exc:  # pragma: no cover
        logger.warning("persist_turn(research) falló: %s", exc)

    return ChatResponse(**result, session_id=session_id)
