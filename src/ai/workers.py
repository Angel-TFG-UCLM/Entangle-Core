"""
Carga y validación de la configuración del agente Router-Worker.

Lee ``config/workers.yaml`` al importar el módulo y expone ``RouterConfig``
y ``WorkerConfig`` (dataclasses inmutables) que ``agent.py`` consume para
despachar peticiones sin lógica hardcodeada por intent.

Decisión de diseño: los prompts siguen viviendo como constantes en
``prompts.py``. El YAML solo guarda el nombre del constante. Razón:
mantenemos el control de versiones cómodo con Python (con resaltado de
sintaxis para los placeholders del prompt) sin sacrificar la modularidad
config-driven del router y los tools.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from . import prompts as _prompts_module
from ..core.logger import logger


# Localización del YAML — calculada relativamente al repo root para que
# funcione tanto en local (``python -m src...``) como en el contenedor
# Docker (la imagen copia ``config/`` al WORKDIR).
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _BACKEND_ROOT / "config" / "workers.yaml"


@dataclass(frozen=True)
class RouterConfig:
    prompt: str
    intents: List[str]
    fallback: str
    reasoning_effort: str = "minimal"
    max_completion_tokens: int = 10

    def __post_init__(self) -> None:
        if self.fallback not in self.intents:
            raise ValueError(
                f"Router fallback '{self.fallback}' no está en intents {self.intents}"
            )


@dataclass(frozen=True)
class WorkerConfig:
    intent: str
    display_name: str
    prompt: str
    tools: List[str] = field(default_factory=list)
    temperature: float = 0.5
    reasoning_effort: str = "low"
    tool_choice_first_round: str = "auto"
    max_rounds: int = 25

    @property
    def has_tools(self) -> bool:
        return bool(self.tools)


@dataclass(frozen=True)
class AgentConfig:
    """Vista agregada del YAML completo."""
    router: RouterConfig
    workers: Dict[str, WorkerConfig]

    def get_worker(self, intent: str) -> WorkerConfig:
        worker = self.workers.get(intent)
        if worker is None:
            # Cae al fallback del router si el intent no existe
            return self.workers[self.router.fallback]
        return worker


def _resolve_prompt(prompt_constant: str) -> str:
    """Obtiene el valor del constante de prompts.py por nombre.
    Falla con un error claro si el constante no existe — así un error de
    configuración se detecta al arrancar la app, no en runtime."""
    prompt = getattr(_prompts_module, prompt_constant, None)
    if prompt is None:
        raise ValueError(
            f"prompts.{prompt_constant} no existe. Revisa workers.yaml."
        )
    if not isinstance(prompt, str):
        raise TypeError(
            f"prompts.{prompt_constant} debe ser str, es {type(prompt).__name__}."
        )
    return prompt


def _build_router(raw: Dict[str, Any]) -> RouterConfig:
    return RouterConfig(
        prompt=_resolve_prompt(raw["prompt_constant"]),
        intents=list(raw.get("intents", [])),
        fallback=str(raw.get("fallback", "")).lower(),
        reasoning_effort=str(raw.get("reasoning_effort", "minimal")),
        max_completion_tokens=int(raw.get("max_completion_tokens", 10)),
    )


def _build_worker(intent: str, raw: Dict[str, Any]) -> WorkerConfig:
    return WorkerConfig(
        intent=intent,
        display_name=str(raw.get("display_name", intent.title())),
        prompt=_resolve_prompt(raw["prompt_constant"]),
        tools=list(raw.get("tools", []) or []),
        temperature=float(raw.get("temperature", 0.5)),
        reasoning_effort=str(raw.get("reasoning_effort", "low")),
        tool_choice_first_round=str(raw.get("tool_choice_first_round", "auto")),
        max_rounds=int(raw.get("max_rounds", 25)),
    )


def load_agent_config(path: Optional[Path] = None) -> AgentConfig:
    """Carga ``workers.yaml`` y devuelve la configuración validada.

    Usa ``functools.lru_cache`` para evitar re-leer el fichero en cada
    petición. En tests se puede invocar ``load_agent_config.cache_clear()``
    si fuera necesario, pero la inmutabilidad de los dataclasses ya cubre
    la mayoría de casos sin necesidad de invalidación.
    """
    cfg_path = path or _DEFAULT_CONFIG_PATH
    return _load_cached(str(cfg_path))


@lru_cache(maxsize=4)
def _load_cached(path_str: str) -> AgentConfig:
    cfg_path = Path(path_str)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"No se encuentra workers.yaml en {cfg_path}. "
            "Comprueba que config/ se copia a la imagen Docker."
        )
    with cfg_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"workers.yaml debe ser un dict en raíz, es {type(raw).__name__}")

    router = _build_router(raw["router"])
    workers_raw = raw.get("workers", {}) or {}
    workers = {
        intent: _build_worker(intent, worker_raw)
        for intent, worker_raw in workers_raw.items()
    }

    if router.fallback not in workers:
        raise ValueError(
            f"Router fallback '{router.fallback}' no tiene worker definido."
        )

    logger.info(
        "✅ Agent config cargada: router fallback=%s, workers=%s",
        router.fallback,
        list(workers.keys()),
    )
    return AgentConfig(router=router, workers=workers)
