"""
Memoria conversacional persistente en MongoDB.

Persiste cada turno user/assistant/tool en la colección ``chat_sessions``
con TTL automático de 30 días. Permite que el agente entienda
referencias anafóricas ("y de esos…", "el mismo pero con Python") sin
que el frontend tenga que reenviar todo el historial cada vez.

Modelo de documento:
  {
    "session_id":   "uuid-v4",
    "user_id":      "anonymous" | str,
    "messages":     [ { role, content, ts, tool_call_id?, name? }, ... ],
    "created_at":   ISODate,
    "last_active":  ISODate,           # ← campo del TTL index
    "turn_count":   int,
    "agent_calls":  { "data": int, ... }  # estadísticas opcionales
  }

Diseño:
  - **TTL en ``last_active``**: cada nuevo turno empuja la expiración.
  - **Límite de mensajes**: se mantienen los últimos ``MAX_MESSAGES``
    (default 40 → cubre 20 turnos completos). Mensajes más antiguos se
    eliminan al persistir, manteniendo el contexto barato y evitando
    que el prompt crezca sin freno.
  - **Filtrado al cargar**: ``load_history`` excluye mensajes de
    sistema (los workers añaden su propio system_prompt) y mantiene la
    secuencia válida exigida por la API (tool_call_id sin partir).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import OperationFailure, PyMongoError

from .db import get_collection, get_database
from .logger import logger


SESSIONS_COLLECTION = "chat_sessions"
MAX_MESSAGES = 40                  # ~20 turnos completos (user + assistant)
TTL_SECONDS = 30 * 24 * 3600       # 30 días


def ensure_session_indexes() -> None:
    """Idempotente: crea los índices necesarios sobre ``chat_sessions``.

    - Unique sobre ``session_id`` (lookup O(1)).
    - TTL sobre ``last_active`` con caducidad 30 días.
    """
    coll = get_collection(SESSIONS_COLLECTION)
    existing = {ix.get("name") for ix in coll.list_indexes()}

    if "session_id_unique" not in existing:
        coll.create_index("session_id", unique=True, name="session_id_unique")
        logger.info("✅ Index session_id_unique creado en %s", SESSIONS_COLLECTION)

    if "ttl_last_active" not in existing:
        coll.create_index(
            "last_active",
            expireAfterSeconds=TTL_SECONDS,
            name="ttl_last_active",
        )
        logger.info("✅ TTL index ttl_last_active (%ds) creado", TTL_SECONDS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_session_id() -> str:
    """Genera un session_id v4 (sin acoplarse al frontend)."""
    return str(uuid.uuid4())


def _sanitize_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Elimina mensajes huérfanos que harían inválido el payload al LLM.

    Azure OpenAI exige que cada mensaje con ``role=tool`` venga PRECEDIDO
    por un ``role=assistant`` con ``tool_calls`` que contenga su
    ``tool_call_id``. Si el truncate por ``MAX_MESSAGES`` cortó entre
    ambos, queda un ``tool`` huérfano que provoca 400 Bad Request.

    Esta función:
      1) Detecta ``tool`` messages sin assistant previo con ese tool_call_id → los descarta.
      2) Detecta ``assistant`` con tool_calls cuyas respuestas NO están todas presentes
         a continuación → los descarta (junto con sus tools parciales).
      3) Conserva el orden original del resto.
    """
    if not messages:
        return messages

    sanitized: List[Dict[str, Any]] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        role = m.get("role")
        if role == "tool":
            # Tool huérfano (no hay assistant pendiente que lo reclame).
            # Eso solo puede pasar si el truncate ya lo aisló.
            i += 1
            continue

        if role == "assistant" and m.get("tool_calls"):
            # Buscamos los tool responses que deben venir a continuación.
            expected_ids = {tc.get("id") for tc in (m.get("tool_calls") or []) if tc.get("id")}
            j = i + 1
            seen_ids: set = set()
            collected_tools: List[Dict[str, Any]] = []
            while j < len(messages) and messages[j].get("role") == "tool":
                tcid = messages[j].get("tool_call_id")
                if tcid in expected_ids and tcid not in seen_ids:
                    collected_tools.append(messages[j])
                    seen_ids.add(tcid)
                j += 1
            if seen_ids == expected_ids and expected_ids:
                sanitized.append(m)
                sanitized.extend(collected_tools)
                i = j
                continue
            # Faltan respuestas o no hay tool_calls válidos → descartar el group entero
            logger.warning(
                "Sanitize: descartando assistant con tool_calls incompletos "
                "(esperados=%d, encontrados=%d)",
                len(expected_ids), len(seen_ids),
            )
            i = j
            continue

        # Mensaje normal (user / assistant sin tool_calls)
        sanitized.append(m)
        i += 1

    return sanitized


