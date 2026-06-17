"""
Integración con Azure AI Foundry — Arquitectura Router-Worker config-driven.

El flujo es:
  1. ROUTER  → clasifica intención usando ``config/workers.yaml``
  2. WORKER  → despacha al worker correspondiente con sus tools y reasoning_effort

Workers, tools y prompts se declaran en ``config/workers.yaml`` y se
registran con ``@tool`` en ``tool_functions.py``. Para añadir un worker
nuevo basta con editar el YAML — no se toca este módulo.

Compatibilidad con código antiguo:
  - ``TOOL_FUNCTIONS`` sigue exportándose para tests legacy.
  - ``AGENT_TOOLS`` se construye dinámicamente desde el registry para tests
    que aún lo importan.

Soporta streaming SSE para enviar pasos de razonamiento en tiempo real.
"""
import json
import re
import threading
import time
from typing import Any, Dict, Generator, List, Optional, Tuple

import requests
from azure.identity import DefaultAzureCredential

from ..core.config import config
from ..core.logger import logger

# Side-effect imports: registran las tools (@tool decorator) en tool_registry.
# Imprescindible que se importen antes de cualquier llamada a get_schemas_for.
from . import tool_functions as _tool_functions  # noqa: F401
from . import rag_tool as _rag_tool  # noqa: F401  -- RAG search tool
from . import insights_tools as _insights_tools  # noqa: F401  -- similar/compare/collab
from . import research_tools as _research_tools  # noqa: F401  -- web + arXiv
from .prompts import (
    DATA_ANALYST_PROMPT,
    ROUTER_PROMPT,
    UI_DASHBOARD_PROMPT,
    UI_UNIVERSE_PROMPT,
)
from .tool_functions import TOOL_FUNCTIONS  # backwards-compat re-export
from .tool_registry import get_callable, get_display_name, get_schemas_for
from .workers import AgentConfig, WorkerConfig, load_agent_config

# Token cache con thread-safety
_credential = None
_credential_lock = threading.Lock()

# Retry config para 429 / 5xx
_MAX_RETRIES = 3
_BASE_BACKOFF = 2  # segundos

# Límite de caracteres por tool result (evita explosión de contexto)
_MAX_TOOL_RESULT_CHARS = 8000


def _agent_config() -> AgentConfig:
    """Acceso perezoso a la configuración (cacheada en workers.py)."""
    return load_agent_config()


def _build_agent_tools() -> List[Dict[str, Any]]:
    """Backwards-compat: devuelve todos los schemas registrados, en el orden
    en que se declararon. Tests antiguos importan ``AGENT_TOOLS`` esperando
    una lista; mantenemos esa interfaz como vista del registry."""
    # Suma de tools de todos los workers (sin duplicados, preservando orden)
    seen: Dict[str, None] = {}
    for worker in _agent_config().workers.values():
        for name in worker.tools:
            seen.setdefault(name, None)
    return get_schemas_for(seen.keys())


# Vista pública (se evalúa la primera vez que se importa). Tests que muteen
# esta lista verán los cambios sólo en su scope; el agente real recalcula
# por-worker en cada petición.
AGENT_TOOLS: List[Dict[str, Any]] = _build_agent_tools()


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


