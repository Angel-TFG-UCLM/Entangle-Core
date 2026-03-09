"""
Funciones de consulta a la base de datos para el agente de IA.
Cada función corresponde a un tool del agente en Azure AI Foundry.
"""
import json
import re
from typing import Any, Dict, List, Optional

from ..core.mongo_repository import MongoRepository
from ..core.logger import logger


# Repositorios de datos (singleton por colección)
_repos_repo = MongoRepository("repositories")
_orgs_repo = MongoRepository("organizations")
_users_repo = MongoRepository("users")


def get_top_repositories(
    sort_by: str = "stars_count",
    limit: int = 10,
    language: Optional[str] = None,
) -> str:
    """Obtiene los repositorios top ordenados por un campo específico."""
    try:
        limit = min(max(limit, 1), 20)

        valid_sort_fields = {
            "stars_count", "forks_count", "quantum_score",
            "collaboration_score", "contributors_count",
        }
        if sort_by not in valid_sort_fields:
            sort_by = "stars_count"

        query: Dict[str, Any] = {}
        if language:
            query["primary_language"] = {"$regex": f"^{re.escape(language)}$", "$options": "i"}

        docs = _repos_repo.find(
            query=query,
            projection={
                "_id": 0, "name": 1, "owner.login": 1, "stars_count": 1,
                "forks_count": 1, "primary_language": 1, "quantum_score": 1,
                "collaboration_score": 1, "contributors_count": 1,
                "description": 1,
            },
            sort=[(sort_by, -1)],
            limit=limit,
        )

        results = []
        for d in docs:
            owner = d.get("owner", {}).get("login", "N/A") if isinstance(d.get("owner"), dict) else "N/A"
            results.append({
                "name": d.get("name"),
                "owner": owner,
                "stars": d.get("stars_count", 0),
                "forks": d.get("forks_count", 0),
                "language": d.get("primary_language"),
                "quantum_score": d.get("quantum_score"),
                "collaboration_score": d.get("collaboration_score"),
                "contributors": d.get("contributors_count", 0),
                "description": (d.get("description") or "")[:120],
            })

        return json.dumps({"repositories": results, "total": len(results)}, default=str)

    except Exception as e:
        logger.error(f"Error en get_top_repositories: {e}")
        return json.dumps({"error": str(e)})


def get_top_organizations(
    sort_by: str = "quantum_focus_score",
    limit: int = 10,
) -> str:
    """Obtiene las organizaciones top del ecosistema cuántico."""
    try:
        limit = min(max(limit, 1), 20)

        valid_sort_fields = {
            "quantum_focus_score", "members_count",
            "quantum_repositories_count", "public_repos_count",
        }
        if sort_by not in valid_sort_fields:
            sort_by = "quantum_focus_score"

        docs = _orgs_repo.find(
            query={},
            projection={
                "_id": 0, "login": 1, "name": 1, "members_count": 1,
                "public_repos_count": 1, "quantum_focus_score": 1,
                "quantum_repositories_count": 1, "is_verified": 1,
                "description": 1,
            },
            sort=[(sort_by, -1)],
            limit=limit,
        )

        results = []
        for d in docs:
            results.append({
                "login": d.get("login"),
                "name": d.get("name"),
                "members": d.get("members_count", 0),
                "public_repos": d.get("public_repos_count", 0),
                "quantum_focus_score": d.get("quantum_focus_score"),
                "quantum_repos": d.get("quantum_repositories_count", 0),
                "verified": d.get("is_verified", False),
                "description": (d.get("description") or "")[:120],
            })

        return json.dumps({"organizations": results, "total": len(results)}, default=str)

    except Exception as e:
        logger.error(f"Error en get_top_organizations: {e}")
        return json.dumps({"error": str(e)})


