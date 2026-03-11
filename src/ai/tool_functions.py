"""
Funciones de consulta a la base de datos para el agente de IA.
El agente tiene acceso directo a MongoDB mediante query_database,
run_aggregation y get_collection_schema — puede construir cualquier
consulta que necesite sin depender de funciones predefinidas.
"""
import json
from typing import Any, Dict, List, Optional

from ..core.mongo_repository import MongoRepository
from ..core.logger import logger


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


def query_database(
    collection: str,
    filter: Optional[Dict[str, Any]] = None,
    projection: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, int]] = None,
    limit: int = 10,
) -> str:
    """
    Ejecuta una consulta flexible (find) sobre cualquiera de las colecciones.
    El agente puede construir filtros, proyecciones y sort libremente.
    Solo lectura — no modifica datos.
    """
    try:
        if collection not in _COLLECTIONS:
            return json.dumps({"error": f"Colección no válida: {collection}. Usa: {list(_COLLECTIONS.keys())}"})

        repo = _COLLECTIONS[collection]
        limit = min(max(limit, 1), _MAX_RESULTS)

        # Convertir sort dict {"field": -1} a lista de tuplas [("field", -1)]
        sort_list = None
        if sort:
            sort_list = [(k, v) for k, v in sort.items()]

        # Excluir _id por defecto si no se especificó projection
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


def run_aggregation(
    collection: str,
    pipeline: List[Dict[str, Any]],
) -> str:
    """
    Ejecuta un pipeline de aggregation sobre una colección.
    Permite al agente hacer cálculos complejos: $group, $match, $sort,
    $unwind, $project, $lookup, etc.
    Solo lectura — operaciones de escritura ($out, $merge) están prohibidas.
    """
    try:
        if collection not in _COLLECTIONS:
            return json.dumps({"error": f"Colección no válida: {collection}. Usa: {list(_COLLECTIONS.keys())}"})

        # Bloquear stages de escritura
        FORBIDDEN_STAGES = {"$out", "$merge"}
        for stage in pipeline:
            for key in stage:
                if key in FORBIDDEN_STAGES:
                    return json.dumps({"error": f"Stage '{key}' no permitido (solo lectura)."})

        # Forzar un límite si no hay $limit en el pipeline
        has_limit = any("$limit" in stage for stage in pipeline)
        if not has_limit:
            pipeline.append({"$limit": _MAX_RESULTS})

        repo = _COLLECTIONS[collection]
        cursor = repo.collection.aggregate(pipeline)
        results = list(cursor)

        # Limpiar _id de ObjectId para serialización
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


def get_collection_schema(collection: str) -> str:
    """
    Devuelve un documento de ejemplo de una colección para que el agente
    entienda la estructura y los campos disponibles.
    """
    try:
        if collection not in _COLLECTIONS:
            return json.dumps({"error": f"Colección no válida: {collection}. Usa: {list(_COLLECTIONS.keys())}"})

        repo = _COLLECTIONS[collection]
        # Obtener un documento de muestra
        sample = repo.find_one(query={}, projection={"_id": 0})
        if not sample:
            return json.dumps({"collection": collection, "sample": None, "message": "Colección vacía"})

        # Extraer estructura: nombre de campo → tipo
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


# Registro de funciones disponibles para el agente
TOOL_FUNCTIONS = {
    "query_database": query_database,
    "run_aggregation": run_aggregation,
    "get_collection_schema": get_collection_schema,
}
