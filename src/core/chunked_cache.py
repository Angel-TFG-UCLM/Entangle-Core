"""
Chunked MongoDB Cache
=====================
Almacenamiento de documentos grandes en MongoDB/Cosmos DB vCore,
dividiendo arrays grandes en chunks que respetan el límite de 2 MB por documento.

Uso:
    from src.core.chunked_cache import save_chunked, load_chunked, delete_chunked

    # Guardar (auto-divide arrays grandes en chunks)
    save_chunked(collection, "my_cache_id", data, large_fields=["graph.nodes", "graph.links"])

    # Leer (auto-reensambla chunks)
    result = load_chunked(collection, "my_cache_id")

    # Borrar (elimina meta + todos los chunks)
    delete_chunked(collection, "my_cache_id")
"""

import json
import math
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Tamaño objetivo por chunk en bytes (1.5 MB, margen seguro bajo el límite de 2 MB de Cosmos DB vCore)
TARGET_CHUNK_BYTES = 1_500_000


def _estimate_items_per_chunk(array, target_bytes=TARGET_CHUNK_BYTES):
    """Estima cuántos items caben en un chunk muestreando los primeros 50 elementos."""
    if not array:
        return max(len(array), 1)
    sample = array[:min(50, len(array))]
    total_bytes = sum(len(json.dumps(item, default=str).encode("utf-8")) for item in sample)
    avg_bytes = total_bytes / len(sample)
    # Margen de 30% para overhead BSON y metadata del documento
    items = int(target_bytes / (avg_bytes * 1.3))
    return max(items, 1)


def save_chunked(collection, cache_id, data, large_fields):
    """
    Guarda datos en MongoDB con arrays grandes divididos en chunks.

    Args:
        collection: colección pymongo
        cache_id: _id base del documento (ej: "collaboration_graph")
        data: diccionario completo a cachear
        large_fields: lista de paths con notación punto a arrays grandes
                      ej: ["graph.nodes", "graph.links", "bridge_users"]
    """
    # 1. Borrar caché anterior
    delete_chunked(collection, cache_id)

    # 2. Copiar datos (shallow) para construir el meta doc
    meta = _shallow_copy(data)
    meta["_id"] = cache_id
    meta["_chunked"] = True
    meta["_chunk_map"] = {}
    meta["_cached_at"] = datetime.now(timezone.utc).isoformat()

    chunk_ids_written = []

    for field_path in large_fields:
        # Extraer el array del path anidado
        array = _get_nested(data, field_path)

        if not array or not isinstance(array, (list, dict)):
            meta["_chunk_map"][field_path] = {"count": 0, "kind": "list", "total": 0}
            _remove_nested(meta, field_path)
            continue

        # Soportar dicts (convertir a lista de pares para chunking)
        if isinstance(array, dict):
            items_list = list(array.items())
            kind = "dict"
        else:
            items_list = array
            kind = "list"

        items_per_chunk = _estimate_items_per_chunk(
            [{"k": k, "v": v} for k, v in items_list] if kind == "dict" else items_list
        )
        num_chunks = math.ceil(len(items_list) / items_per_chunk)

        meta["_chunk_map"][field_path] = {
            "count": num_chunks,
            "kind": kind,
            "total": len(items_list),
        }

        # Remover el array grande del meta para que quepa en 2 MB
        _remove_nested(meta, field_path)

        # Escribir chunks
        for i in range(num_chunks):
            chunk_data = items_list[i * items_per_chunk : (i + 1) * items_per_chunk]
            chunk_id = f"{cache_id}##{field_path.replace('.', '_')}##{i}"

            if kind == "dict":
                # Guardar como lista de [key, value] para preservar las claves
                chunk_doc = {"_id": chunk_id, "items": [[k, v] for k, v in chunk_data]}
            else:
                chunk_doc = {"_id": chunk_id, "items": chunk_data}

            collection.insert_one(chunk_doc)
            chunk_ids_written.append(chunk_id)

    # 3. Escribir meta
    collection.insert_one(meta)

    total_docs = 1 + len(chunk_ids_written)
    field_summary = ", ".join(
        f"{fp}: {meta['_chunk_map'][fp]['total']} items en {meta['_chunk_map'][fp]['count']} chunks"
        for fp in large_fields
        if meta["_chunk_map"].get(fp, {}).get("total", 0) > 0
    )
    logger.info(f"[ChunkedCache] Guardado '{cache_id}' en {total_docs} documentos ({field_summary})")


