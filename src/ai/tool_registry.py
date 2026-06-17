"""
Tool Registry — registro declarativo de herramientas invocables por el agente.

Permite definir funciones con un decorador `@tool` que se autoregistran junto
con su nombre, esquema OpenAI function-calling y nombre de display. El agente
no necesita ya conocer la lista de tools por anticipado: la lee del registro
cada vez que despacha un worker.

Diseño:
    @tool(
        name="query_database",
        description="...",
        parameters={...},
        display_name="Consultando base de datos",
    )
    def query_database(collection, filter, ...): ...

API pública:
    register_tool(name, schema, fn, display_name)  -- usado por @tool
    get_tool(name) -> ToolEntry
    get_callable(name) -> Callable
    get_schemas_for(names) -> List[dict]            -- para `tools` del agente
    get_display_name(name) -> str
    list_tools() -> List[str]                       -- para introspección
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class ToolEntry:
    """Entrada del registro de tools."""
    name: str
    fn: Callable[..., Any]
    schema: Dict[str, Any]
    display_name: str


_REGISTRY: Dict[str, ToolEntry] = {}


def register_tool(
    name: str,
    fn: Callable[..., Any],
    *,
    description: str,
    parameters: Dict[str, Any],
    display_name: Optional[str] = None,
) -> None:
    """Registra una función como tool invocable por el agente.

    Si ya existe una tool con ``name``, se sobrescribe. Esto permite
    redefiniciones controladas en tests sin contaminar el estado global.
    """
    schema = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }
    _REGISTRY[name] = ToolEntry(
        name=name,
        fn=fn,
        schema=schema,
        display_name=display_name or name,
    )


def tool(
    *,
    name: str,
    description: str,
    parameters: Dict[str, Any],
    display_name: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorador: marca una función como tool y la registra al importarse."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        register_tool(
            name,
            fn,
            description=description,
            parameters=parameters,
            display_name=display_name,
        )
        return fn
    return decorator


def get_tool(name: str) -> Optional[ToolEntry]:
    return _REGISTRY.get(name)


def get_callable(name: str) -> Optional[Callable[..., Any]]:
    entry = _REGISTRY.get(name)
    return entry.fn if entry else None


def get_schemas_for(names: Iterable[str]) -> List[Dict[str, Any]]:
    """Devuelve los esquemas OpenAI de las tools indicadas, en el mismo
    orden. Tools desconocidas se ignoran silenciosamente (con warning) para
    no romper el agente si el YAML referencia algo no implementado todavía."""
    schemas: List[Dict[str, Any]] = []
    for n in names:
        entry = _REGISTRY.get(n)
        if entry is not None:
            schemas.append(entry.schema)
    return schemas


def get_display_name(name: str) -> str:
    entry = _REGISTRY.get(name)
    return entry.display_name if entry else name


def list_tools() -> List[str]:
    """Lista los nombres de tools registradas (orden estable de inserción)."""
    return list(_REGISTRY.keys())


def _reset_for_tests() -> None:
    """Limpia el registro. SOLO para tests; no usar en producción."""
    _REGISTRY.clear()
