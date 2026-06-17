"""
Módulo de búsqueda semántica sobre Azure Cosmos DB for MongoDB vCore.

Provee:
  - ``ensure_vector_index()``: idempotente, crea el índice vectorial IVF
    sobre ``repos_chunks.embedding`` si no existe.
  - ``vector_search(query_embedding, k, filter)``: realiza top-k cosine
    similarity sobre la colección, aceptando filtros estructurados extra
    (idioma, mínimo de stars, etc.) que se aplican antes del search.

Decisiones de diseño:
  - Algoritmo: ``vector-ivf`` (Inverted File). Suficiente para ~5K chunks,
    bajo coste de RAM. HNSW solo merece la pena con cientos de miles.
  - ``numLists``: regla práctica = sqrt(N), con N ≈ chunks esperados.
    Para 3.5K chunks → ~60 lists; redondeo a 64 para alineación.
  - Dimensión: 1536 (la del modelo ``text-embedding-3-small`` que ya
    desplegamos en Azure AI Foundry).
  - Similitud: ``cosine``, la única que funciona bien con embeddings
    normalizados de OpenAI.

Referencias:
  https://learn.microsoft.com/azure/cosmos-db/mongodb/vcore/vector-search
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pymongo.errors import OperationFailure

from .db import get_database
from .logger import logger


CHUNKS_COLLECTION = "repos_chunks"
EMBEDDING_FIELD = "embedding"
EMBEDDING_DIM = 1536
VECTOR_INDEX_NAME = "vector_repos_chunks"
NUM_LISTS = 64  # ~sqrt(chunks) — válido hasta ~10K chunks


def ensure_vector_index() -> bool:
    """Garantiza que el índice vectorial y los índices auxiliares existen
    sobre ``repos_chunks``.

    Cosmos for MongoDB vCore exige que los campos usados como ``filter``
    del ``$search.cosmosSearch`` tengan también un índice convencional
    (B-tree). Si faltan, las búsquedas con filtros fallan con HTTP 2
    "The index for filter path X was not found".
    """
    db = get_database()
    coll = db[CHUNKS_COLLECTION]

    # 1. Índice vectorial (idempotente)
    try:
        indexes = list(coll.list_indexes())
    except OperationFailure as e:
        logger.error("No pude leer índices de %s: %s", CHUNKS_COLLECTION, e)
        raise
    existing_names = {idx.get("name") for idx in indexes}

    if VECTOR_INDEX_NAME not in existing_names:
        cmd = {
            "createIndexes": CHUNKS_COLLECTION,
            "indexes": [
                {
                    "name": VECTOR_INDEX_NAME,
                    "key": {EMBEDDING_FIELD: "cosmosSearch"},
                    "cosmosSearchOptions": {
                        "kind": "vector-ivf",
                        "numLists": NUM_LISTS,
                        "similarity": "COS",
                        "dimensions": EMBEDDING_DIM,
                    },
                }
            ],
        }
        db.command(cmd)
        logger.info(
            "✅ Índice vectorial %s creado (IVF, %d lists, cosine, %d dim)",
            VECTOR_INDEX_NAME, NUM_LISTS, EMBEDDING_DIM,
        )
    else:
        logger.info("✅ Índice vectorial %s ya existe", VECTOR_INDEX_NAME)

    # 2. Índices auxiliares para los campos de filtro (Cosmos vCore los exige)
    aux_indexes = [
        ("source_type", "source_type_1"),
        ("primary_language", "primary_language_1"),
        ("stargazer_count", "stargazer_count_1"),
        ("source_id", "source_id_1"),
    ]
    for field, name in aux_indexes:
        if name not in existing_names:
            try:
                coll.create_index(field, name=name)
                logger.info("✅ Índice auxiliar %s creado", name)
            except OperationFailure as e:
                logger.warning("Índice %s no creado (puede existir con otro nombre): %s", name, e)

    return True


def vector_search(
    query_embedding: List[float],
    k: int = 8,
    pre_filter: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Top-K búsqueda semántica sobre ``repos_chunks``.

    Args:
        query_embedding: vector consulta (debe tener ``EMBEDDING_DIM`` dim).
        k: nº de resultados a devolver (cap a 50).
        pre_filter: filtro MongoDB aplicado **antes** del vector search.
            Ejemplos útiles:
                {"primary_language": "Python"}
                {"stargazer_count": {"$gte": 100}}
                {"source_type": "repository"}

    Returns:
        Lista de dicts con campos ``{source_id, source_type, text,
        repo_name, primary_language, stargazer_count, score}`` ordenados
        por similitud descendente.
    """
    if len(query_embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"query_embedding debe tener {EMBEDDING_DIM} dim, tiene {len(query_embedding)}"
        )

    k = max(1, min(int(k), 50))
    db = get_database()
    coll = db[CHUNKS_COLLECTION]

    cosmos_search: Dict[str, Any] = {
        "vector": query_embedding,
        "path": EMBEDDING_FIELD,
        "k": k,
    }
    if pre_filter:
        cosmos_search["filter"] = pre_filter

    pipeline: List[Dict[str, Any]] = [
        {"$search": {"cosmosSearch": cosmos_search, "returnStoredSource": True}},
        {
            "$project": {
                "_id": 0,
                "source_id": 1,
                "source_type": 1,
                "chunk_index": 1,
                "text": 1,
                "repo_name": 1,
                "repo_full_name": 1,
                "primary_language": 1,
                "stargazer_count": 1,
                "score": {"$meta": "searchScore"},
            }
        },
    ]

    try:
        results = list(coll.aggregate(pipeline))
        logger.info(
            "🔍 vector_search returned %d hits (k=%d, filtered=%s)",
            len(results), k, bool(pre_filter),
        )
        return results
    except OperationFailure as e:
        logger.error("Vector search falló: %s", e)
        raise