def load_history(
    session_id: str,
    *,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Devuelve los mensajes guardados de una sesión, ordenados por turno.

    Filtra ``role == 'system'`` (los workers añaden su system prompt) y
    devuelve mensajes en el formato esperado por la API de Azure OpenAI.
    Aplica ``_sanitize_history`` para evitar 400 por tool messages
    huérfanos tras truncate. Si la sesión no existe, devuelve lista vacía
    SIN error: el llamador debe crear la sesión en el próximo persist.
    """
    if not session_id:
        return []
    coll = get_collection(SESSIONS_COLLECTION)
    try:
        doc = coll.find_one({"session_id": session_id}, {"_id": 0, "messages": 1})
    except PyMongoError as exc:
        logger.warning("load_history(%s) falló: %s", session_id, exc)
        return []
    if not doc:
        return []
    messages = doc.get("messages") or []
    # Devolver solo lo necesario para la API; quitar metadatos internos como ``ts``
    api_messages: List[Dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") == "system":
            continue
        cleaned = {k: v for k, v in m.items() if k not in {"ts"}}
        api_messages.append(cleaned)
    api_messages = _sanitize_history(api_messages)
    if limit:
        api_messages = api_messages[-int(limit):]
    return api_messages


def persist_turn(
    session_id: str,
    new_messages: List[Dict[str, Any]],
    *,
    user_id: str = "anonymous",
    intent: Optional[str] = None,
) -> None:
    """Añade ``new_messages`` al final del historial y empuja TTL.

    - Crea la sesión si no existe (upsert).
    - Cap a ``MAX_MESSAGES`` con ``$slice`` para no inflar el documento.
    - Filtra system prompts del worker (no se guardan, se inyectan en
      cada request).
    """
    if not session_id or not new_messages:
        return

    now = _now()
    ts_messages: List[Dict[str, Any]] = []
    for m in new_messages:
        if not isinstance(m, dict) or m.get("role") == "system":
            continue
        ts_messages.append({**m, "ts": now})

    if not ts_messages:
        return

    coll = get_collection(SESSIONS_COLLECTION)
    update: Dict[str, Any] = {
        "$setOnInsert": {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": now,
        },
        "$set": {"last_active": now},
        "$push": {
            "messages": {
                "$each": ts_messages,
                "$slice": -MAX_MESSAGES,  # mantén los últimos N
            }
        },
        "$inc": {"turn_count": 1},
    }
    if intent:
        update["$inc"][f"agent_calls.{intent.lower()}"] = 1

    try:
        coll.update_one({"session_id": session_id}, update, upsert=True)
    except OperationFailure as exc:
        logger.error("persist_turn(%s) falló: %s", session_id, exc)


def reset_session(session_id: str) -> bool:
    """Borra una sesión bajo demanda del usuario (botón 'Nueva conversación')."""
    if not session_id:
        return False
    coll = get_collection(SESSIONS_COLLECTION)
    res = coll.delete_one({"session_id": session_id})
    return res.deleted_count == 1


def session_stats(session_id: str) -> Dict[str, Any]:
    """Devuelve metadatos de una sesión (sin los mensajes en sí)."""
    if not session_id:
        return {}
    coll = get_collection(SESSIONS_COLLECTION)
    doc = coll.find_one(
        {"session_id": session_id},
        {"_id": 0, "messages": 0},
    )
    return doc or {}