def get_top_users(
    sort_by: str = "quantum_expertise_score",
    limit: int = 10,
) -> str:
    """Obtiene los desarrolladores más destacados del ecosistema cuántico."""
    try:
        limit = min(max(limit, 1), 20)

        valid_sort_fields = {
            "quantum_expertise_score", "followers_count",
            "total_commit_contributions", "total_pr_contributions",
            "public_repos_count",
        }
        if sort_by not in valid_sort_fields:
            sort_by = "quantum_expertise_score"

        docs = _users_repo.find(
            query={"is_quantum_contributor": True},
            projection={
                "_id": 0, "login": 1, "name": 1, "followers_count": 1,
                "public_repos_count": 1, "quantum_expertise_score": 1,
                "total_commit_contributions": 1, "total_pr_contributions": 1,
                "top_languages": 1,
            },
            sort=[(sort_by, -1)],
            limit=limit,
        )

        results = []
        for d in docs:
            results.append({
                "login": d.get("login"),
                "name": d.get("name"),
                "followers": d.get("followers_count", 0),
                "public_repos": d.get("public_repos_count", 0),
                "quantum_expertise_score": d.get("quantum_expertise_score"),
                "commits": d.get("total_commit_contributions", 0),
                "prs": d.get("total_pr_contributions", 0),
                "top_languages": (d.get("top_languages") or [])[:5],
            })

        return json.dumps({"users": results, "total": len(results)}, default=str)

    except Exception as e:
        logger.error(f"Error en get_top_users: {e}")
        return json.dumps({"error": str(e)})


