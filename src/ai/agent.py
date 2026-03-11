"""
Integración con Azure AI Foundry — Arquitectura Router-Worker.

El flujo es:
  1. ROUTER  → clasifica intención ("DATA" / "UI") con gpt-4o, max_tokens 10
  2. WORKER  → despacha al prompt especializado:
       • DATA_ANALYST  (tools + temperature 0)
       • UI_EXPERT     (sin tools + temperature 0.5)

Soporta streaming SSE para enviar pasos de razonamiento en tiempo real.
"""
import json
import threading
import time
from typing import Any, Dict, Generator, List, Optional

import requests
from azure.identity import DefaultAzureCredential

from ..core.config import config
from ..core.logger import logger
from .prompts import DATA_ANALYST_PROMPT, ROUTER_PROMPT, UI_EXPERT_PROMPT
from .tool_functions import TOOL_FUNCTIONS

# Token cache con thread-safety
_credential = None
_credential_lock = threading.Lock()

# Retry config para 429 / 5xx
_MAX_RETRIES = 3
_BASE_BACKOFF = 2  # segundos

# Límite de caracteres por tool result (evita explosión de contexto)
_MAX_TOOL_RESULT_CHARS = 8000


# Definición de las tools para el agente (OpenAI function calling format)
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "Ejecuta una consulta flexible (find) sobre una colección de MongoDB. Permite construir filtros, proyecciones y sort libremente. Solo lectura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {
                        "type": "string",
                        "enum": ["repositories", "organizations", "users", "metrics"],
                        "description": "Colección a consultar",
                    },
                    "filter": {
                        "type": "object",
                        "description": "Filtro de MongoDB (JSON). Ejemplo: {\"stargazer_count\": {\"$gt\": 100}} o {\"primary_language\": \"Python\"}. Soporta $gt, $gte, $lt, $lte, $ne, $in, $regex, $exists, $or, $and, etc.",
                    },
                    "projection": {
                        "type": "object",
                        "description": "Campos a incluir/excluir. Ejemplo: {\"name\": 1, \"stargazer_count\": 1} para incluir solo esos campos.",
                    },
                    "sort": {
                        "type": "object",
                        "description": "Ordenamiento. Ejemplo: {\"stargazer_count\": -1} para ordenar por estrellas descendente. Usa -1 (DESC) o 1 (ASC).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Máximo de resultados (1-50, default 10)",
                        "default": 10,
                    },
                },
                "required": ["collection"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_aggregation",
            "description": "Ejecuta un pipeline de aggregation de MongoDB sobre una colección. Permite cálculos complejos como $group, $match, $sort, $unwind, $project, $bucket, $facet, etc. Solo lectura ($out/$merge prohibidos).",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {
                        "type": "string",
                        "enum": ["repositories", "organizations", "users", "metrics"],
                        "description": "Colección sobre la que ejecutar el pipeline",
                    },
                    "pipeline": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Array de stages de aggregation. Ejemplo: [{\"$match\": {\"stargazer_count\": {\"$gt\": 0}}}, {\"$sort\": {\"stargazer_count\": -1}}, {\"$limit\": 10}]",
                    },
                },
                "required": ["collection", "pipeline"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_collection_schema",
            "description": "Devuelve un documento de ejemplo y el esquema (campos y tipos) de una colección. Útil para entender la estructura antes de hacer consultas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {
                        "type": "string",
                        "enum": ["repositories", "organizations", "users", "metrics"],
                        "description": "Colección de la que obtener el esquema",
                    },
                },
                "required": ["collection"],
            },
        },
    },
]




def _get_auth_headers() -> Dict[str, str]:
    """Obtiene headers de autenticación para la API de Foundry.
    Usa API Key si está configurada, sino Azure Entra ID (DefaultAzureCredential)."""
    if config.AZURE_AI_API_KEY:
        return {
            "Content-Type": "application/json",
            "api-key": config.AZURE_AI_API_KEY,
        }

    # Azure Entra ID authentication
    global _credential
    with _credential_lock:
        if _credential is None:
            _credential = DefaultAzureCredential()

    token = _credential.get_token("https://cognitiveservices.azure.com/.default")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token.token}",
    }