def _api_call_streaming(url: str, payload: dict) -> Generator[Dict[str, Any], None, None]:
    """
    Llama a Azure OpenAI con stream=True y yields chunks normalizados.
    Los tool_calls vienen fragmentados; se acumulan internamente y se emiten
    al final como un único evento.

    Yields dicts con esta forma:
      - {"type": "content", "text": "..."}            → trozo de texto del reply
      - {"type": "tool_calls", "calls": [...]}         → tool calls completos
      - {"type": "done", "finish_reason": "stop"|...}  → fin del stream

    NOTA: no implementa retry automático. Para casos críticos (router) seguir
    usando ``_api_call_with_retry``. Streaming solo se usa en los workers
    porque ahí prima la UX percibida sobre la resiliencia.
    """
    payload = _normalize_payload(payload)
    payload["stream"] = True

    response = requests.post(
        url,
        headers=_get_auth_headers(),
        json=payload,
        stream=True,
        timeout=120,
    )
    # Si el servidor devuelve error, loguear el body completo (debugging 400/422)
    if response.status_code >= 400:
        body = ""
        try:
            body = response.text[:1000]
        except Exception:
            pass
        logger.error(
            "💥 Azure OpenAI %d Bad Request. Body: %s",
            response.status_code, body,
        )
    response.raise_for_status()

    accumulated_tool_calls: Dict[int, Dict[str, Any]] = {}
    finish_reason: Optional[str] = None

    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        # Azure SSE: "data: {...}" o "data: [DONE]"
        if not raw_line.startswith("data:"):
            continue
        data_str = raw_line[5:].strip()
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue

        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}

        # Texto del reply (puede llegar en muchos chunks pequeños)
        content_piece = delta.get("content")
        if content_piece:
            yield {"type": "content", "text": content_piece}

        # Tool calls fragmentados: vienen con index, vamos acumulando
        for tc_delta in delta.get("tool_calls") or []:
            idx = tc_delta.get("index", 0)
            entry = accumulated_tool_calls.setdefault(idx, {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            })
            if tc_delta.get("id"):
                entry["id"] = tc_delta["id"]
            fn = tc_delta.get("function") or {}
            if fn.get("name"):
                entry["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                entry["function"]["arguments"] += fn["arguments"]

        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]

    if accumulated_tool_calls:
        ordered = [accumulated_tool_calls[k] for k in sorted(accumulated_tool_calls.keys())]
        yield {"type": "tool_calls", "calls": ordered}

    yield {"type": "done", "finish_reason": finish_reason}