def load_chunked(collection, cache_id):
    """
    Carga y reensambla un documento con chunks. Retorna None si no existe.
    Compatible con documentos legacy (sin chunks).
    """
    meta = collection.find_one({"_id": cache_id})
    if not meta:
        return None

    meta.pop("_id", None)
    meta.pop("_cached_at", None)

    # Documento legacy (sin chunks)
    if not meta.pop("_chunked", False):
        meta.pop("cached_at", None)
        return meta

    chunk_map = meta.pop("_chunk_map", {})

    for field_path, info in chunk_map.items():
        num_chunks = info["count"]
        kind = info.get("kind", "list")
        assembled = []

        for i in range(num_chunks):
            chunk_id = f"{cache_id}##{field_path.replace('.', '_')}##{i}"
            chunk_doc = collection.find_one({"_id": chunk_id})
            if chunk_doc and "items" in chunk_doc:
                assembled.extend(chunk_doc["items"])

        # Restaurar tipo original
        if kind == "dict":
            value = {k: v for k, v in assembled}
        else:
            value = assembled

        _set_nested(meta, field_path, value)

    return meta


def delete_chunked(collection, cache_id):
    """Elimina un caché chunked y todos sus chunks."""
    meta = collection.find_one({"_id": cache_id}, {"_chunk_map": 1, "_chunked": 1})

    ids_to_delete = [cache_id]

    if meta and meta.get("_chunked"):
        for field_path, info in meta.get("_chunk_map", {}).items():
            num_chunks = info["count"] if isinstance(info, dict) else info
            for i in range(num_chunks):
                ids_to_delete.append(f"{cache_id}##{field_path.replace('.', '_')}##{i}")

    result = collection.delete_many({"_id": {"$in": ids_to_delete}})
    if result.deleted_count > 0:
        logger.info(f"[ChunkedCache] Eliminado '{cache_id}': {result.deleted_count} documentos")
    return result.deleted_count


def get_cache_age_seconds(collection, cache_id):
    """Retorna la antigüedad del caché en segundos, o None si no existe."""
    meta = collection.find_one({"_id": cache_id}, {"_cached_at": 1})
    if not meta or "_cached_at" not in meta:
        return None
    try:
        cached_at = datetime.fromisoformat(meta["_cached_at"])
        age = datetime.now(timezone.utc) - cached_at
        return age.total_seconds()
    except (ValueError, TypeError):
        return None


# ── Helpers internos ──

def _shallow_copy(data):
    """Copia superficial recursiva de dicts (1 nivel de profundidad)."""
    result = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[key] = dict(value)
        else:
            result[key] = value
    return result


def _get_nested(obj, dot_path):
    """Obtiene un valor anidado por path con puntos. Ej: 'graph.nodes'."""
    parts = dot_path.split(".")
    current = obj
    for p in parts:
        if isinstance(current, dict) and p in current:
            current = current[p]
        else:
            return None
    return current


def _set_nested(obj, dot_path, value):
    """Establece un valor anidado por path con puntos. Crea dicts intermedios."""
    parts = dot_path.split(".")
    current = obj
    for p in parts[:-1]:
        if p not in current or not isinstance(current.get(p), dict):
            current[p] = {}
        current = current[p]
    current[parts[-1]] = value


def _remove_nested(obj, dot_path):
    """Elimina un valor anidado por path con puntos."""
    parts = dot_path.split(".")
    current = obj
    for p in parts[:-1]:
        if isinstance(current, dict) and p in current:
            current = current[p]
        else:
            return
    if isinstance(current, dict) and parts[-1] in current:
        del current[parts[-1]]
