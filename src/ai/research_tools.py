"""
Tools de investigación externa para el worker DEEP_RESEARCH.

Provee dos tools complementarias que dan al agente acceso controlado a
internet sin alucinar:

  - ``web_search`` → Tavily Search API: web general (noticias, blogs,
    issues de GitHub, docs). Devuelve fragmentos + URLs.
  - ``search_arxiv`` → arXiv API: papers académicos cuánticos. Sin key,
    sin límite, devuelve título + resumen + autores + URL.

Diseño:
  - Si ``TAVILY_API_KEY`` no está configurado, ``web_search`` devuelve un
    JSON con error explicativo en vez de petar — esto permite que el
    agente conozca su limitación y avise al usuario.
  - arXiv siempre disponible; cuota generosa, sin auth.
  - Todas las respuestas vienen "limpias": el agente recibe solo lo que
    necesita para responder y citar.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import requests

from ..core.logger import logger
from .tool_registry import tool


# ─────────────────────────────────────────────────────────────
# Tavily (web search optimizado para LLMs)
# ─────────────────────────────────────────────────────────────
_TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
_TAVILY_URL = "https://api.tavily.com/search"
_TAVILY_TIMEOUT_S = 30


@tool(
    name="web_search",
    description=(
        "Búsqueda web (Tavily) optimizada para LLMs: devuelve fragmentos "
        "indexados de webs, blogs, issues de GitHub y documentación. Útil "
        "para preguntas sobre NOTICIAS o información POSTERIOR a la base "
        "de datos (la BD se actualiza periódicamente). NO usar para "
        "preguntas sobre repos que ya tienes indexados — para eso usa "
        "``search_knowledge_base``. SIEMPRE cita la URL en la respuesta."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Consulta en lenguaje natural. Ejemplo: \"IBM Heron processor release date\".",
            },
            "max_results": {
                "type": "integer",
                "description": "Máx. resultados (1-10, default 5).",
                "default": 5,
            },
            "include_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Limita la búsqueda a estos dominios (ej: [\"github.com\", \"ibm.com\"]). Opcional.",
            },
        },
        "required": ["query"],
    },
    display_name="Buscando en la web",
)
def web_search(
    query: str,
    max_results: int = 5,
    include_domains: Optional[List[str]] = None,
) -> str:
    """Llamada a Tavily Search API. Devuelve JSON estructurado con
    title/url/content/score."""
    if not _TAVILY_API_KEY:
        return json.dumps({
            "error": "web_search no disponible (TAVILY_API_KEY no configurada)",
            "hint": "El agente debe informar al usuario que no puede buscar en internet en este momento.",
        })

    payload = {
        "api_key": _TAVILY_API_KEY,
        "query": query.strip(),
        "search_depth": "basic",
        "max_results": max(1, min(int(max_results), 10)),
        "include_answer": False,
        "include_raw_content": False,
    }
    if include_domains:
        payload["include_domains"] = [str(d) for d in include_domains if d]

    try:
        t0 = time.time()
        resp = requests.post(_TAVILY_URL, json=payload, timeout=_TAVILY_TIMEOUT_S)
        elapsed = time.time() - t0
        resp.raise_for_status()
        data = resp.json()

        # Curar la respuesta — solo lo útil
        results: List[Dict[str, Any]] = []
        for item in data.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": (item.get("content") or "")[:600],
                "score": round(item.get("score", 0.0), 4),
            })

        logger.info(
            "🌐 web_search(%r) → %d hits in %.1fs",
            query[:50], len(results), elapsed,
        )
        return json.dumps(
            {"query": query, "count": len(results), "results": results},
            ensure_ascii=False,
        )
    except requests.RequestException as e:
        logger.error("web_search failed: %s", e)
        return json.dumps({"error": f"web_search falló: {e}"})


# ─────────────────────────────────────────────────────────────
# arXiv (papers académicos, gratis, sin key)
# ─────────────────────────────────────────────────────────────
_ARXIV_URL = "https://export.arxiv.org/api/query"
_ARXIV_TIMEOUT_S = 15                # bajamos: si tarda más de 15s es señal de degradación
_ARXIV_MAX_RETRIES = 5               # solo se aplica a 429s; timeouts mueren a los 2
_ARXIV_BACKOFFS_S = (5, 10, 15, 20, 30)


@tool(
    name="search_arxiv",
    description=(
        "Busca papers académicos en arXiv. Devuelve título, autores, "
        "resumen y URL del PDF. Usar SOLO para preguntas sobre "
        "investigación científica reciente (computación cuántica, "
        "algoritmos, hardware, criptografía cuántica). Citar siempre "
        "el URL completo en la respuesta."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Consulta en inglés (arXiv indexa principalmente en EN). "
                    "Ejemplo: \"variational quantum eigensolver hardware noise\"."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Máximo resultados (1-10, default 5).",
                "default": 5,
            },
            "category": {
                "type": "string",
                "description": (
                    "Categoría arXiv para restringir (opcional). "
                    "Ejemplos: ``quant-ph`` (cuántica), ``cs.CR`` (criptografía), ``cs.LG`` (ML)."
                ),
            },
        },
        "required": ["query"],
    },
    display_name="Buscando papers en arXiv",
)
def search_arxiv(
    query: str,
    max_results: int = 5,
    category: Optional[str] = None,
) -> str:
    """Llamada a la API pública de arXiv. Parsea el feed Atom y devuelve
    JSON estructurado para el agente.

    arXiv tiene un rate-limit estricto (~1 req cada 3s por IP global).
    Implementa retry exponencial 3x con backoff 2s/4s/8s en caso de 429.
    """
    import xml.etree.ElementTree as ET

    search_query = query.strip()
    if category:
        search_query = f"cat:{category} AND ({search_query})"

    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max(1, min(int(max_results), 10)),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    # arXiv pide en sus términos un User-Agent identificable.
    headers = {
        "User-Agent": "Entangle-Quantum-Research/1.0 (https://entangle.uclm.es)"
    }

    last_exc: Optional[Exception] = None
    resp = None
    elapsed = 0.0
    # Estrategia: 429 vale la pena reintentar (rate limit transitorio). Pero
    # timeouts/errores de conexión indican que arXiv está degradado y esperar
    # no ayuda — mejor caer antes a Tavily. Damos 2 retries cortos para
    # timeouts y hasta MAX_RETRIES para 429s.
    timeout_attempts = 0
    MAX_TIMEOUT_RETRIES = 2

    for attempt in range(_ARXIV_MAX_RETRIES):
        try:
            t0 = time.time()
            resp = requests.get(
                _ARXIV_URL, params=params, headers=headers, timeout=_ARXIV_TIMEOUT_S,
            )
            elapsed = time.time() - t0
            if resp.status_code == 429:
                wait = _ARXIV_BACKOFFS_S[min(attempt, len(_ARXIV_BACKOFFS_S) - 1)]
                logger.warning(
                    "📚 arXiv 429 (attempt %d/%d) — esperando %ds antes de reintentar",
                    attempt + 1, _ARXIV_MAX_RETRIES, wait,
                )
                time.sleep(wait)
                last_exc = requests.HTTPError(f"429 attempt {attempt + 1}")
                continue
            resp.raise_for_status()
            break
        except (requests.Timeout, requests.ConnectionError) as e:
            # Timeout/conexión: arXiv degradado. NO insistir mucho — caer a Tavily.
            timeout_attempts += 1
            last_exc = e
            if timeout_attempts >= MAX_TIMEOUT_RETRIES:
                logger.error(
                    "search_arxiv: %d timeouts consecutivos — abortando y delegando a web_search",
                    timeout_attempts,
                )
                return json.dumps({
                    "error": (
                        "arXiv API no responde (timeouts). Probablemente está sobrecargado. "
                        "Usa web_search en su lugar."
                    ),
                })
            wait = 3  # pausa corta para no martillear si está caído
            logger.warning(
                "📚 arXiv timeout (attempt %d): %s — retry rápido en %ds",
                attempt + 1, e, wait,
            )
            time.sleep(wait)
            continue
        except requests.RequestException as e:
            last_exc = e
            if attempt < _ARXIV_MAX_RETRIES - 1:
                wait = _ARXIV_BACKOFFS_S[min(attempt, len(_ARXIV_BACKOFFS_S) - 1)]
                logger.warning(
                    "📚 arXiv error (attempt %d/%d): %s — retry en %ds",
                    attempt + 1, _ARXIV_MAX_RETRIES, e, wait,
                )
                time.sleep(wait)
                continue
            logger.error("search_arxiv failed after %d retries: %s", _ARXIV_MAX_RETRIES, e)
            return json.dumps({
                "error": (
                    "arXiv API no respondió tras varios reintentos. Usa web_search como fallback."
                ),
            })

    if resp is None or resp.status_code != 200:
        return json.dumps({
            "error": f"arXiv no respondió OK: {last_exc}",
        })

    # Parse Atom feed
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        return json.dumps({"error": f"arXiv devolvió XML no válido: {e}"})

    entries = root.findall("atom:entry", ns)
    results: List[Dict[str, Any]] = []
    for entry in entries:
        title_el = entry.find("atom:title", ns)
        summary_el = entry.find("atom:summary", ns)
        id_el = entry.find("atom:id", ns)
        published_el = entry.find("atom:published", ns)
        authors = [
            (a.findtext("atom:name", default="", namespaces=ns) or "").strip()
            for a in entry.findall("atom:author", ns)
        ]

        title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""
        summary = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else ""
        url = (id_el.text or "").strip() if id_el is not None else ""
        published = (published_el.text or "").strip() if published_el is not None else ""

        results.append({
            "title": title,
            "authors": authors,
            "summary": summary[:800],
            "url": url,
            "published": published[:10],  # YYYY-MM-DD
        })

    logger.info(
        "📚 search_arxiv(%r) → %d papers in %.1fs",
        query[:50], len(results), elapsed,
    )
    return json.dumps(
        {"query": query, "count": len(results), "results": results},
        ensure_ascii=False,
    )
