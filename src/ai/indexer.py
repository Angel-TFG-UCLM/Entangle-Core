"""
Pipeline de indexación de READMEs y descripciones de repositorios.

Es idempotente: usa un hash SHA-256 del contenido para detectar cambios
desde la última indexación. Cuando un repo no ha cambiado, se salta sin
gastar tokens de embeddings.

Flujo:
    1. Lee de ``repositories`` solo lo necesario (id, full_name,
       description, readme_text, primary_language, stargazer_count).
    2. Compara hash con ``_indexing.content_hash`` del propio doc.
    3. Si cambió o nunca se indexó:
         a) borra chunks anteriores de ese ``source_id``
         b) chunkea
         c) embedde en batch
         d) bulk insert en ``repos_chunks``
         e) actualiza ``_indexing`` en el repo origen

Uso (CLI):
    python -m src.ai.indexer  [--limit N] [--force] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from pymongo import UpdateOne

from ..core.db import get_collection, get_database
from ..core.logger import logger
from ..core.vector_search import CHUNKS_COLLECTION, ensure_vector_index
from .chunker import chunk_text, text_hash
from .embedder import embed_texts


# Campos textuales que se combinan para chunking
_TEXT_FIELDS = ("description", "readme_text")

# Para no saturar el endpoint de embeddings, lote máximo de chunks
# embebidos por llamada (multiplicado por el batch interno del embedder)
_CHUNK_BATCH = 64


def _build_source_text(repo: Dict[str, Any]) -> str:
    """Concatena los campos textuales relevantes en un único string
    que sirve tanto para hashing como para chunking."""
    parts: List[str] = []
    for field in _TEXT_FIELDS:
        value = repo.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n\n".join(parts)


def _stable_source_id(repo: Dict[str, Any]) -> str:
    """ID estable basado en el ``id`` interno o ``full_name``."""
    rid = repo.get("id")
    if isinstance(rid, (str, int)) and str(rid).strip():
        return f"repo:{rid}"
    full = repo.get("full_name") or repo.get("name") or "unknown"
    return f"repo:{full}"


def _iter_repos(limit: Optional[int] = None) -> Iterable[Dict[str, Any]]:
    coll = get_collection("repositories")
    projection = {
        "_id": 0,
        "id": 1,
        "full_name": 1,
        "name": 1,
        "description": 1,
        "readme_text": 1,
        "primary_language": 1,
        "stargazer_count": 1,
        "_indexing": 1,
    }
    cursor = coll.find({}, projection=projection)
    if limit:
        cursor = cursor.limit(limit)
    for repo in cursor:
        yield repo


def _delete_existing_chunks(source_id: str) -> int:
    coll = get_collection(CHUNKS_COLLECTION)
    res = coll.delete_many({"source_id": source_id})
    return res.deleted_count


def _persist_chunks(
    chunks: List[Dict[str, Any]],
    embeddings: List[List[float]],
    repo: Dict[str, Any],
    source_id: str,
    content_hash: str,
) -> int:
    if not chunks:
        return 0
    coll = get_collection(CHUNKS_COLLECTION)
    now = datetime.now(timezone.utc)
    docs: List[Dict[str, Any]] = []
    for chunk, embedding in zip(chunks, embeddings):
        docs.append({
            "source_id": source_id,
            "source_type": "repository",
            "chunk_index": chunk["chunk_index"],
            "text": chunk["text"],
            "embedding": embedding,
            "section_path": chunk.get("section_path") or "",
            "char_count": chunk["char_count"],
            "repo_name": repo.get("name") or "",
            "repo_full_name": repo.get("full_name") or "",
            "primary_language": repo.get("primary_language") or "Unknown",
            "stargazer_count": int(repo.get("stargazer_count") or 0),
            "indexed_at": now,
            "content_hash": content_hash,
        })
    coll.insert_many(docs, ordered=False)
    return len(docs)


def _mark_repo_indexed(
    repo: Dict[str, Any],
    content_hash: str,
    chunks_count: int,
) -> None:
    """Anota en el doc de repository el hash y nº de chunks generados."""
    repos = get_collection("repositories")
    rid = repo.get("id") or repo.get("full_name")
    if not rid:
        return
    repos.update_one(
        {"$or": [{"id": rid}, {"full_name": rid}]},
        {"$set": {"_indexing": {
            "content_hash": content_hash,
            "chunks_count": chunks_count,
            "indexed_at": datetime.now(timezone.utc),
            "source_text_fields": list(_TEXT_FIELDS),
        }}},
    )


def index_repositories(
    *,
    limit: Optional[int] = None,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Indexa los repos: extrae texto, chunkea, embedde, persiste.

    Returns:
        Diccionario con métricas: processed, indexed, skipped, chunks_total,
        errors.
    """
    if not dry_run:
        ensure_vector_index()

    stats = {
        "processed": 0,
        "indexed": 0,
        "skipped_unchanged": 0,
        "skipped_no_text": 0,
        "chunks_total": 0,
        "errors": 0,
    }
    t0 = time.time()

    for repo in _iter_repos(limit=limit):
        stats["processed"] += 1

        source_text = _build_source_text(repo)
        if not source_text:
            stats["skipped_no_text"] += 1
            continue

        new_hash = text_hash(source_text)
        existing = (repo.get("_indexing") or {}).get("content_hash")
        if not force and existing == new_hash:
            stats["skipped_unchanged"] += 1
            continue

        source_id = _stable_source_id(repo)
        header = repo.get("full_name") or repo.get("name") or ""
        chunks = chunk_text(source_text, header=f"Repository: {header}" if header else None)
        if not chunks:
            stats["skipped_no_text"] += 1
            continue

        try:
            embeddings = embed_texts(
                [c["text"] for c in chunks],
                batch_size=_CHUNK_BATCH,
            )
        except Exception as exc:
            logger.error("Embeddings fallaron para %s: %s", source_id, exc)
            stats["errors"] += 1
            continue

        if dry_run:
            stats["chunks_total"] += len(chunks)
            stats["indexed"] += 1
            logger.info("[dry-run] %s → %d chunks", source_id, len(chunks))
            continue

        try:
            _delete_existing_chunks(source_id)
            inserted = _persist_chunks(chunks, embeddings, repo, source_id, new_hash)
            _mark_repo_indexed(repo, new_hash, inserted)
            stats["chunks_total"] += inserted
            stats["indexed"] += 1
            if stats["indexed"] % 20 == 0:
                elapsed = time.time() - t0
                logger.info(
                    "Progreso: %d indexados, %d chunks, %d skipped, %.1fs",
                    stats["indexed"], stats["chunks_total"],
                    stats["skipped_unchanged"], elapsed,
                )
        except Exception as exc:
            logger.error("Persistencia falló para %s: %s", source_id, exc)
            stats["errors"] += 1

    elapsed = time.time() - t0
    logger.info(
        "✅ Indexación terminada en %.1fs — %s",
        elapsed,
        ", ".join(f"{k}={v}" for k, v in stats.items()),
    )
    return stats


def _main() -> int:
    parser = argparse.ArgumentParser(description="Indexa READMEs en Cosmos vector store")
    parser.add_argument("--limit", type=int, default=None,
                        help="Máximo de repos a procesar (todos por defecto)")
    parser.add_argument("--force", action="store_true",
                        help="Re-indexa incluso si el hash coincide")
    parser.add_argument("--dry-run", action="store_true",
                        help="No persiste, solo cuenta chunks")
    args = parser.parse_args()

    stats = index_repositories(limit=args.limit, force=args.force, dry_run=args.dry_run)
    print()
    for k, v in stats.items():
        print(f"  {k:25s}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
