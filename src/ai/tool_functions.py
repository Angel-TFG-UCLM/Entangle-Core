"""
Funciones de consulta a la base de datos para el agente de IA.

Cada función se registra automáticamente como tool al importar este módulo,
gracias al decorador ``@tool``. El agente lee la lista por configuración
(``config/workers.yaml``), de modo que añadir una tool nueva no requiere
tocar el agente: basta con decorar la función.
"""
import json
from typing import Any, Dict, List, Optional

from ..core.logger import logger
from ..core.mongo_repository import MongoRepository
from .tool_registry import register_tool, tool


# Repositorios de datos (singleton por colección)
_repos_repo = MongoRepository("repositories")
_orgs_repo = MongoRepository("organizations")
_users_repo = MongoRepository("users")
_metrics_repo = MongoRepository("metrics")

# Mapa de colecciones permitidas
_COLLECTIONS = {
    "repositories": _repos_repo,
    "organizations": _orgs_repo,
    "users": _users_repo,
    "metrics": _metrics_repo,
}

# Límite máximo de documentos por consulta
_MAX_RESULTS = 50


@tool(
    name="query_database",
    description=(
        "Ejecuta una consulta flexible (find) sobre una colección de MongoDB. "
        "Permite construir filtros, proyecciones y sort libremente. Solo lectura."
    ),
    parameters={
        "type": "object",
        "properties": {
            "collection": {
                "type": "string",
                "enum": ["repositories", "organizations", "users", "metrics"],
                "description": "Colección a consultar",
            },
            "filter": {
                "type": "object",
                "description": (
                    "Filtro de MongoDB (JSON). Ejemplo: "
                    "{\"stargazer_count\": {\"$gt\": 100}} o "
                    "{\"primary_language\": \"Python\"}. "
                    "Soporta $gt, $gte, $lt, $lte, $ne, $in, $regex, $exists, $or, $and, etc."
                ),
            },
            "projection": {
                "type": "object",
                "description": (
                    "Campos a incluir/excluir. "
                    "Ejemplo: {\"name\": 1, \"stargazer_count\": 1} para incluir solo esos campos."
                ),
            },
            "sort": {
                "type": "object",
                "description": (
                    "Ordenamiento. Ejemplo: {\"stargazer_count\": -1} para ordenar por estrellas descendente. "
                    "Usa -1 (DESC) o 1 (ASC)."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Máximo de resultados (1-50, default 10)",
                "default": 10,
            },
        },
        "required": ["collection"],
    },
    display_name="Consultando base de datos",
)
def query_database(
    collection: str,
    filter: Optional[Dict[str, Any]] = None,
    projection: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, int]] = None,
    limit: int = 10,
) -> str:
    """Ejecuta una consulta flexible (find). Solo lectura."""
    try:
        if collection not in _COLLECTIONS:
            return json.dumps({"error": f"Colección no válida: {collection}. Usa: {list(_COLLECTIONS.keys())}"})

        repo = _COLLECTIONS[collection]
        limit = min(max(limit, 1), _MAX_RESULTS)

        sort_list = None
        if sort:
            sort_list = [(k, v) for k, v in sort.items()]

        if projection is None:
            projection = {"_id": 0}
        elif "_id" not in projection:
            projection["_id"] = 0

        docs = repo.find(
            query=filter or {},
            projection=projection,
            sort=sort_list,
            limit=limit,
        )

        results = list(docs)
        logger.info(f"🔍 query_database({collection}) filter={filter} sort={sort} → {len(results)} docs")

        return json.dumps(
            {"collection": collection, "count": len(results), "results": results},
            default=str,
        )

    except Exception as e:
        logger.error(f"Error en query_database: {e}")
        return json.dumps({"error": str(e)})


@tool(
    name="run_aggregation",
    description=(
        "Ejecuta un pipeline de aggregation de MongoDB sobre una colección. "
        "Permite cálculos complejos como $group, $match, $sort, $unwind, $project, $bucket, $facet, etc. "
        "Solo lectura ($out/$merge prohibidos)."
    ),
    parameters={
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
                "description": (
                    "Array de stages de aggregation. Ejemplo: "
                    "[{\"$match\": {\"stargazer_count\": {\"$gt\": 0}}}, "
                    "{\"$sort\": {\"stargazer_count\": -1}}, {\"$limit\": 10}]"
                ),
            },
        },
        "required": ["collection", "pipeline"],
    },
    display_name="Ejecutando análisis agregado",
)
def run_aggregation(
    collection: str,
    pipeline: List[Dict[str, Any]],
) -> str:
    """Ejecuta un pipeline de aggregation. Solo lectura."""
    try:
        if collection not in _COLLECTIONS:
            return json.dumps({"error": f"Colección no válida: {collection}. Usa: {list(_COLLECTIONS.keys())}"})

        FORBIDDEN_STAGES = {"$out", "$merge"}
        for stage in pipeline:
            for key in stage:
                if key in FORBIDDEN_STAGES:
                    return json.dumps({"error": f"Stage '{key}' no permitido (solo lectura)."})

        has_limit = any("$limit" in stage for stage in pipeline)
        if not has_limit:
            pipeline.append({"$limit": _MAX_RESULTS})

        repo = _COLLECTIONS[collection]
        cursor = repo.collection.aggregate(pipeline)
        results = list(cursor)

        for doc in results:
            if "_id" in doc and not isinstance(doc["_id"], (str, int, float, bool, type(None))):
                doc["_id"] = str(doc["_id"])

        logger.info(f"🔍 run_aggregation({collection}) stages={len(pipeline)} → {len(results)} docs")

        return json.dumps(
            {"collection": collection, "count": len(results), "results": results},
            default=str,
        )

    except Exception as e:
        logger.error(f"Error en run_aggregation: {e}")
        return json.dumps({"error": str(e)})


@tool(
    name="get_collection_schema",
    description=(
        "Devuelve un documento de ejemplo y el esquema (campos y tipos) de una colección. "
        "Útil para entender la estructura antes de hacer consultas."
    ),
    parameters={
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
    display_name="Inspeccionando estructura de datos",
)
def get_collection_schema(collection: str) -> str:
    """Devuelve un documento de muestra y el esquema de campos."""
    try:
        if collection not in _COLLECTIONS:
            return json.dumps({"error": f"Colección no válida: {collection}. Usa: {list(_COLLECTIONS.keys())}"})

        repo = _COLLECTIONS[collection]
        sample = repo.find_one(query={}, projection={"_id": 0})
        if not sample:
            return json.dumps({"collection": collection, "sample": None, "message": "Colección vacía"})

        schema = {}
        for key, value in sample.items():
            if isinstance(value, dict):
                schema[key] = {k: type(v).__name__ for k, v in value.items()}
            elif isinstance(value, list):
                elem_type = type(value[0]).__name__ if value else "empty"
                schema[key] = f"list[{elem_type}]"
            else:
                schema[key] = type(value).__name__

        return json.dumps(
            {"collection": collection, "schema": schema, "sample_document": sample},
            default=str,
        )

    except Exception as e:
        logger.error(f"Error en get_collection_schema: {e}")
        return json.dumps({"error": str(e)})


# Backwards-compat: las versiones antiguas del código importan este dict.
# Se mantiene como capa de compatibilidad para tests existentes y módulos
# que aún no se han migrado al registry. Cualquier código nuevo debería
# usar ``tool_registry.get_callable(name)`` en su lugar.
TOOL_FUNCTIONS = {
    "query_database": query_database,
    "run_aggregation": run_aggregation,
    "get_collection_schema": get_collection_schema,
}