def _api_call_with_retry(url: str, payload: dict) -> dict:
    """
    Llama a la API de Azure OpenAI con reintentos automáticos para 429
    y errores transitorios (5xx). Respeta el header Retry-After.
    """
    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers=_get_auth_headers(),
                json=payload,
                timeout=120,
            )
            # Si no es 429 ni 5xx, procesamos normalmente
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After") or response.headers.get("retry-after")
                wait = int(retry_after) if retry_after else _BASE_BACKOFF * (2 ** attempt)
                wait = min(wait, 30)  # Cap 30s
                logger.warning(
                    f"⏳ API retornó {response.status_code}, reintento {attempt + 1}/{_MAX_RETRIES} "
                    f"en {wait}s..."
                )
                time.sleep(wait)
                last_error = requests.exceptions.HTTPError(
                    f"{response.status_code}", response=response
                )
                continue

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            raise  # No reintentar timeouts
        except requests.exceptions.ConnectionError as e:
            if attempt < _MAX_RETRIES:
                wait = _BASE_BACKOFF * (2 ** attempt)
                logger.warning(f"⏳ Error de conexión, reintento {attempt + 1}/{_MAX_RETRIES} en {wait}s...")
                time.sleep(wait)
                last_error = e
                continue
            raise

    # Agotados los reintentos
    if last_error:
        raise last_error
    raise requests.exceptions.RequestException("Reintentos agotados")


def _truncate_tool_result(result: str) -> str:
    """Trunca resultados de herramientas demasiado largos para evitar
    explosión de contexto en los mensajes acumulados."""
    if len(result) <= _MAX_TOOL_RESULT_CHARS:
        return result

    # Intentar parsear JSON para truncar de forma inteligente
    try:
        data = json.loads(result)
        results_list = data.get("results", [])
        if results_list and len(results_list) > 5:
            # Reducir a max 5 resultados y re-serializar
            data["results"] = results_list[:5]
            data["_truncated"] = True
            data["_original_count"] = data.get("count", len(results_list))
            data["count"] = len(data["results"])
            truncated = json.dumps(data, default=str)
            if len(truncated) <= _MAX_TOOL_RESULT_CHARS:
                return truncated

        # Si sigue siendo grande, serializar con menos resultados
        if results_list and len(results_list) > 2:
            data["results"] = results_list[:2]
            data["_truncated"] = True
            data["count"] = len(data["results"])
            truncated = json.dumps(data, default=str)
            if len(truncated) <= _MAX_TOOL_RESULT_CHARS:
                return truncated
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: devolver JSON válido indicando que es demasiado grande
    return json.dumps({
        "error": "El resultado es demasiado grande para procesarlo completo.",
        "hint": "Añade filtros más específicos, usa projection para limitar campos, o reduce el limit.",
        "_truncated": True,
        "_original_chars": len(result),
    })


def _build_api_url() -> str:
    """Construye la URL de la API de Azure OpenAI Chat Completions."""
    return (
        f"{config.AZURE_AI_ENDPOINT}/openai/deployments/"
        f"{config.AZURE_AI_DEPLOYMENT}/chat/completions?api-version=2024-10-21"
    )