def _api_call_with_retry(url: str, payload: dict) -> dict:
    """
    Llama a la API de Azure OpenAI con reintentos automáticos para 429
    y errores transitorios (5xx). Respeta el header Retry-After.
    """
    payload = _normalize_payload(payload)
    last_error = None
    msg_count = len(payload.get("messages", []))
    has_tools = bool(payload.get("tools"))
    tool_choice = payload.get("tool_choice", "none")
    for attempt in range(_MAX_RETRIES + 1):
        try:
            t0 = time.time()
            logger.info(
                f"🌐 API call attempt={attempt} msgs={msg_count} "
                f"tools={has_tools} tool_choice={tool_choice}"
            )
            response = requests.post(
                url,
                headers=_get_auth_headers(),
                json=payload,
                timeout=120,
            )
            elapsed = time.time() - t0
            logger.info(
                f"🌐 API response: status={response.status_code} "
                f"elapsed={elapsed:.1f}s content_length={len(response.content)}"
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
            elapsed = time.time() - t0
            logger.error(f"⏰ API TIMEOUT after {elapsed:.1f}s (attempt {attempt})")
            raise
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
    """Construye la URL de la API de Azure OpenAI Chat Completions.

    Usa la api-version 2024-12-01-preview porque es la primera que admite
    `reasoning_effort` y `max_completion_tokens` para la familia GPT-5.
    """
    return (
        f"{config.AZURE_AI_ENDPOINT}/openai/deployments/"
        f"{config.AZURE_AI_DEPLOYMENT}/chat/completions?api-version=2024-12-01-preview"
    )


# Detección de familia de modelo: gpt-5-mini, gpt-5-nano, o1, etc. usan
# parámetros distintos a gpt-4o. Cuando AZURE_AI_DEPLOYMENT contiene "gpt-5",
# "o1" o "o3", se aplica el contrato nuevo:
#   - max_tokens         → max_completion_tokens
#   - temperature !=1.0  → omitida (los modelos de razonamiento solo aceptan 1.0)
_REASONING_HINTS = ("gpt-5", "gpt5", "o1", "o3")


def _is_reasoning_model() -> bool:
    name = (config.AZURE_AI_DEPLOYMENT or "").lower()
    return any(hint in name for hint in _REASONING_HINTS)


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Adapta el payload según la familia del modelo de despliegue.

    Para modelos de razonamiento (gpt-5*, o1*, o3*):
      • Renombra max_tokens → max_completion_tokens.
      • Multiplica max_completion_tokens × 4 (mínimo 200) para reservar
        cupo a los tokens de razonamiento internos que la API consume
        antes de generar texto visible.
      • Elimina temperatures distintas de 1.0 (la única permitida).
      • Inyecta reasoning_effort="minimal" cuando no se ha definido,
        para que el router/clasificador no consuma tokens en cadenas
        de razonamiento innecesarias y mantenga latencia baja.
    """
    if not _is_reasoning_model():
        return payload

    normalized = dict(payload)

    if "max_tokens" in normalized:
        original = normalized.pop("max_tokens")
        normalized.setdefault("max_completion_tokens", max(int(original) * 4, 200))

    temp = normalized.get("temperature")
    if temp is not None and not _is_default_temperature(temp):
        normalized.pop("temperature", None)

    normalized.setdefault("reasoning_effort", "minimal")

    return normalized


def _is_default_temperature(value) -> bool:
    """Return True when ``value`` equals the reasoning-models default (1.0)
    within a small float tolerance (avoids the S1244 float-equality smell)."""
    try:
        return abs(float(value) - 1.0) < 1e-9
    except (TypeError, ValueError):
        return False


# ── Regex para extraer acciones embebidas en la respuesta del agente ──
_ACTION_PATTERN = re.compile(
    r'\[ACTION:(\w+)(?::(\{.*?\}))?\]',
    re.DOTALL,
)

# Patrón para limpiar code fences que envuelvan marcadores de acción
# El modelo a veces mete los marcadores dentro de ```...``` por costumbre
_CODE_FENCE_ACTION = re.compile(
    r'```[^\n]*\n*\s*(\[ACTION:[^\]]+\])\s*\n*```',
    re.DOTALL,
)


def _extract_actions(reply: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Extrae directivas de acción embebidas en la respuesta del agente.

    Formato soportado:
      [ACTION:OPEN_UNIVERSE]
      [ACTION:OPEN_UNIVERSE:{"autoTour":true}]
      [ACTION:CREATE_VIEW:{"orgs":["qiskit","IBM"]}]

    También detecta marcadores envueltos en code fences (```...```).

    Retorna:
      (cleaned_reply, actions_list)
      donde cleaned_reply es el texto sin los marcadores
      y actions_list es [{"action": "OPEN_UNIVERSE", "data": {...}}, ...]
    """
    # Paso 0: Desenvolver code fences que contengan marcadores de acción
    text = _CODE_FENCE_ACTION.sub(r'\1', reply)

    actions: List[Dict[str, Any]] = []
    for match in _ACTION_PATTERN.finditer(text):
        action_type = match.group(1)
        raw_data = match.group(2)
        try:
            action_data = json.loads(raw_data) if raw_data else {}
        except (json.JSONDecodeError, TypeError):
            action_data = {}
        actions.append({"action": action_type, "data": action_data})

    # Eliminar los marcadores del texto
    cleaned = _ACTION_PATTERN.sub('', text).strip()
    # Limpiar líneas vacías duplicadas que queden
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned, actions


def _route_intent(user_message: str) -> str:
    """Clasifica la intención del usuario contra los intents definidos en
    ``config/workers.yaml``. El router devuelve el nombre del intent en
    UPPERCASE (legacy: tests existentes lo comparan así); en caso de error
    o respuesta no reconocida cae al ``fallback`` del config.
    """
    router_cfg = _agent_config().router
    valid_upper = {i.upper() for i in router_cfg.intents}
    fallback_upper = router_cfg.fallback.upper()

    try:
        payload = {
            "messages": [
                {"role": "system", "content": router_cfg.prompt},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.0,
            "max_tokens": router_cfg.max_completion_tokens,
        }
        data = _api_call_with_retry(_build_api_url(), payload)
        raw = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
            .upper()
        )
        intent = raw if raw in valid_upper else fallback_upper
        logger.info(f"🧭 Router: \"{user_message[:60]}\" → {intent} (raw={raw})")
        return intent
    except Exception as e:
        logger.warning(f"⚠️ Router falló, fallback {fallback_upper}: {e}")
        return fallback_upper


def _execute_tool_call(function_name: str, arguments: Dict[str, Any]) -> str:
    """Ejecuta una función local según la solicitud del agente.
    Normaliza argumentos comunes que el modelo a veces nombra diferente.
    Usa el tool registry como fuente de verdad, con caída al dict legacy
    TOOL_FUNCTIONS para compatibilidad con tests que aún lo monkeypatchean."""
    func = get_callable(function_name) or TOOL_FUNCTIONS.get(function_name)
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
    """Arquitectura Router-Worker config-driven.

      1. Router clasifica el intent contra ``config/workers.yaml``.
      2. Se busca el WorkerConfig correspondiente.
      3. Si el worker tiene tools → ``_run_tooled_worker``; si no → ``_run_ui_worker``.
    """
    endpoint = config.AZURE_AI_ENDPOINT
    if not endpoint:
        return {"reply": "El servicio de IA no está configurado.", "history": [], "tools_used": [], "actions": []}

    # ── Paso 1: Enrutar ──
    intent_upper = _route_intent(user_message)
    cfg = _agent_config().get_worker(intent_upper.lower())

    # ── Paso 2: Despachar al worker ──
    if cfg.has_tools:
        return _run_tooled_worker(cfg, user_message, conversation_history)
    return _run_ui_worker(cfg, user_message, conversation_history)


def _run_ui_worker(
    cfg: WorkerConfig,
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Worker UI genérico (sin tools). Lee prompt, temperature y reasoning
    desde ``cfg`` — añadir un worker UI nuevo no requiere tocar este código."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": cfg.prompt}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    payload: Dict[str, Any] = {"messages": messages, "temperature": cfg.temperature}
    if cfg.reasoning_effort:
        payload["reasoning_effort"] = cfg.reasoning_effort

    try:
        data = _api_call_with_retry(_build_api_url(), payload)
    except requests.exceptions.Timeout:
        return {"reply": "Lo siento, el servicio tardó demasiado en responder.", "history": [], "tools_used": [], "actions": []}
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en {cfg.display_name} worker: {e}")
        return {"reply": "Error al conectar con el servicio de IA.", "history": [], "tools_used": [], "actions": []}

    raw_reply = data.get("choices", [{}])[0].get("message", {}).get("content", "No pude generar una respuesta.")

    reply, actions = _extract_actions(raw_reply)
    if actions:
        logger.info(f"🎬 {cfg.display_name} emitió {len(actions)} acción(es): {[a['action'] for a in actions]}")

    messages.append({"role": "assistant", "content": reply})
    clean_history = [m for m in messages if m.get("role") != "system"]
    return {"reply": reply, "history": clean_history, "tools_used": [], "actions": actions}


# Aliases para compatibilidad hacia atrás con tests que monkeypatchean los
# nombres concretos. Implementan la antigua firma reenviando al despachador
# config-driven (`_run_ui_worker`).
def _chat_ui_generic(
    system_prompt: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    label: str = "UI",
) -> Dict[str, Any]:
    """Compat: ejecuta un worker UI ad-hoc con un prompt arbitrario."""
    ad_hoc = WorkerConfig(
        intent=label.lower(),
        display_name=label,
        prompt=system_prompt,
        tools=[],
        temperature=0.5,
        reasoning_effort="low",
    )
    return _run_ui_worker(ad_hoc, user_message, conversation_history)


def _chat_dashboard_worker(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return _run_ui_worker(_agent_config().get_worker("dashboard"), user_message, conversation_history)


def _chat_universe_worker(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return _run_ui_worker(_agent_config().get_worker("universe"), user_message, conversation_history)


def _chat_data_worker(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return _run_tooled_worker(_agent_config().get_worker("data"), user_message, conversation_history)


def _run_tooled_worker(
    cfg: WorkerConfig,
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Worker con function-calling. Lee tools, temperature, reasoning_effort,
    tool_choice_first_round y max_rounds desde ``cfg``."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": cfg.prompt}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    tools_schemas = get_schemas_for(cfg.tools)
    tools_used: List[str] = []

    for round_num in range(cfg.max_rounds):
        tool_choice = cfg.tool_choice_first_round if (round_num == 0 and not tools_used) else "auto"
        payload: Dict[str, Any] = {
            "messages": messages,
            "tools": tools_schemas,
            "tool_choice": tool_choice,
            "temperature": cfg.temperature,
        }
        if cfg.reasoning_effort:
            payload["reasoning_effort"] = cfg.reasoning_effort

        try:
            data = _api_call_with_retry(_build_api_url(), payload)
        except requests.exceptions.Timeout:
            logger.error("Timeout al llamar al agente de IA")
            return {"reply": "Lo siento, el servicio tardó demasiado en responder.", "history": [], "tools_used": tools_used, "actions": []}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error llamando al agente de IA: {e}")
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            if status == 429:
                return {"reply": "El servicio está temporalmente saturado. Espera unos segundos.", "history": [], "tools_used": tools_used, "actions": []}
            return {"reply": "Error al conectar con el servicio de IA.", "history": [], "tools_used": tools_used, "actions": []}

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
        tools_display = list(dict.fromkeys(get_display_name(t) for t in tools_used))
        return {"reply": reply, "history": clean_history, "tools_used": tools_display, "actions": []}

    return {
        "reply": "Se alcanzó el límite de procesamiento. Por favor, reformula tu pregunta.",
        "history": [],
        "tools_used": tools_used,
        "actions": [],
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
    Versión streaming — arquitectura Router-Worker config-driven.
    Emite eventos SSE:
      - {"type": "status",      "message": "..."}
      - {"type": "routing",     "intent": "DATA"|"DASHBOARD"|"UNIVERSE"|...}
      - {"type": "thinking",    "description": "...", "round": N}
      - {"type": "tool_result", "summary": "..."}
      - {"type": "reply",       "content": "...", "history": [...], "tools_used": [...]}
      - {"type": "error",       "content": "..."}
    """
    endpoint = config.AZURE_AI_ENDPOINT
    if not endpoint:
        yield json.dumps({"type": "error", "content": "El servicio de IA no está configurado."})
        return

    # Paso 1: thinking real del router (no fake)
    yield json.dumps({
        "type": "thinking",
        "description": "Eligiendo el agente más adecuado",
        "phase": "router",
    })

    # ── Paso 1: Enrutar ──
    # _route_intent es una llamada bloqueante a Azure OpenAI. En producción
    # puede tardar varios segundos y, si no enviamos NADA al cliente durante
    # ese tiempo, proxies intermedios (Front Door, ingress de Container Apps,
    # CDN) cierran el stream SSE por idle. Para evitarlo, ejecutamos la
    # clasificación en un hilo y mientras tanto emitimos heartbeats SSE
    # invisibles (comentarios) que mantienen viva la conexión sin ensuciar
    # la UI con mensajes fake.
    cfg = _agent_config()
    fallback_upper = cfg.router.fallback.upper()
    result_holder: Dict[str, Any] = {}

    def _run_router():
        try:
            result_holder["intent"] = _route_intent(user_message)
        except Exception as exc:  # pragma: no cover — _route_intent ya hace su propio fallback
            result_holder["error"] = exc
            result_holder["intent"] = fallback_upper

    router_thread = threading.Thread(target=_run_router, daemon=True)
    router_thread.start()

    HEARTBEAT_INTERVAL_S = 2.0
    MAX_WAIT_S = 60.0
    waited = 0.0
    while router_thread.is_alive() and waited < MAX_WAIT_S:
        router_thread.join(timeout=HEARTBEAT_INTERVAL_S)
        waited += HEARTBEAT_INTERVAL_S
        if router_thread.is_alive():
            # Heartbeat invisible: mantiene la conexión TCP viva sin generar
            # ruido en la UI. El frontend ignora type='heartbeat' por defecto
            # en el switch SSE. El thinking step "Eligiendo agente" sigue
            # visible con su timer hasta que llegue el tool_result.
            yield json.dumps({"type": "heartbeat"})

    if router_thread.is_alive():
        logger.warning("⚠️ Router timeout — fallback a %s", fallback_upper)
        intent = fallback_upper
    else:
        intent = result_holder.get("intent", fallback_upper)

    worker_cfg = cfg.get_worker(intent.lower())

    # Cerrar el thinking del router con un tool_result real
    yield json.dumps({
        "type": "tool_result",
        "summary": f"Agente seleccionado: {worker_cfg.display_name}",
    })

    yield json.dumps({"type": "routing", "intent": intent})

    # Preservar indirecciones legacy: tests existentes monkeypatchean
    # ``_stream_data_worker`` y ``_stream_ui_generic``. Mantengo las dos
    # rutas para que el flujo siga siendo testeable sin tocar tests
    # antiguos. Nuevos workers tooled usan el dispatcher genérico directo.
    if worker_cfg.has_tools:
        if worker_cfg.intent == "data":
            yield from _stream_data_worker(user_message, conversation_history)
        else:
            yield from _stream_tooled_worker(worker_cfg, user_message, conversation_history)
    else:
        # ``_stream_ui_generic`` acepta prompt+label y dentro reusa
        # ``_stream_ui_worker``; los tests legacy lo monkeypatchean.
        yield from _stream_ui_generic(
            worker_cfg.prompt,
            user_message,
            conversation_history,
            worker_cfg.display_name,
        )


def _stream_ui_worker(
    cfg: WorkerConfig,
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Generator[str, None, None]:
    """Streaming de un worker UI (sin tools). Lee parámetros desde ``cfg``."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": cfg.prompt}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    yield json.dumps({
        "type": "thinking",
        "description": f"{cfg.display_name} preparando respuesta",
        "phase": "ui_worker",
    })

    payload: Dict[str, Any] = {"messages": messages, "temperature": cfg.temperature}
    if cfg.reasoning_effort:
        payload["reasoning_effort"] = cfg.reasoning_effort

    try:
        data = _api_call_with_retry(_build_api_url(), payload)
    except requests.exceptions.Timeout:
        yield json.dumps({"type": "error", "content": "El servicio tardó demasiado en responder."})
        return
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en {cfg.display_name} worker: {e}")
        yield json.dumps({"type": "error", "content": "Error al conectar con el servicio de IA."})
        return

    raw_reply = data.get("choices", [{}])[0].get("message", {}).get("content", "No pude generar una respuesta.")

    reply, actions = _extract_actions(raw_reply)
    if actions:
        logger.info(f"🎬 {cfg.display_name} emitió {len(actions)} acción(es): {[a['action'] for a in actions]}")

    # Cerrar el thinking con un tool_result real
    yield json.dumps({
        "type": "tool_result",
        "summary": f"{len(actions)} acción(es) a aplicar" if actions else "Respuesta lista",
    })

    for action in actions:
        yield json.dumps({
            "type": "action",
            "action": action["action"],
            "data": action.get("data", {}),
        })

    messages.append({"role": "assistant", "content": reply})
    clean_history = [m for m in messages if m.get("role") != "system"]

    yield json.dumps({
        "type": "reply",
        "content": reply,
        "history": clean_history,
        "tools_used": [],
    })


# Backwards-compat: tests viejos llaman a _stream_ui_generic con prompt + label
def _stream_ui_generic(
    system_prompt: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    label: str = "UI",
) -> Generator[str, None, None]:
    ad_hoc = WorkerConfig(
        intent=label.lower(),
        display_name=label,
        prompt=system_prompt,
        tools=[],
        temperature=0.5,
        reasoning_effort="low",
    )
    yield from _stream_ui_worker(ad_hoc, user_message, conversation_history)


def _stream_data_worker(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Generator[str, None, None]:
    """Backwards-compat alias para el worker DATA (sigue usado por tests)."""
    yield from _stream_tooled_worker(
        _agent_config().get_worker("data"), user_message, conversation_history
    )


def _stream_tooled_worker(
    cfg: WorkerConfig,
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Generator[str, None, None]:
    """Streaming de un worker con function-calling. Lee tools, temperature,
    reasoning_effort y max_rounds desde ``cfg``."""
    messages: List[Dict[str, Any]] = [{"role": "system", "content": cfg.prompt}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    tools_schemas = get_schemas_for(cfg.tools)
    tools_used: List[str] = []
    short_name = cfg.display_name.split()[0] if cfg.display_name else "Worker"

    for round_num in range(cfg.max_rounds):
        # Thinking real: el agente está "pensando qué hacer" antes de la
        # llamada al LLM. Si el primer chunk del stream es texto, el frontend
        # cierra este step automáticamente al recibir el primer 'token' (oculta
        # los thinking y muestra el reply en streaming). Si el primer chunk es
        # un tool_call, emitimos el tool_result de este paso justo antes del
        # thinking del propio tool, dando continuidad realista.
        if round_num == 0:
            yield json.dumps({
                "type": "thinking",
                "description": f"{short_name} analizando tu pregunta",
                "phase": "reasoning",
                "round": round_num + 1,
            })
        else:
            phase_desc = "Sintetizando los datos obtenidos" if tools_used else "Replanteando la consulta"
            yield json.dumps({
                "type": "thinking",
                "description": phase_desc,
                "phase": "reasoning",
                "round": round_num + 1,
            })

        tool_choice = cfg.tool_choice_first_round if (round_num == 0 and not tools_used) else "auto"
        payload: Dict[str, Any] = {
            "messages": messages,
            "tools": tools_schemas,
            "tool_choice": tool_choice,
            "temperature": cfg.temperature,
        }
        if cfg.reasoning_effort:
            payload["reasoning_effort"] = cfg.reasoning_effort

        try:
            stream_iter = _api_call_streaming(_build_api_url(), payload)
            accumulated_content = ""
            accumulated_tool_calls: Optional[List[Dict[str, Any]]] = None
            finish_reason: Optional[str] = None
            for chunk in stream_iter:
                ctype = chunk.get("type")
                if ctype == "content":
                    text = chunk.get("text") or ""
                    if text:
                        accumulated_content += text
                        yield json.dumps({"type": "token", "content": text})
                elif ctype == "tool_calls":
                    accumulated_tool_calls = chunk.get("calls")
                elif ctype == "done":
                    finish_reason = chunk.get("finish_reason")
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

        tool_calls = accumulated_tool_calls
        if finish_reason == "tool_calls" or tool_calls:
            # Cerrar el thinking "analizando/sintetizando" con un tool_result
            # real que indique cuántas herramientas planea usar.
            n_tools = len(tool_calls or [])
            yield json.dumps({
                "type": "tool_result",
                "summary": f"Va a ejecutar {n_tools} {'herramienta' if n_tools == 1 else 'herramientas'}",
            })

            # Reconstruimos el message del assistant para añadirlo al historial
            messages.append({
                "role": "assistant",
                "content": accumulated_content if accumulated_content else None,
                "tool_calls": tool_calls or [],
            })

            for tc in (tool_calls or []):
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    fn_args = {}

                display_name = get_display_name(fn_name)
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
                    "tool_key": fn_name,
                    "collection_key": col_raw,
                    "has_filter": bool(fn_args.get("filter")),
                    "round": round_num + 1,
                })

                logger.info(f"🔧 Agente solicita: {fn_name}({fn_args})")
                result = _execute_tool_call(fn_name, fn_args)
                tools_used.append(fn_name)

                result_count = None
                try:
                    result_data = json.loads(result)
                    result_count = result_data.get("count", result_data.get("total", None))
                    if result_count is not None:
                        summary = f"{result_count} resultados obtenidos"
                    else:
                        summary = "Datos recibidos"
                except (json.JSONDecodeError, AttributeError):
                    summary = "Datos recibidos"

                yield json.dumps({
                    "type": "tool_result",
                    "summary": summary,
                    "count": result_count,
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            continue

        reply = accumulated_content or "No pude generar una respuesta."
        messages.append({"role": "assistant", "content": reply})
        clean_history = [m for m in messages if m.get("role") != "system"]
        tools_display = list(dict.fromkeys(get_display_name(t) for t in tools_used))

        yield json.dumps({
            "type": "reply",
            "content": reply,
            "history": clean_history,
            "tools_used": tools_display,
        })
        return

    yield json.dumps({
        "type": "error",
        "content": "Se alcanzó el límite de procesamiento. Reformula tu pregunta.",
    })
