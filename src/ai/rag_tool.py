"""
Tool RAG: búsqueda semántica de READMEs y descripciones de repositorios.

Se registra automáticamente con ``@tool`` al importarse, y queda
disponible para cualquier worker que la incluya en ``config/workers.yaml``.

Patrón de uso típico del agente:

    search_knowledge_base(
        query="variational quantum eigensolver",
        primary_language="Python",
        top_k=5,
    )
    → top 5 chunks de READMEs cuya semántica encaja con la consulta,
      restringidos al lenguaje pedido.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..core.logger import logger
from ..core.vector_search import vector_search
from .embedder import embed_one
from .tool_registry import tool


@tool(
    name="search_knowledge_base",
    description=(
        "Búsqueda semántica sobre los READMEs y descripciones reales de los "
        "repositorios indexados. Útil para responder preguntas cualitativas "
        "(\"¿qué hace este proyecto?\", \"¿qué diferencia hay entre A y B?\") "
        "o para descubrir repos por concepto (\"variational quantum solvers\"). "
        "NO usar para conteos exactos ni rankings — para eso usa run_aggregation."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Pregunta o concepto en lenguaje natural. "
                    "Ejemplo: \"librerías para circuit simulation\"."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": "Número máximo de fragmentos a devolver (1-20, default 5).",
                "default": 5,
            },
            "primary_language": {
                "type": "string",
                "description": (
                    "Filtra por lenguaje principal del repo (case sensitive como en GitHub: "
                    "Python, C++, Julia, Rust...). Opcional."
                ),
            },
            "min_stars": {
                "type": "integer",
                "description": "Filtra por nº mínimo de estrellas del repo. Opcional.",
            },
        },
        "required": ["query"],
    },
    display_name="Consultando conocimiento del ecosistema",
)
def search_knowledge_base(
    query: str,
    top_k: int = 5,
    primary_language: Optional[str] = None,
    min_stars: Optional[int] = None,
) -> str:
    """Realiza una búsqueda semántica + filtros estructurales y devuelve
    fragmentos con el origen del repo para que el agente pueda citarlos."""
    try:
        if not query or not query.strip():
            return json.dumps({"error": "Query vacía"})

        top_k = max(1, min(int(top_k), 20))

        # 1. Embedding de la query
        query_embedding = embed_one(query)

        # 2. Filtro estructural pre-vector
        pre_filter: Dict[str, Any] = {"source_type": "repository"}
        if primary_language:
            pre_filter["primary_language"] = primary_language
        if min_stars is not None and min_stars > 0:
            pre_filter["stargazer_count"] = {"$gte": int(min_stars)}

        # 3. Top-k cosine
        hits = vector_search(query_embedding, k=top_k, pre_filter=pre_filter)

        # 4. Curar la salida para minimizar tokens al worker
        results: List[Dict[str, Any]] = []
        for h in hits:
            results.append({
                "repo": h.get("repo_full_name") or h.get("repo_name") or "",
                "language": h.get("primary_language") or "Unknown",
                "stars": h.get("stargazer_count", 0),
                "section": h.get("section_path", ""),
                "score": round(h.get("score", 0.0), 4),
                # El texto se trunca para que el agente no se explaye demasiado
                "snippet": (h.get("text") or "")[:800],
            })

        logger.info(
            "🧠 search_knowledge_base(query=%r, lang=%s, min_stars=%s) → %d hits",
            query[:50], primary_language, min_stars, len(results),
        )
        return json.dumps(
            {"query": query, "count": len(results), "results": results},
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.error("search_knowledge_base error: %s", exc)
        return json.dumps({"error": str(exc)})
