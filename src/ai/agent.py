"""
Integración con Azure AI Foundry Agent.
Gestiona la creación del agente y el procesamiento de conversaciones
usando la Responses API con function calling.
"""
import json
import threading
from typing import Any, Dict, List, Optional

import requests
from azure.identity import DefaultAzureCredential

from ..core.config import config
from ..core.logger import logger
from .tool_functions import TOOL_FUNCTIONS

# Token cache con thread-safety
_credential = None
_credential_lock = threading.Lock()


# Definición de las tools para el agente (OpenAI function calling format)
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_top_repositories",
            "description": "Obtiene los repositorios top ordenados por un campo específico",
            "parameters": {
                "type": "object",
                "properties": {
                    "sort_by": {
                        "type": "string",
                        "enum": ["stars_count", "forks_count", "quantum_score", "collaboration_score", "contributors_count"],
                        "description": "Campo por el cual ordenar",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Número de resultados (máx 20)",
                        "default": 10,
                    },
                    "language": {
                        "type": "string",
                        "description": "Filtrar por lenguaje de programación (ej: Python, Rust, Julia)",
                    },
                },
                "required": ["sort_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_organizations",
            "description": "Obtiene las organizaciones top del ecosistema cuántico",
            "parameters": {
                "type": "object",
                "properties": {
                    "sort_by": {
                        "type": "string",
                        "enum": ["quantum_focus_score", "members_count", "quantum_repositories_count", "public_repos_count"],
                        "description": "Campo por el cual ordenar",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Número de resultados (máx 20)",
                        "default": 10,
                    },
                },
                "required": ["sort_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_users",
            "description": "Obtiene los desarrolladores más destacados del ecosistema cuántico",
            "parameters": {
                "type": "object",
                "properties": {
                    "sort_by": {
                        "type": "string",
                        "enum": ["quantum_expertise_score", "followers_count", "total_commit_contributions", "total_pr_contributions", "public_repos_count"],
                        "description": "Campo por el cual ordenar",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Número de resultados (máx 20)",
                        "default": 10,
                    },
                },
                "required": ["sort_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_general_stats",
            "description": "Obtiene estadísticas generales del ecosistema: totales de repos, orgs, usuarios, lenguajes más usados, etc.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_entity",
            "description": "Busca un repositorio, organización o usuario específico por nombre",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "enum": ["repository", "organization", "user"],
                        "description": "Tipo de entidad a buscar",
                    },
                    "query": {
                        "type": "string",
                        "description": "Nombre o login a buscar (búsqueda parcial)",
                    },
                },
                "required": ["entity_type", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_language_distribution",
            "description": "Obtiene la distribución de lenguajes de programación en los repositorios cuánticos",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Número de lenguajes a devolver",
                        "default": 15,
                    },
                },
                "required": [],
            },
        },
    },
]

SYSTEM_PROMPT = """Eres el asistente de datos de Entangle, una plataforma de análisis del ecosistema de computación cuántica en GitHub.

Tienes acceso a una base de datos con tres colecciones:
- **repositories**: Repositorios de GitHub relacionados con computación cuántica. Campos clave: name, owner, stars_count, forks_count, language, topics, quantum_score, collaboration_score, is_quantum, created_at, updated_at, contributors_count.
- **organizations**: Organizaciones de GitHub vinculadas al ecosistema cuántico. Campos clave: login, name, members_count, public_repos_count, quantum_focus_score, quantum_repositories_count, is_verified, is_active.
- **users**: Desarrolladores del ecosistema cuántico. Campos clave: login, name, followers_count, public_repos_count, total_commit_contributions, total_pr_contributions, quantum_expertise_score, is_quantum_contributor, top_languages, organizations.

Reglas:
1. Usa SIEMPRE las funciones disponibles para consultar datos reales. NUNCA inventes datos.
2. Si no tienes una función para responder algo, dilo honestamente.
3. Responde en el mismo idioma que el usuario.
4. Sé conciso pero informativo. Usa tablas markdown cuando muestres rankings.
5. Cuando des rankings o tops, muestra máximo 10 resultados salvo que el usuario pida más.
6. Si el usuario pregunta algo que no está relacionado con el ecosistema cuántico de GitHub, redirige amablemente al tema."""


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


def _execute_tool_call(function_name: str, arguments: Dict[str, Any]) -> str:
    """Ejecuta una función local según la solicitud del agente."""
    func = TOOL_FUNCTIONS.get(function_name)
    if not func:
        return json.dumps({"error": f"Función desconocida: {function_name}"})
    try:
        return func(**arguments)
    except Exception as e:
        logger.error(f"Error ejecutando {function_name}: {e}")
        return json.dumps({"error": str(e)})


def chat(
    user_message: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Envía un mensaje al agente de Foundry y procesa la respuesta,
    incluyendo el loop de function calling.

    Args:
        user_message: Pregunta del usuario.
        conversation_history: Historial previo de mensajes (opcional).

    Returns:
        dict con claves: "reply" (str), "history" (list), "tools_used" (list[str])
    """
    endpoint = config.AZURE_AI_ENDPOINT
    if not endpoint:
        return {"reply": "El servicio de IA no está configurado.", "history": [], "tools_used": []}

    # Construir mensajes
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    tools_used: List[str] = []
    max_rounds = 5  # Prevenir loops infinitos de function calling

    for _ in range(max_rounds):
        payload = {
            "messages": messages,
            "tools": AGENT_TOOLS,
            "tool_choice": "auto",
            "temperature": 0.3,
        }

        try:
            url = (
                f"{endpoint}/openai/deployments/{config.AZURE_AI_DEPLOYMENT}"
                f"/chat/completions?api-version=2024-10-21"
            )
            response = requests.post(
                url,
                headers=_get_auth_headers(),
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.Timeout:
            logger.error("Timeout al llamar al agente de IA")
            return {"reply": "Lo siento, el servicio tardó demasiado en responder. Intenta de nuevo.", "history": [], "tools_used": tools_used}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error llamando al agente de IA: {e}")
            return {"reply": "Error al conectar con el servicio de IA.", "history": [], "tools_used": tools_used}

        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason")

        # Si el modelo quiere llamar funciones
        tool_calls = message.get("tool_calls")
        if finish_reason == "tool_calls" or tool_calls:
            # Añadir respuesta del asistente con las tool_calls al historial
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

            # Continuar el loop para que el modelo procese los resultados
            continue

        # Respuesta final del modelo (sin tool calls)
        reply = message.get("content", "No pude generar una respuesta.")
        messages.append({"role": "assistant", "content": reply})

        # Devolver historial limpio (sin system prompt)
        clean_history = [m for m in messages if m.get("role") != "system"]

        return {
            "reply": reply,
            "history": clean_history,
            "tools_used": tools_used,
        }

    # Si se alcanzó el máximo de rounds
    return {
        "reply": "Se alcanzó el límite de procesamiento. Por favor, reformula tu pregunta.",
        "history": [],
        "tools_used": tools_used,
    }