def _route_intent(user_message: str) -> str:
    """
    Clasifica la intención del usuario como "DATA" o "UI".
    Usa el mismo modelo (gpt-4o) con max_tokens=10, sin tools.
    Fallback → "DATA" (es más seguro: el data analyst puede hacer tool calls).
    """
    try:
        payload = {
            "messages": [
                {"role": "system", "content": ROUTER_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.0,
            "max_tokens": 10,
        }
        data = _api_call_with_retry(_build_api_url(), payload)
        raw = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
            .upper()
        )
        intent = raw if raw in ("DATA", "UI") else "DATA"
        logger.info(f"🧭 Router: \"{user_message[:60]}\" → {intent} (raw={raw})")
        return intent
    except Exception as e:
        logger.warning(f"⚠️ Router falló, fallback DATA: {e}")
        return "DATA"


def _execute_tool_call(function_name: str, arguments: Dict[str, Any]) -> str:
    """Ejecuta una función local según la solicitud del agente.
    Normaliza argumentos comunes que el modelo a veces nombra diferente."""
    func = TOOL_FUNCTIONS.get(function_name)
    if not func:
        return json.dumps({"error": f"Función desconocida: {function_name}"})

    # Normalizar argumentos mal nombrados por el modelo
    if function_name == "query_database":
        # "query" → "filter", "filters" → "filter"
        if "query" in arguments and "filter" not in arguments:
            arguments["filter"] = arguments.pop("query")
        if "filters" in arguments and "filter" not in arguments:
            arguments["filter"] = arguments.pop("filters")
    elif function_name == "run_aggregation":
        # A veces el modelo envía "stages" en vez de "pipeline"
        if "stages" in arguments and "pipeline" not in arguments:
            arguments["pipeline"] = arguments.pop("stages")

    try:
        result = func(**arguments)
        return _truncate_tool_result(result)
    except TypeError as e:
        # Error de argumentos (missing/unexpected) — dar feedback claro al modelo
        error_msg = str(e)
        logger.warning(f"⚠️ Argumentos incorrectos para {function_name}: {error_msg}")
        return json.dumps({
            "error": f"Argumentos incorrectos: {error_msg}",
            "hint": "Revisa los nombres de parámetros en la definición de la herramienta.",
        })
    except Exception as e:
        logger.error(f"Error ejecutando {function_name}: {e}")
        return json.dumps({"error": str(e)})


def chat(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Arquitectura Router-Worker:
      1. Router clasifica → "DATA" o "UI"
      2. Worker especializado procesa la petición
    """
    endpoint = config.AZURE_AI_ENDPOINT
    if not endpoint:
        return {"reply": "El servicio de IA no está configurado.", "history": [], "tools_used": []}

    # ── Paso 1: Enrutar ──
    intent = _route_intent(user_message)

    # ── Paso 2: Despachar al worker ──
    if intent == "UI":
        return _chat_ui_worker(user_message, conversation_history)
    return _chat_data_worker(user_message, conversation_history)


def _chat_ui_worker(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Worker UI: sin tools, temperature 0.5, responde sobre la plataforma."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": UI_EXPERT_PROMPT}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    payload = {"messages": messages, "temperature": 0.5}

    try:
        data = _api_call_with_retry(_build_api_url(), payload)
    except requests.exceptions.Timeout:
        return {"reply": "Lo siento, el servicio tardó demasiado en responder.", "history": [], "tools_used": []}
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en UI worker: {e}")
        return {"reply": "Error al conectar con el servicio de IA.", "history": [], "tools_used": []}

    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "No pude generar una respuesta.")
    messages.append({"role": "assistant", "content": reply})
    clean_history = [m for m in messages if m.get("role") != "system"]
    return {"reply": reply, "history": clean_history, "tools_used": []}


def _chat_data_worker(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Worker DATA: con tools, temperature 0, tool_choice required en round 0."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": DATA_ANALYST_PROMPT}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    tools_used: List[str] = []
    max_rounds = 25

    for round_num in range(max_rounds):
        payload = {
            "messages": messages,
            "tools": AGENT_TOOLS,
            "tool_choice": "required" if round_num == 0 and not tools_used else "auto",
            "temperature": 0,
        }

        try:
            data = _api_call_with_retry(_build_api_url(), payload)
        except requests.exceptions.Timeout:
            logger.error("Timeout al llamar al agente de IA")
            return {"reply": "Lo siento, el servicio tardó demasiado en responder.", "history": [], "tools_used": tools_used}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error llamando al agente de IA: {e}")
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            if status == 429:
                return {"reply": "El servicio está temporalmente saturado. Espera unos segundos.", "history": [], "tools_used": tools_used}
            return {"reply": "Error al conectar con el servicio de IA.", "history": [], "tools_used": tools_used}

        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason")

        tool_calls = message.get("tool_calls")
        if finish_reason == "tool_calls" or tool_calls:
            messages.append(message)
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    fn_args = {}
                logger.info(f"🔧 Agente solicita: {fn_name}({fn_args})")
                result = _execute_tool_call(fn_name, fn_args)
                tools_used.append(fn_name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
            continue

        reply = message.get("content", "No pude generar una respuesta.")
        messages.append({"role": "assistant", "content": reply})
        clean_history = [m for m in messages if m.get("role") != "system"]
        tools_display = list(dict.fromkeys(
            TOOL_DISPLAY_NAMES.get(t, t) for t in tools_used
        ))
        return {"reply": reply, "history": clean_history, "tools_used": tools_display}

    return {
        "reply": "Se alcanzó el límite de procesamiento. Por favor, reformula tu pregunta.",
        "history": [],
        "tools_used": tools_used,
    }


# Nombres legibles para las herramientas (NO revelar nombres técnicos al usuario)
TOOL_DISPLAY_NAMES = {
    "query_database": "Consultando base de datos",
    "run_aggregation": "Ejecutando análisis agregado",
    "get_collection_schema": "Inspeccionando estructura de datos",
}

# Nombres legibles de colecciones (NO revelar nombres técnicos)
_COLLECTION_DISPLAY = {
    "repositories": "repositorios",
    "organizations": "organizaciones",
    "users": "usuarios",
    "metrics": "métricas",
}


def chat_stream(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Generator[str, None, None]:
    """
    Versión streaming — arquitectura Router-Worker.
    Emite eventos SSE:
      - {"type": "status",      "message": "..."}
      - {"type": "routing",     "intent": "DATA"|"UI"}
      - {"type": "thinking",    "description": "...", "round": N}
      - {"type": "tool_result", "summary": "..."}
      - {"type": "reply",       "content": "...", "history": [...], "tools_used": [...]}
      - {"type": "error",       "content": "..."}
    """
    endpoint = config.AZURE_AI_ENDPOINT
    if not endpoint:
        yield json.dumps({"type": "error", "content": "El servicio de IA no está configurado."})
        return

    # Evento inmediato: feedback al usuario
    yield json.dumps({"type": "status", "message": "Clasificando tu pregunta…"})

    # ── Paso 1: Enrutar ──
    intent = _route_intent(user_message)
    yield json.dumps({"type": "routing", "intent": intent})

    # Status post-routing: informar al usuario qué agente se activó
    if intent == "UI":
        yield json.dumps({"type": "status", "message": "Conectando con el Asistente UI…"})
        yield from _stream_ui_worker(user_message, conversation_history)
    else:
        yield json.dumps({"type": "status", "message": "Conectando con el Analista de datos…"})
        yield from _stream_data_worker(user_message, conversation_history)


def _stream_ui_worker(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Generator[str, None, None]:
    """Worker UI streaming: sin tools, temperature 0.5."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": UI_EXPERT_PROMPT}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    yield json.dumps({"type": "status", "message": "Asistente UI redactando respuesta…"})

    payload = {"messages": messages, "temperature": 0.5}

    try:
        data = _api_call_with_retry(_build_api_url(), payload)
    except requests.exceptions.Timeout:
        yield json.dumps({"type": "error", "content": "El servicio tardó demasiado en responder."})
        return
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en UI worker: {e}")
        yield json.dumps({"type": "error", "content": "Error al conectar con el servicio de IA."})
        return

    reply = data.get("choices", [{}])[0].get("message", {}).get("content", "No pude generar una respuesta.")
    messages.append({"role": "assistant", "content": reply})
    clean_history = [m for m in messages if m.get("role") != "system"]

    yield json.dumps({
        "type": "reply",
        "content": reply,
        "history": clean_history,
        "tools_used": [],
    })


def _stream_data_worker(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Generator[str, None, None]:
    """Worker DATA streaming: con tools, temperature 0, tool_choice required en round 0."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": DATA_ANALYST_PROMPT}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    tools_used: List[str] = []
    max_rounds = 25

    for round_num in range(max_rounds):
        if round_num > 0:
            if tools_used:
                yield json.dumps({"type": "status", "message": "Analista procesando datos obtenidos…"})
            else:
                yield json.dumps({"type": "status", "message": "Analista preparando consulta…"})

        payload = {
            "messages": messages,
            "tools": AGENT_TOOLS,
            "tool_choice": "required" if round_num == 0 and not tools_used else "auto",
            "temperature": 0,
        }

        try:
            data = _api_call_with_retry(_build_api_url(), payload)
        except requests.exceptions.Timeout:
            yield json.dumps({"type": "error", "content": "El servicio tardó demasiado en responder."})
            return
        except requests.exceptions.RequestException as e:
            logger.error(f"Error llamando al agente de IA: {e}")
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            if status == 429:
                yield json.dumps({"type": "error", "content": "El servicio está temporalmente saturado. Espera unos segundos."})
            else:
                yield json.dumps({"type": "error", "content": "Error al conectar con el servicio de IA."})
            return

        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason")

        tool_calls = message.get("tool_calls")
        if finish_reason == "tool_calls" or tool_calls:
            messages.append(message)

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    fn_args = {}

                # Emitir evento de "pensando" — SIN revelar nombres técnicos
                display_name = TOOL_DISPLAY_NAMES.get(fn_name, "Procesando")
                col_raw = fn_args.get("collection", "")
                col_display = _COLLECTION_DISPLAY.get(col_raw, col_raw)

                desc_parts = []
                if fn_name == "query_database":
                    desc_parts.append(f"en {col_display}")
                    if fn_args.get("filter"):
                        desc_parts.append("con filtros")
                elif fn_name == "run_aggregation":
                    desc_parts.append(f"en {col_display}")
                elif fn_name == "get_collection_schema":
                    desc_parts.append(f"de {col_display}")

                description = f"{display_name} {' '.join(desc_parts)}".strip()

                yield json.dumps({
                    "type": "thinking",
                    "description": description,
                    "round": round_num + 1,
                })

                logger.info(f"🔧 Agente solicita: {fn_name}({fn_args})")
                result = _execute_tool_call(fn_name, fn_args)
                tools_used.append(fn_name)

                # Emitir resumen breve del resultado
                try:
                    result_data = json.loads(result)
                    count = result_data.get("count", result_data.get("total", None))
                    if count is not None:
                        summary = f"{count} resultados obtenidos"
                    else:
                        summary = "Datos recibidos"
                except (json.JSONDecodeError, AttributeError):
                    summary = "Datos recibidos"

                yield json.dumps({
                    "type": "tool_result",
                    "summary": summary,
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            continue

        # Respuesta final
        reply = message.get("content", "No pude generar una respuesta.")
        messages.append({"role": "assistant", "content": reply})
        clean_history = [m for m in messages if m.get("role") != "system"]
        tools_display = list(dict.fromkeys(
            TOOL_DISPLAY_NAMES.get(t, t) for t in tools_used
        ))

        yield json.dumps({
            "type": "reply",
            "content": reply,
            "history": clean_history,
            "tools_used": tools_display,
        })
        return

    # Safety cap alcanzado
    yield json.dumps({
        "type": "error",
        "content": "Se alcanzó el límite de procesamiento. Reformula tu pregunta.",
    })