def get_general_stats() -> str:
    """Obtiene estadísticas generales del ecosistema."""
    try:
        total_repos = _repos_repo.count_documents()
        total_orgs = _orgs_repo.count_documents()
        total_users = _users_repo.count_documents()
        quantum_contributors = _users_repo.count_documents({"is_quantum_contributor": True})

        # Top lenguajes por frecuencia
        pipeline = [
            {"$match": {"primary_language": {"$ne": None}}},
            {"$group": {"_id": "$primary_language", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        lang_cursor = _repos_repo.collection.aggregate(pipeline)
        top_languages = [{"language": doc["_id"], "count": doc["count"]} for doc in lang_cursor]

        # Promedios de métricas
        avg_pipeline = [
            {"$group": {
                "_id": None,
                "avg_stars": {"$avg": "$stars_count"},
                "avg_forks": {"$avg": "$forks_count"},
                "avg_quantum_score": {"$avg": "$quantum_score"},
            }},
        ]
        avg_cursor = list(_repos_repo.collection.aggregate(avg_pipeline))
        averages = avg_cursor[0] if avg_cursor else {}

        stats = {
            "total_repositories": total_repos,
            "total_organizations": total_orgs,
            "total_users": total_users,
            "quantum_contributors": quantum_contributors,
            "top_languages": top_languages,
            "averages": {
                "avg_stars": round(averages.get("avg_stars", 0) or 0, 1),
                "avg_forks": round(averages.get("avg_forks", 0) or 0, 1),
                "avg_quantum_score": round(averages.get("avg_quantum_score", 0) or 0, 2),
            },
        }

        return json.dumps(stats, default=str)

    except Exception as e:
        logger.error(f"Error en get_general_stats: {e}")
        return json.dumps({"error": str(e)})


def search_entity(entity_type: str, query: str) -> str:
    """Busca un repositorio, organización o usuario por nombre."""
    try:
        if entity_type not in ("repository", "organization", "user"):
            return json.dumps({"error": f"Tipo de entidad no válido: {entity_type}"})

        safe_query = re.escape(query)
        regex_filter = {"$regex": safe_query, "$options": "i"}

        if entity_type == "repository":
            docs = _repos_repo.find(
                query={"$or": [{"name": regex_filter}, {"owner.login": regex_filter}]},
                projection={
                    "_id": 0, "name": 1, "owner.login": 1, "stars_count": 1,
                    "forks_count": 1, "primary_language": 1, "quantum_score": 1,
                    "description": 1, "topics": 1,
                },
                limit=10,
                sort=[("stars_count", -1)],
            )
            results = []
            for d in docs:
                owner = d.get("owner", {}).get("login", "N/A") if isinstance(d.get("owner"), dict) else "N/A"
                results.append({
                    "name": d.get("name"),
                    "owner": owner,
                    "stars": d.get("stars_count", 0),
                    "forks": d.get("forks_count", 0),
                    "language": d.get("primary_language"),
                    "quantum_score": d.get("quantum_score"),
                    "description": (d.get("description") or "")[:150],
                    "topics": (d.get("topics") or [])[:8],
                })

        elif entity_type == "organization":
            docs = _orgs_repo.find(
                query={"$or": [{"login": regex_filter}, {"name": regex_filter}]},
                projection={
                    "_id": 0, "login": 1, "name": 1, "members_count": 1,
                    "public_repos_count": 1, "quantum_focus_score": 1,
                    "quantum_repositories_count": 1, "description": 1,
                },
                limit=10,
                sort=[("quantum_focus_score", -1)],
            )
            results = [
                {
                    "login": d.get("login"),
                    "name": d.get("name"),
                    "members": d.get("members_count", 0),
                    "public_repos": d.get("public_repos_count", 0),
                    "quantum_focus_score": d.get("quantum_focus_score"),
                    "quantum_repos": d.get("quantum_repositories_count", 0),
                    "description": (d.get("description") or "")[:150],
                }
                for d in docs
            ]

        else:  # user
            docs = _users_repo.find(
                query={"$or": [{"login": regex_filter}, {"name": regex_filter}]},
                projection={
                    "_id": 0, "login": 1, "name": 1, "followers_count": 1,
                    "public_repos_count": 1, "quantum_expertise_score": 1,
                    "total_commit_contributions": 1, "top_languages": 1, "bio": 1,
                },
                limit=10,
                sort=[("quantum_expertise_score", -1)],
            )
            results = [
                {
                    "login": d.get("login"),
                    "name": d.get("name"),
                    "followers": d.get("followers_count", 0),
                    "public_repos": d.get("public_repos_count", 0),
                    "quantum_expertise_score": d.get("quantum_expertise_score"),
                    "commits": d.get("total_commit_contributions", 0),
                    "top_languages": (d.get("top_languages") or [])[:5],
                    "bio": (d.get("bio") or "")[:150],
                }
                for d in docs
            ]

        return json.dumps(
            {"entity_type": entity_type, "query": query, "results": results, "total": len(results)},
            default=str,
        )

    except Exception as e:
        logger.error(f"Error en search_entity: {e}")
        return json.dumps({"error": str(e)})


def get_language_distribution(limit: int = 15) -> str:
    """Obtiene la distribución de lenguajes de programación."""
    try:
        limit = min(max(limit, 1), 30)

        pipeline = [
            {"$match": {"primary_language": {"$ne": None}}},
            {"$group": {"_id": "$primary_language", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]
        cursor = _repos_repo.collection.aggregate(pipeline)
        languages = [{"language": doc["_id"], "repository_count": doc["count"]} for doc in cursor]

        total_with_language = sum(l["repository_count"] for l in languages)
        for lang in languages:
            lang["percentage"] = round(lang["repository_count"] / total_with_language * 100, 1) if total_with_language else 0

        return json.dumps({"languages": languages, "total_languages_shown": len(languages)}, default=str)

    except Exception as e:
        logger.error(f"Error en get_language_distribution: {e}")
        return json.dumps({"error": str(e)})


# Registro de funciones disponibles para el agente
TOOL_FUNCTIONS = {
    "get_top_repositories": get_top_repositories,
    "get_top_organizations": get_top_organizations,
    "get_top_users": get_top_users,
    "get_general_stats": get_general_stats,
    "search_entity": search_entity,
    "get_language_distribution": get_language_distribution,
}
