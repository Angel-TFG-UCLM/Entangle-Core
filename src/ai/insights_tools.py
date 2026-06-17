"""
Tools del worker INSIGHTS — análisis cruzado del ecosistema cuántico.

A diferencia de DATA (consultas directas a Mongo) o KNOWLEDGE (RAG sobre
texto), estas tools combinan datos y descubren patrones:

  - find_similar_repos(name)            → repos con README semánticamente similar
  - compare_repos([r1, r2, r3])         → tabla estructurada lado a lado
  - collaboration_strength(a, b)        → métricas concretas de colaboración

Se registran con ``@tool`` al importarse este módulo.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..core.db import db
from ..core.logger import logger
from ..core.vector_search import vector_search
from .embedder import embed_one
from .tool_registry import tool


# ──────────────────────────────────────────────────────────────────────
# 1) find_similar_repos
# ──────────────────────────────────────────────────────────────────────

@tool(
    name="find_similar_repos",
    description=(
        "Encuentra repositorios con un README/propósito SEMÁNTICAMENTE similar a "
        "un repo dado. Útil para descubrimiento: 'repos parecidos a Qiskit pero más "
        "ligeros', 'alternativas a Cirq', 'qué hay como PennyLane en Julia'. "
        "Usa vector search sobre los embeddings del README del repo de referencia."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repo_name": {
                "type": "string",
                "description": (
                    "Nombre del repo de referencia. Acepta 'qiskit', 'Qiskit/qiskit', "
                    "o 'qiskit/qiskit' indistintamente."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": "Número de repos similares a devolver (1-15, default 5).",
                "default": 5,
            },
            "primary_language": {
                "type": "string",
                "description": "Filtro opcional por lenguaje (e.g. 'Python', 'Julia').",
            },
            "min_stars": {
                "type": "integer",
                "description": "Filtro opcional: solo repos con ≥ esta cantidad de estrellas.",
            },
        },
        "required": ["repo_name"],
    },
    display_name="Buscando repos similares",
)
def find_similar_repos(
    repo_name: str,
    top_k: int = 5,
    primary_language: Optional[str] = None,
    min_stars: Optional[int] = None,
) -> str:
    db.ensure_connection()
    repos = db.get_collection("repositories")
    chunks = db.get_collection("repos_chunks")

    # 1) Resolver el repo de referencia (acepta nombre suelto o owner/name).
    # Priorizar el repo más popular si hay ambigüedad (e.g. "qiskit" matches
    # tanto "Qiskit/qiskit" como "a-auer/qiskit"; queremos el primero).
    needle = repo_name.strip()
    if "/" in needle:
        owner, name = needle.split("/", 1)
        ref = repos.find_one({
            "$or": [
                {"full_name": {"$regex": f"^{owner}/{name}$", "$options": "i"}},
                {"full_name": needle},
            ]
        })
    else:
        # Buscar candidatos y elegir el de más estrellas
        candidates = list(repos.find(
            {"$or": [
                {"name": {"$regex": f"^{needle}$", "$options": "i"}},
                {"full_name": {"$regex": f"/{needle}$", "$options": "i"}},
            ]},
            {"id": 1, "full_name": 1, "name": 1, "stargazer_count": 1, "primary_language": 1},
        ).limit(20))
        if candidates:
            ref = max(candidates, key=lambda r: r.get("stargazer_count", 0) or 0)
            # Reload completo (la projection anterior es parcial)
            ref = repos.find_one({"_id": ref["_id"]})
        else:
            ref = None

    if not ref:
        return json.dumps({"error": f"Repo '{repo_name}' no encontrado en la BBDD."})

    ref_full = ref.get("full_name") or f"{(ref.get('owner') or {}).get('login', '?')}/{ref.get('name', '?')}"

    # source_id estable (mismo formato que usa el indexer: "repo:<github_node_id>"
    # o "repo:<full_name>" como fallback). El "id" en BBDD es el node_id base64
    # de la API GraphQL de GitHub, NO un número.
    rid = ref.get("id")
    if isinstance(rid, (str, int)) and str(rid).strip():
        ref_source_id = f"repo:{rid}"
    else:
        ref_source_id = f"repo:{ref_full}"

    # 2) Construir embedding desde el README del ref (concatenando chunks)
    ref_chunks = list(chunks.find(
        {"source_id": ref_source_id, "source_type": "repository"},
        {"text": 1},
    ).limit(3))

    if ref_chunks:
        seed_text = " ".join(c.get("text", "") for c in ref_chunks)[:2000]
    else:
        seed_text = (ref.get("description") or "") + " " + (ref.get("name") or "")

    if not seed_text.strip():
        return json.dumps({"error": f"'{ref_full}' no tiene texto suficiente para comparar."})

    qvec = embed_one(seed_text)

    # 3) Vector search con filtros
    pre_filter: Dict[str, Any] = {"source_type": "repository"}
    if primary_language:
        pre_filter["primary_language"] = primary_language
    if min_stars is not None:
        pre_filter["stargazer_count"] = {"$gte": int(min_stars)}

    hits = vector_search(
        query_embedding=qvec,
        k=max(top_k * 3, 10),  # overfetch para deduplicar por source_id
        pre_filter=pre_filter,
    )

    # 4) Agrupar hits por source_id, descartando el repo de referencia
    seen: Dict[str, Dict[str, Any]] = {}
    for h in hits:
        sid = h.get("source_id")
        if not sid or sid == ref_source_id:
            continue
        if sid in seen:
            seen[sid]["score"] = max(seen[sid]["score"], h.get("score", 0))
            continue
        seen[sid] = {
            "source_id": sid,
            "score": h.get("score", 0),
            "snippet": (h.get("text") or "")[:300],
        }
        if len(seen) >= top_k:
            break

    # 5) Enriquecer con metadatos del repo. El source_id tiene formato
    # "repo:<node_id_base64>" → buscamos en repositories por field `id`.
    repo_ids: List[str] = []
    repo_full_names: List[str] = []
    for sid in seen.keys():
        if sid.startswith("repo:"):
            value = sid[5:]
            # heurística: si parece full_name (contiene /) lo metemos como fallback;
            # en cualquier caso lo metemos como id porque GraphQL node_ids son strings.
            if "/" in value:
                repo_full_names.append(value)
            else:
                repo_ids.append(value)

    query_or = []
    if repo_ids:
        query_or.append({"id": {"$in": repo_ids}})
    if repo_full_names:
        query_or.append({"full_name": {"$in": repo_full_names}})
    if not query_or:
        docs = []
    else:
        docs = list(repos.find(
            {"$or": query_or},
            {"id": 1, "full_name": 1, "name": 1, "description": 1, "stargazer_count": 1,
             "primary_language": 1, "repository_topics": 1, "url": 1},
        ))

    # Index doc por source_id
    by_sid: Dict[str, Any] = {}
    for d in docs:
        rid_d = d.get("id")
        if rid_d is not None:
            by_sid[f"repo:{rid_d}"] = d
        if d.get("full_name"):
            by_sid.setdefault(f"repo:{d['full_name']}", d)

    results = []
    for sid, info in seen.items():
        doc = by_sid.get(sid)
        if not doc:
            continue
        results.append({
            "full_name": doc.get("full_name"),
            "description": doc.get("description"),
            "stargazer_count": doc.get("stargazer_count", 0),
            "primary_language": doc.get("primary_language"),
            "topics": (doc.get("repository_topics") or [])[:6],
            "url": doc.get("url"),
            "similarity": round(float(info["score"]), 4),
            "snippet": info["snippet"],
        })

    results.sort(key=lambda r: r["similarity"], reverse=True)
    results = results[:top_k]

    logger.info(
        "🔧 find_similar_repos(ref='%s', lang=%s, min_stars=%s) → %d hits",
        ref_full, primary_language, min_stars, len(results),
    )
    return json.dumps({
        "reference": ref_full,
        "count": len(results),
        "results": results,
    }, default=str)


# ──────────────────────────────────────────────────────────────────────
# 2) compare_repos
# ──────────────────────────────────────────────────────────────────────

@tool(
    name="compare_repos",
    description=(
        "Compara 2-5 repositorios lado a lado en una tabla estructurada con "
        "métricas concretas (estrellas, lenguaje, contribuyentes, topics, "
        "actividad). Útil para responder 'compara X vs Y vs Z', "
        "'diferencias entre A y B'. Devuelve campos comparables, no texto libre."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repos": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Lista de 2-5 nombres de repo. Acepta 'qiskit', 'Qiskit/qiskit' "
                    "o 'qiskit/qiskit'. Mínimo 2, máximo 5."
                ),
                "minItems": 2,
                "maxItems": 5,
            },
        },
        "required": ["repos"],
    },
    display_name="Comparando repositorios",
)
def compare_repos(repos: List[str]) -> str:
    if not repos or len(repos) < 2:
        return json.dumps({"error": "Se requieren al menos 2 repos para comparar."})
    if len(repos) > 5:
        repos = repos[:5]

    db.ensure_connection()
    repos_col = db.get_collection("repositories")

    rows = []
    not_found = []
    for raw in repos:
        needle = raw.strip()
        if "/" in needle:
            doc = repos_col.find_one({"full_name": {"$regex": f"^{needle}$", "$options": "i"}})
        else:
            doc = repos_col.find_one({"name": {"$regex": f"^{needle}$", "$options": "i"}})
            if not doc:
                doc = repos_col.find_one({"full_name": {"$regex": f"/{needle}$", "$options": "i"}})
        if not doc:
            not_found.append(raw)
            continue
        rows.append({
            "full_name": doc.get("full_name"),
            "description": (doc.get("description") or "")[:200],
            "stargazer_count": doc.get("stargazer_count", 0),
            "fork_count": doc.get("fork_count", 0),
            "watcher_count": doc.get("watchers_count", 0),
            "open_issues_count": doc.get("open_issues_count", 0),
            "primary_language": doc.get("primary_language"),
            "license": (doc.get("license_info") or {}).get("spdx_id") if isinstance(doc.get("license_info"), dict) else None,
            "topics": (doc.get("repository_topics") or [])[:8],
            "owner": (doc.get("owner") or {}).get("login"),
            "contributors_count": doc.get("collaborators_count", len(doc.get("collaborators") or [])),
            "created_at": doc.get("created_at"),
            "pushed_at": doc.get("pushed_at"),
            "url": doc.get("url"),
        })

    logger.info("🔧 compare_repos(%s) → %d found, %d missing", repos, len(rows), len(not_found))
    return json.dumps({
        "count": len(rows),
        "results": rows,
        "not_found": not_found,
    }, default=str)


# ──────────────────────────────────────────────────────────────────────
# 3) collaboration_strength
# ──────────────────────────────────────────────────────────────────────

@tool(
    name="collaboration_strength",
    description=(
        "Mide cuánto colaboran dos organizaciones o usuarios entre sí en el "
        "ecosistema cuántico. Devuelve métricas concretas: contribuyentes "
        "compartidos, número y nombres de repos comunes, fuerza relativa. "
        "Útil para 'cuánto colaboran IBM y Google', '¿hay overlap entre Microsoft y Rigetti?', "
        "'qué tan conectados están dos equipos'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "entity_a": {
                "type": "string",
                "description": "Primera organización (login) o usuario.",
            },
            "entity_b": {
                "type": "string",
                "description": "Segunda organización (login) o usuario.",
            },
            "kind": {
                "type": "string",
                "enum": ["org", "user", "auto"],
                "description": "Tipo de entidad. 'auto' (default) intenta detectar automáticamente.",
                "default": "auto",
            },
        },
        "required": ["entity_a", "entity_b"],
    },
    display_name="Midiendo colaboración",
)
def collaboration_strength(entity_a: str, entity_b: str, kind: str = "auto") -> str:
    db.ensure_connection()
    orgs = db.get_collection("organizations")
    users = db.get_collection("users")
    repos = db.get_collection("repositories")

    def _resolve(name: str, want_kind: str):
        """Devuelve (kind_real, doc) o (None, None)."""
        if want_kind in ("auto", "org"):
            doc = orgs.find_one({"login": {"$regex": f"^{name}$", "$options": "i"}})
            if doc:
                return "org", doc
        if want_kind in ("auto", "user"):
            doc = users.find_one({"login": {"$regex": f"^{name}$", "$options": "i"}})
            if doc:
                return "user", doc
        return None, None

    kind_a, doc_a = _resolve(entity_a, kind)
    kind_b, doc_b = _resolve(entity_b, kind)

    if not doc_a or not doc_b:
        missing = []
        if not doc_a: missing.append(entity_a)
        if not doc_b: missing.append(entity_b)
        return json.dumps({"error": f"No encontrados en BBDD: {missing}"})

    # ── Caso: dos organizaciones ──
    if kind_a == "org" and kind_b == "org":
        login_a = doc_a["login"]
        login_b = doc_b["login"]

        # Contribuyentes únicos a repos de cada org.
        # Estructura real en BBDD: owner.login + collaborators[].login
        def _contributors_for_org(login: str) -> set:
            cur = repos.find(
                {"owner.login": {"$regex": f"^{login}$", "$options": "i"}},
                {"collaborators": 1},
            )
            users_set: set = set()
            for r in cur:
                for c in (r.get("collaborators") or []):
                    if isinstance(c, dict) and c.get("login"):
                        users_set.add(c["login"])
                    elif isinstance(c, str):
                        users_set.add(c)
            return users_set

        contribs_a = _contributors_for_org(login_a)
        contribs_b = _contributors_for_org(login_b)
        shared_users = contribs_a & contribs_b

        # Métricas
        total_a = len(contribs_a)
        total_b = len(contribs_b)
        n_shared = len(shared_users)
        jaccard = n_shared / max(1, len(contribs_a | contribs_b))
        repos_count_a = repos.count_documents({"owner.login": {"$regex": f"^{login_a}$", "$options": "i"}})
        repos_count_b = repos.count_documents({"owner.login": {"$regex": f"^{login_b}$", "$options": "i"}})

        logger.info(
            "🔧 collaboration_strength(org %s ↔ org %s) → %d shared / %d ∪ %d (jaccard=%.3f)",
            login_a, login_b, n_shared, total_a, total_b, jaccard,
        )
        return json.dumps({
            "kind": "org_vs_org",
            "entity_a": {"login": login_a, "repos": repos_count_a, "contributors": total_a},
            "entity_b": {"login": login_b, "repos": repos_count_b, "contributors": total_b},
            "shared_contributors": sorted(shared_users)[:50],
            "shared_count": n_shared,
            "jaccard_similarity": round(jaccard, 4),
            "interpretation": _interpret_strength(jaccard, n_shared),
        }, default=str)

    # ── Caso: dos usuarios ──
    if kind_a == "user" and kind_b == "user":
        login_a = doc_a["login"]
        login_b = doc_b["login"]

        def _repos_contributed(login: str) -> set:
            cur = repos.find(
                {"collaborators.login": login},
                {"full_name": 1},
            )
            return {r["full_name"] for r in cur if r.get("full_name")}

        repos_a = _repos_contributed(login_a)
        repos_b = _repos_contributed(login_b)
        shared_repos = repos_a & repos_b

        n_shared = len(shared_repos)
        jaccard = n_shared / max(1, len(repos_a | repos_b))

        logger.info(
            "🔧 collaboration_strength(user %s ↔ user %s) → %d shared repos",
            login_a, login_b, n_shared,
        )
        return json.dumps({
            "kind": "user_vs_user",
            "entity_a": {"login": login_a, "repos_contributed": len(repos_a)},
            "entity_b": {"login": login_b, "repos_contributed": len(repos_b)},
            "shared_repos": sorted(shared_repos)[:30],
            "shared_count": n_shared,
            "jaccard_similarity": round(jaccard, 4),
            "interpretation": _interpret_strength(jaccard, n_shared),
        }, default=str)

    # ── Caso mixto: user ↔ org ──
    org_doc = doc_a if kind_a == "org" else doc_b
    user_doc = doc_b if kind_a == "org" else doc_a
    org_login = org_doc["login"]
    user_login = user_doc["login"]

    cur = repos.find(
        {
            "owner.login": {"$regex": f"^{org_login}$", "$options": "i"},
            "collaborators.login": user_login,
        },
        {"full_name": 1, "stargazer_count": 1},
    )
    contributed = list(cur)
    total_org_repos = repos.count_documents({"owner.login": {"$regex": f"^{org_login}$", "$options": "i"}})

    logger.info(
        "🔧 collaboration_strength(user %s ↔ org %s) → %d/%d repos contributed",
        user_login, org_login, len(contributed), total_org_repos,
    )
    return json.dumps({
        "kind": "user_vs_org",
        "user": user_login,
        "org": org_login,
        "contributed_repos": [
            {"full_name": r.get("full_name"), "stars": r.get("stargazer_count", 0)}
            for r in contributed[:30]
        ],
        "contributed_count": len(contributed),
        "total_org_repos": total_org_repos,
        "coverage_ratio": round(len(contributed) / max(1, total_org_repos), 4),
    }, default=str)


def _interpret_strength(jaccard: float, n_shared: int) -> str:
    """Etiqueta humana de la fuerza de colaboración."""
    if n_shared == 0:
        return "ninguna colaboración detectada"
    if jaccard >= 0.30:
        return "colaboración muy fuerte"
    if jaccard >= 0.10:
        return "colaboración significativa"
    if jaccard >= 0.03:
        return "colaboración moderada"
    return "colaboración débil"
