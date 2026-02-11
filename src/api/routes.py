"""
Definición de rutas/endpoints de la API.
"""
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import Optional, Dict, Any
from datetime import datetime

from ..github.extract import (
    extract_organization,
    extract_repository,
    extract_user,
    search_repositories
)
from ..github.rate_limit import get_rate_limit_info
from ..github.repositories_ingestion import IngestionEngine
from ..github.user_ingestion import UserIngestionEngine
from ..github.organization_ingestion import OrganizationIngestionEngine
from ..github.repositories_enrichment import EnrichmentEngine
from ..github.user_enrichment import UserEnrichmentEngine
from ..github.organization_enrichment import OrganizationEnrichmentEngine
from ..github.graphql_client import GitHubGraphQLClient
from ..core.logger import logger
from ..core.config import config, ingestion_config
from ..core.mongo_repository import MongoRepository

# Router principal
router = APIRouter()

# Estado global para tareas en background
background_tasks_status: Dict[str, Dict[str, Any]] = {}


@router.get("/")
async def root():
    """Endpoint raíz."""
    return {
        "message": "TFG Backend API",
        "version": "1.0.0",
        "status": "running"
    }


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@router.get("/stats")
async def get_stats():
    """
    Obtiene estadísticas generales del sistema (Simple counts).
    Retorna el conteo total de repositorios, usuarios y organizaciones.
    
    NOTA: Para dashboard completo con caché, usar /dashboard/stats
    """
    try:
        from ..core.db import db
        
        # Asegurar conexión activa (reconecta automáticamente si está caída)
        db.ensure_connection()
        
        # Obtener colecciones
        repos_collection = db.get_collection("repositories")
        users_collection = db.get_collection("users")
        orgs_collection = db.get_collection("organizations")
        
        # Contar documentos con timeout de 5 segundos
        repos_count = repos_collection.count_documents({}, maxTimeMS=5000)
        users_count = users_collection.count_documents({}, maxTimeMS=5000)
        orgs_count = orgs_collection.count_documents({}, maxTimeMS=5000)
        
        return {
            "repositories": repos_count,
            "users": users_count,
            "organizations": orgs_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        error_msg = f"Error al obtener estadísticas: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    force_refresh: bool = Query(default=False, description="Forzar recálculo ignorando caché"),
    org: Optional[str] = Query(default=None, description="Filtrar por organización (login)"),
    language: Optional[str] = Query(default=None, description="Filtrar por lenguaje de programación"),
    repo: Optional[str] = Query(default=None, description="Filtrar por repositorio (full_name)"),
    collab_type: Optional[str] = Query(default=None, description="Tipo de colaborador: 'contributors' (con commits), 'reviewers' (solo mencionables), 'all'"),
    include_bots: bool = Query(default=False, description="Incluir cuentas de bots en el análisis de colaboradores")
):
    """
    Endpoint COMPLETO para dashboard con sistema de caché MongoDB.
    
    Pre-calcula TODAS las métricas que necesita el frontend:
    - KPIs: totales, promedios, top language
    - Gráficos: top orgs, top repos, top users, distribución de lenguajes
    - Grafo: nodos y enlaces pre-filtrados (top elementos)
    - Tablas: top repos y users para detalle
    
    Filtros opcionales:
    - org: filtra repos por owner.login y users por organizations
    - language: filtra repos por primary_language
    - repo: filtra por repositorio específico (muestra sus colaboradores)
    - collab_type: tipo de colaborador (contributors/reviewers/all)
    - include_bots: incluir bots (dependabot, github-actions, etc.)
    
    Estrategia de Caché:
    - Solo usa caché cuando NO hay filtros activos
    - Con filtros: calcula en tiempo real (~50-100ms)
    """
    try:
        from ..core.db import db
        from datetime import timedelta
        
        # Asegurar conexión activa
        db.ensure_connection()
        
        # Configuración de caché (1 hora - más frecuente para datos dinámicos)
        CACHE_TTL_HOURS = 1
        current_time = datetime.now()
        
        # Detectar si hay filtros activos
        has_filters = bool(org or language or repo or collab_type or not include_bots)
        
        # 1. INTENTAR OBTENER CACHÉ (solo si no hay filtros y no se fuerza refresh)
        metrics_collection = db.get_collection("metrics")
        
        if not force_refresh and not has_filters:
            cached_stats = metrics_collection.find_one({"type": "dashboard_stats"})
            
            if cached_stats:
                updated_at = cached_stats.get("updated_at")
                if updated_at and isinstance(updated_at, datetime):
                    age_hours = (current_time - updated_at).total_seconds() / 3600
                    
                    # Si el caché es fresco (< 1h), retornarlo
                    if age_hours < CACHE_TTL_HOURS:
                        logger.info(f"📊 Cache HIT - Dashboard stats servido desde caché ({age_hours:.1f}h antiguo)")
                        
                        # Agregar metadatos de caché
                        response_data = cached_stats.get("data", {})
                        response_data["metadata"] = {
                            "cached": True,
                            "calculatedAt": updated_at.isoformat(),
                            "expiresAt": (updated_at + timedelta(hours=CACHE_TTL_HOURS)).isoformat(),
                            "ageHours": round(age_hours, 2)
                        }
                        return response_data
        
        # Log de filtros activos
        if has_filters:
            logger.info(f"📊 Calculando dashboard stats CON FILTROS: org={org}, language={language}, repo={repo}")
        else:
            logger.info("📊 Calculando dashboard stats COMPLETO desde MongoDB...")
        
        # 2. CALCULAR ESTADÍSTICAS
        repos_collection = db.get_collection("repositories")
        users_collection = db.get_collection("users")
        orgs_collection = db.get_collection("organizations")
        
        # === Construir filtros base para MongoDB ===
        repo_filter = {}
        user_filter = {}
        org_filter = {}
        
        if org:
            repo_filter["$or"] = [
                {"owner.login": org},
                {"organization.login": org}
            ]
            # Filtrar usuarios que pertenecen a esta org
            # organizations puede ser array de strings o array de objetos con login
            user_filter["$or"] = [
                {"organizations": org},
                {"organizations.login": org},
                {"organizations": {"$elemMatch": {"login": org}}}
            ]
            # Filtrar solo la org seleccionada
            org_filter["login"] = org
        
        if language:
            repo_filter["$or"] = repo_filter.get("$or", [])
            # Añadir filtro de lenguaje (puede ser string o objeto con .name)
            lang_filter = {"$or": [
                {"primary_language.name": language},
                {"primary_language": language}
            ]}
            if repo_filter.get("$or"):
                # Combinar con filtro de org usando $and
                existing_or = repo_filter.pop("$or")
                repo_filter["$and"] = [{"$or": existing_or}, lang_filter]
            else:
                repo_filter.update(lang_filter)
        
        # === KPIs: Conteos (filtrados si aplica) ===
        total_repos = repos_collection.count_documents(repo_filter, maxTimeMS=10000) if repo_filter else repos_collection.count_documents({}, maxTimeMS=10000)
        
        # Para usuarios, si hay filtro de org o language, contar desde colaboradores de repos
        if org or language:
            # Contar usuarios únicos desde los colaboradores de los repos filtrados
            users_pipeline = [
                {"$match": repo_filter} if repo_filter else {"$match": {}},
                {"$unwind": {"path": "$collaborators", "preserveNullAndEmptyArrays": False}},
                {"$group": {"_id": "$collaborators.login"}},
                {"$count": "total"}
            ]
            users_count_result = list(repos_collection.aggregate(users_pipeline, maxTimeMS=15000))
            total_users = users_count_result[0]["total"] if users_count_result else 0
        else:
            total_users = users_collection.count_documents({}, maxTimeMS=10000)
        
        # Orgs: si hay filtro, contar solo las orgs relevantes
        if org:
            total_orgs = orgs_collection.count_documents(org_filter, maxTimeMS=10000)
        elif language:
            # Contar orgs únicas que tienen repos en ese lenguaje
            orgs_pipeline = [
                {"$match": repo_filter},
                {"$group": {"_id": {"$ifNull": ["$owner.login", "$organization.login"]}}},
                {"$match": {"_id": {"$ne": None}}},
                {"$count": "total"}
            ]
            orgs_count_result = list(repos_collection.aggregate(orgs_pipeline, maxTimeMS=15000))
            total_orgs = orgs_count_result[0]["total"] if orgs_count_result else 0
        else:
            total_orgs = orgs_collection.count_documents({}, maxTimeMS=10000)
        
        # === KPIs: Promedios (filtrados si aplica) ===
        avg_stars_pipeline = []
        if repo_filter:
            avg_stars_pipeline.append({"$match": repo_filter})
        avg_stars_pipeline.append({"$group": {"_id": None, "avgStars": {"$avg": "$stargazer_count"}}})
        avg_stars_result = list(repos_collection.aggregate(avg_stars_pipeline))
        avg_stars = round(avg_stars_result[0]["avgStars"], 2) if avg_stars_result else 0
        
        avg_expertise_pipeline = [
            {"$match": {"quantum_expertise_score": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": None, "avgExpertise": {"$avg": "$quantum_expertise_score"}}}
        ]
        avg_expertise_result = list(users_collection.aggregate(avg_expertise_pipeline))
        avg_expertise = round(avg_expertise_result[0]["avgExpertise"], 2) if avg_expertise_result else 0
        
        # === DISTRIBUCIÓN DE LENGUAJES (para el PieChart) ===
        # IMPORTANTE: Solo filtrar por org, NO por language
        # (filtrar lenguajes por lenguaje no tiene sentido - mostraría solo 1 al 100%)
        lang_match = {"primary_language": {"$exists": True, "$ne": None}}
        if org:
            # Solo aplicar filtro de organización, no de lenguaje
            lang_match["$or"] = [
                {"owner.login": org},
                {"organization.login": org}
            ]
        
        language_pipeline = [
            {"$match": lang_match},
            {"$group": {
                "_id": {"$ifNull": ["$primary_language.name", "$primary_language"]},
                "count": {"$sum": 1}
            }},
            {"$sort": {"count": -1}},
            {"$project": {"_id": 0, "name": "$_id", "value": "$count"}}
        ]
        language_distribution = list(repos_collection.aggregate(language_pipeline))
        
        # Top language para KPI
        top_language = language_distribution[0]["name"] if language_distribution else "N/A"
        
        kpis = {
            "totalRepos": total_repos,
            "totalUsers": total_users,
            "totalOrgs": total_orgs,
            "avgStars": avg_stars,
            "avgExpertise": avg_expertise,
            "topLanguage": top_language
        }
        
        # === CHART: TOP 10 ORGANIZACIONES (por repos) ===
        # Si hay filtro de lenguaje, calcular dinámicamente desde repos
        # Si no, usar datos pre-calculados de la colección organizations
        if language:
            # Calcular repos por org filtrando por lenguaje
            lang_filter_for_orgs = {"$or": [
                {"primary_language.name": language},
                {"primary_language": language}
            ]}
            
            top_orgs_pipeline = [
                {"$match": lang_filter_for_orgs},
                {"$group": {
                    "_id": {"$ifNull": ["$owner.login", "$organization.login"]},
                    "quantum_repositories_count": {"$sum": 1},
                    "total_stars": {"$sum": {"$ifNull": ["$stargazer_count", 0]}}
                }},
                {"$match": {"_id": {"$ne": None}}},
                {"$sort": {"quantum_repositories_count": -1}},
                {"$limit": 10},
                {"$lookup": {
                    "from": "organizations",
                    "localField": "_id",
                    "foreignField": "login",
                    "as": "org_info"
                }},
                {"$project": {
                    "_id": 0,
                    "login": "$_id",
                    "name": {"$arrayElemAt": ["$org_info.name", 0]},
                    "avatar_url": {"$arrayElemAt": ["$org_info.avatar_url", 0]},
                    "quantum_repositories_count": 1,
                    "total_stars": 1,
                    "quantum_focus_score": {"$ifNull": [{"$arrayElemAt": ["$org_info.quantum_focus_score", 0]}, 0]}
                }}
            ]
            chart_orgs = list(repos_collection.aggregate(top_orgs_pipeline))
        else:
            # Sin filtro de lenguaje: usar datos pre-calculados
            top_orgs_pipeline = [
                {"$project": {
                    "_id": 0,
                    "login": 1,
                    "name": 1,
                    "avatar_url": 1,
                    "quantum_repositories_count": {"$ifNull": ["$quantum_repositories_count", 0]},
                    "total_stars": {"$ifNull": ["$total_stars", 0]},
                    "quantum_focus_score": {"$ifNull": ["$quantum_focus_score", 0]}
                }},
                {"$sort": {"quantum_repositories_count": -1}},
                {"$limit": 10}
            ]
            chart_orgs = list(orgs_collection.aggregate(top_orgs_pipeline))
        
        # === CHART: TOP 10 REPOSITORIOS POR DIFERENTES MÉTRICAS ===
        repo_base_projection = {
            "_id": 0,
            "id": 1,
            "name": 1,
            "full_name": 1,
            "description": 1,
            "stargazer_count": {"$ifNull": ["$stargazer_count", 0]},
            "fork_count": {"$ifNull": ["$fork_count", 0]},
            "collaborators_count": {"$ifNull": ["$collaborators_count", 0]},
            "primary_language": 1,
            "owner": 1
        }
        
        # Crear pipeline base con filtro opcional
        def make_repo_pipeline(sort_field, limit=10):
            pipeline = []
            if repo_filter:
                pipeline.append({"$match": repo_filter})
            pipeline.append({"$project": repo_base_projection})
            pipeline.append({"$sort": {sort_field: -1}})
            pipeline.append({"$limit": limit})
            return pipeline
        
        # Top 10 por estrellas
        chart_repos_stars = list(repos_collection.aggregate(make_repo_pipeline("stargazer_count")))
        
        # Top 10 por forks
        chart_repos_forks = list(repos_collection.aggregate(make_repo_pipeline("fork_count")))
        
        # Top 10 por colaboradores
        chart_repos_collabs = list(repos_collection.aggregate(make_repo_pipeline("collaborators_count")))
        
        # Helper para detectar si un login es un bot
        def is_bot(login: str) -> bool:
            if not login:
                return False
            login_lower = login.lower()
            return (
                "[bot]" in login_lower or
                login_lower.endswith("-bot") or
                login_lower.startswith("bot-") or
                login_lower in ["dependabot", "renovate", "greenkeeper", "snyk-bot", "codecov", "sonarcloud"]
            )
        
        # === CHART: TOP 10 USUARIOS (por contribuciones) ===
        # Prioridad de filtros: repo > language > org > global
        if repo:
            # Filtro por repo específico: mostrar sus colaboradores directamente
            repo_doc = repos_collection.find_one({"full_name": repo})
            if repo_doc and repo_doc.get("collaborators"):
                # Extraer colaboradores del repo
                collaborators = repo_doc.get("collaborators", [])
                
                # Filtrar bots si no se incluyen
                if not include_bots:
                    collaborators = [c for c in collaborators if not is_bot(c.get("login", ""))]
                
                # Filtrar por tipo de colaborador si se especifica
                if collab_type == "contributors":
                    # Solo los que han hecho commits
                    collaborators = [c for c in collaborators if c.get("has_commits", False)]
                elif collab_type == "reviewers":
                    # Solo los que son mencionables pero NO han hecho commits (triage/reviewers)
                    collaborators = [c for c in collaborators if c.get("is_mentionable", False) and not c.get("has_commits", False)]
                # collab_type == "all" o None -> no filtrar
                
                # Enriquecer con info de users
                chart_users = []
                for collab in sorted(collaborators, key=lambda x: x.get("contributions", 0), reverse=True)[:10]:
                    user_info = users_collection.find_one({"login": collab.get("login")})
                    chart_users.append({
                        "login": collab.get("login"),
                        "name": user_info.get("name") if user_info else None,
                        "avatar_url": collab.get("avatar_url") or (user_info.get("avatar_url") if user_info else None),
                        "relevant_repos_count": 1,
                        "total_contributions": collab.get("contributions", 0),
                        "has_commits": collab.get("has_commits", False),
                        "is_mentionable": collab.get("is_mentionable", False),
                        "total_commit_contributions": user_info.get("total_commit_contributions", 0) if user_info else 0,
                        "total_pr_contributions": user_info.get("total_pr_contributions", 0) if user_info else 0,
                        "total_pr_review_contributions": user_info.get("total_pr_review_contributions", 0) if user_info else 0,
                        "total_issue_contributions": user_info.get("total_issue_contributions", 0) if user_info else 0,
                        "organizations": user_info.get("organizations", []) if user_info else []
                    })
            else:
                chart_users = []
        elif language:
            # Filtrar repos por lenguaje y extraer colaboradores
            lang_filter_for_users = {"$or": [
                {"primary_language.name": language},
                {"primary_language": language}
            ]}
            
            # Agregar filtro de org si también está activo
            if org:
                lang_filter_for_users["$and"] = [
                    {"$or": lang_filter_for_users.pop("$or")},
                    {"$or": [{"owner.login": org}, {"organization.login": org}]}
                ]
            
            # Pipeline: repos -> unwind collaborators -> group by user -> lookup user info
            top_users_pipeline = [
                {"$match": lang_filter_for_users},
                {"$match": {"collaborators": {"$exists": True, "$ne": []}}},
                {"$unwind": "$collaborators"},
            ]
            
            # Filtrar bots si no se incluyen
            if not include_bots:
                top_users_pipeline.append({"$match": {
                    "collaborators.login": {
                        "$not": {"$regex": "\\[bot\\]|^bot-|-bot$", "$options": "i"}
                    }
                }})
            
            # Filtrar por tipo de colaborador si se especifica
            if collab_type == "contributors":
                # Solo los que han hecho commits
                top_users_pipeline.append({"$match": {"collaborators.has_commits": True}})
            elif collab_type == "reviewers":
                # Solo los mencionables que NO han hecho commits
                top_users_pipeline.append({"$match": {
                    "collaborators.is_mentionable": True,
                    "$or": [
                        {"collaborators.has_commits": False},
                        {"collaborators.has_commits": {"$exists": False}}
                    ]
                }})
            
            # Continuar con agrupación y proyección
            top_users_pipeline.extend([
                {"$group": {
                    "_id": "$collaborators.login",
                    "repos_in_language": {"$sum": 1},
                    "total_contributions": {"$sum": {"$ifNull": ["$collaborators.contributions", 0]}},
                    "has_commits": {"$max": {"$ifNull": ["$collaborators.has_commits", False]}},
                    "is_mentionable": {"$max": {"$ifNull": ["$collaborators.is_mentionable", False]}}
                }},
                {"$match": {"_id": {"$ne": None}}},
                {"$sort": {"total_contributions": -1, "repos_in_language": -1}},
                {"$limit": 10},
                {"$lookup": {
                    "from": "users",
                    "localField": "_id",
                    "foreignField": "login",
                    "as": "user_info"
                }},
                {"$project": {
                    "_id": 0,
                    "login": "$_id",
                    "name": {"$arrayElemAt": ["$user_info.name", 0]},
                    "avatar_url": {"$arrayElemAt": ["$user_info.avatar_url", 0]},
                    "relevant_repos_count": "$repos_in_language",
                    "total_contributions": 1,
                    "has_commits": 1,
                    "is_mentionable": 1,
                    "total_commit_contributions": {"$ifNull": [{"$arrayElemAt": ["$user_info.total_commit_contributions", 0]}, 0]},
                    "total_pr_contributions": {"$ifNull": [{"$arrayElemAt": ["$user_info.total_pr_contributions", 0]}, 0]},
                    "total_pr_review_contributions": {"$ifNull": [{"$arrayElemAt": ["$user_info.total_pr_review_contributions", 0]}, 0]},
                    "total_issue_contributions": {"$ifNull": [{"$arrayElemAt": ["$user_info.total_issue_contributions", 0]}, 0]},
                    "organizations": {"$ifNull": [{"$arrayElemAt": ["$user_info.organizations", 0]}, []]}
                }}
            ])
            chart_users = list(repos_collection.aggregate(top_users_pipeline))
        else:
            # Sin filtro de lenguaje ni repo
            # Si hay collab_type o filtro de bots, necesitamos agregar desde repos
            if (collab_type and collab_type != "all") or not include_bots:
                # Pipeline desde repos para filtrar por tipo de colaborador
                base_match = {"collaborators": {"$exists": True, "$ne": []}}
                if org:
                    base_match["$or"] = [{"owner.login": org}, {"organization.login": org}]
                
                top_users_pipeline = [
                    {"$match": base_match},
                    {"$unwind": "$collaborators"},
                ]
                
                # Filtrar bots si no se incluyen
                if not include_bots:
                    top_users_pipeline.append({"$match": {
                        "collaborators.login": {
                            "$not": {"$regex": "\\[bot\\]|^bot-|-bot$", "$options": "i"}
                        }
                    }})
                
                # Filtrar por tipo de colaborador
                if collab_type == "contributors":
                    top_users_pipeline.append({"$match": {"collaborators.has_commits": True}})
                elif collab_type == "reviewers":
                    top_users_pipeline.append({"$match": {
                        "collaborators.is_mentionable": True,
                        "$or": [
                            {"collaborators.has_commits": False},
                            {"collaborators.has_commits": {"$exists": False}}
                        ]
                    }})
                
                top_users_pipeline.extend([
                    {"$group": {
                        "_id": "$collaborators.login",
                        "repos_count": {"$sum": 1},
                        "total_contributions": {"$sum": {"$ifNull": ["$collaborators.contributions", 0]}},
                        "has_commits": {"$max": {"$ifNull": ["$collaborators.has_commits", False]}},
                        "is_mentionable": {"$max": {"$ifNull": ["$collaborators.is_mentionable", False]}}
                    }},
                    {"$match": {"_id": {"$ne": None}}},
                    {"$sort": {"total_contributions": -1, "repos_count": -1}},
                    {"$limit": 10},
                    {"$lookup": {
                        "from": "users",
                        "localField": "_id",
                        "foreignField": "login",
                        "as": "user_info"
                    }},
                    {"$project": {
                        "_id": 0,
                        "login": "$_id",
                        "name": {"$arrayElemAt": ["$user_info.name", 0]},
                        "avatar_url": {"$arrayElemAt": ["$user_info.avatar_url", 0]},
                        "relevant_repos_count": "$repos_count",
                        "total_contributions": 1,
                        "has_commits": 1,
                        "is_mentionable": 1,
                        "total_commit_contributions": {"$ifNull": [{"$arrayElemAt": ["$user_info.total_commit_contributions", 0]}, 0]},
                        "total_pr_contributions": {"$ifNull": [{"$arrayElemAt": ["$user_info.total_pr_contributions", 0]}, 0]},
                        "total_pr_review_contributions": {"$ifNull": [{"$arrayElemAt": ["$user_info.total_pr_review_contributions", 0]}, 0]},
                        "total_issue_contributions": {"$ifNull": [{"$arrayElemAt": ["$user_info.total_issue_contributions", 0]}, 0]},
                        "organizations": {"$ifNull": [{"$arrayElemAt": ["$user_info.organizations", 0]}, []]}
                    }}
                ])
                chart_users = list(repos_collection.aggregate(top_users_pipeline))
            else:
                # Sin collab_type: usar datos pre-calculados de users collection
                user_match = {"relevant_repos_count": {"$gt": 0}}
                if user_filter:
                    user_match.update(user_filter)
                
                top_users_pipeline = [
                    {"$match": user_match},
                    {"$project": {
                        "_id": 0,
                        "id": 1,
                        "login": 1,
                        "name": 1,
                        "avatar_url": 1,
                        "relevant_repos_count": {"$ifNull": ["$relevant_repos_count", 0]},
                        "total_commit_contributions": {"$ifNull": ["$total_commit_contributions", 0]},
                        "total_pr_contributions": {"$ifNull": ["$total_pr_contributions", 0]},
                        "total_pr_review_contributions": {"$ifNull": ["$total_pr_review_contributions", 0]},
                        "total_issue_contributions": {"$ifNull": ["$total_issue_contributions", 0]},
                        "total_contributions": {
                            "$add": [
                                {"$ifNull": ["$total_commit_contributions", 0]},
                                {"$ifNull": ["$total_pr_contributions", 0]},
                                {"$ifNull": ["$total_pr_review_contributions", 0]},
                                {"$ifNull": ["$total_issue_contributions", 0]}
                            ]
                        },
                        "organizations": 1
                    }},
                    {"$sort": {"total_contributions": -1, "relevant_repos_count": -1}},
                    {"$limit": 10}
                ]
                chart_users = list(users_collection.aggregate(top_users_pipeline))
        
        # === GRAFO: Nodos y enlaces pre-calculados ===
        # Top 15 orgs para el grafo
        graph_orgs_pipeline = [
            {"$project": {
                "_id": 0,
                "id": 1,
                "login": 1,
                "name": 1,
                "avatar_url": 1,
                "quantum_focus_score": {"$ifNull": ["$quantum_focus_score", 0]}
            }},
            {"$sort": {"quantum_focus_score": -1}},
            {"$limit": 15}
        ]
        graph_orgs = list(orgs_collection.aggregate(graph_orgs_pipeline))
        
        # Top 25 repos para el grafo (con owner para enlaces)
        graph_repos_pipeline = [
            {"$project": {
                "_id": 0,
                "id": 1,
                "name": 1,
                "full_name": 1,
                "stargazer_count": {"$ifNull": ["$stargazer_count", 0]},
                "owner": 1,
                "collaborators": {"$slice": [{"$ifNull": ["$collaborators", []]}, 10]}  # Max 10 collaborators
            }},
            {"$sort": {"stargazer_count": -1}},
            {"$limit": 25}
        ]
        graph_repos = list(repos_collection.aggregate(graph_repos_pipeline))
        
        # Top 40 users para el grafo (con organizations para enlaces)
        graph_users_pipeline = [
            {"$match": {"quantum_expertise_score": {"$exists": True}}},
            {"$project": {
                "_id": 0,
                "id": 1,
                "login": 1,
                "name": 1,
                "avatar_url": 1,
                "quantum_expertise_score": {"$ifNull": ["$quantum_expertise_score", 0]},
                "organizations": {"$slice": [{"$ifNull": ["$organizations", []]}, 5]},  # Max 5 orgs
                "company": 1
            }},
            {"$sort": {"quantum_expertise_score": -1}},
            {"$limit": 40}
        ]
        graph_users = list(users_collection.aggregate(graph_users_pipeline))
        
        # === TABLAS: Top 20 para detalle ===
        table_repos_pipeline = [
            {"$project": {
                "_id": 0,
                "id": 1,
                "name": 1,
                "full_name": 1,
                "description": 1,
                "stargazer_count": {"$ifNull": ["$stargazer_count", 0]},
                "fork_count": {"$ifNull": ["$fork_count", 0]},
                "primary_language": 1,
                "owner": 1,
                "url": 1
            }},
            {"$sort": {"stargazer_count": -1}},
            {"$limit": 20}
        ]
        table_repos = list(repos_collection.aggregate(table_repos_pipeline))
        
        table_users_pipeline = [
            {"$match": {"quantum_expertise_score": {"$exists": True}}},
            {"$project": {
                "_id": 0,
                "id": 1,
                "login": 1,
                "name": 1,
                "avatar_url": 1,
                "quantum_expertise_score": {"$ifNull": ["$quantum_expertise_score", 0]},
                "followers_count": {"$ifNull": ["$followers_count", 0]},
                "relevant_repos_count": {"$ifNull": ["$relevant_repos_count", 0]},
                "organizations": {"$slice": [{"$ifNull": ["$organizations", []]}, 5]},
                "url": 1
            }},
            {"$sort": {"quantum_expertise_score": -1}},
            {"$limit": 20}
        ]
        table_users = list(users_collection.aggregate(table_users_pipeline))
        
        # === LISTAS PARA FILTROS ===
        # Lista de todas las orgs (solo login y name para dropdown)
        filter_orgs_pipeline = [
            {"$project": {"_id": 0, "login": 1, "name": 1}},
            {"$sort": {"login": 1}}
        ]
        filter_orgs = list(orgs_collection.aggregate(filter_orgs_pipeline))
        
        # Lista de todos los lenguajes únicos
        filter_languages = [lang["name"] for lang in language_distribution]
        
        # 3. PREPARAR RESPUESTA COMPLETA
        response_data = {
            "kpis": kpis,
            "charts": {
                "organizations": chart_orgs,
                "repositories": {
                    "byStars": chart_repos_stars,
                    "byForks": chart_repos_forks,
                    "byCollaborators": chart_repos_collabs
                },
                "users": chart_users,
                "languageDistribution": language_distribution
            },
            "graph": {
                "organizations": graph_orgs,
                "repositories": graph_repos,
                "users": graph_users
            },
            "tables": {
                "repositories": table_repos,
                "users": table_users
            },
            "filters": {
                "organizations": filter_orgs,
                "languages": filter_languages
            },
            "metadata": {
                "cached": False,
                "calculatedAt": current_time.isoformat(),
                "expiresAt": (current_time + timedelta(hours=CACHE_TTL_HOURS)).isoformat(),
                "ageHours": 0,
                "activeFilters": {
                    "org": org,
                    "language": language,
                    "repo": repo,
                    "collab_type": collab_type,
                    "include_bots": include_bots
                } if has_filters else None
            }
        }
        
        # 4. GUARDAR EN CACHÉ (Upsert) - SOLO si no hay filtros activos
        if not has_filters:
            cache_document = {
                "type": "dashboard_stats",
                "data": response_data,
                "updated_at": current_time
            }
            
            metrics_collection.update_one(
                {"type": "dashboard_stats"},
                {"$set": cache_document},
                upsert=True
            )
            
            logger.info(f"✅ Dashboard stats COMPLETO calculado y guardado en caché (válido por {CACHE_TTL_HOURS}h)")
        else:
            logger.info(f"✅ Dashboard stats CON FILTROS calculado (no cacheado)")
        
        return response_data
        
    except Exception as e:
        error_msg = f"Error al obtener dashboard stats: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/dashboard/refresh-metrics")
async def refresh_dashboard_metrics():
    """
    Fuerza el recálculo de métricas del dashboard.
    Útil después de ingestas/enriquecimientos.
    """
    try:
        # Llamar al endpoint de stats con force_refresh
        return await get_dashboard_stats(force_refresh=True)
    except Exception as e:
        logger.error(f"Error al refrescar métricas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rate-limit")
async def rate_limit():
    """
    Obtiene información del rate limit de GitHub.
    """
    try:
        rate_limit_info = get_rate_limit_info()
        return rate_limit_info
    except Exception as e:
        logger.error(f"Error al obtener rate limit: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/organizations/github/{org_login}")
async def get_organization(
    org_login: str,
    save_to_db: bool = Query(default=True, description="Guardar en base de datos")
):
    """
    Obtiene información de una organización de GitHub.
    
    Args:
        org_login: Login de la organización
        save_to_db: Si se debe guardar en la base de datos
    """
    try:
        org_data = extract_organization(org_login, save_to_db)
        if not org_data:
            raise HTTPException(status_code=404, detail="Organización no encontrada")
        return org_data
    except Exception as e:
        logger.error(f"Error al obtener organización: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/repositories/github/{owner}/{name}")
async def get_repository(
    owner: str,
    name: str,
    save_to_db: bool = Query(default=True, description="Guardar en base de datos")
):
    """
    Obtiene información de un repositorio de GitHub.
    
    Args:
        owner: Propietario del repositorio
        name: Nombre del repositorio
        save_to_db: Si se debe guardar en la base de datos
    """
    try:
        repo_data = extract_repository(owner, name, save_to_db)
        if not repo_data:
            raise HTTPException(status_code=404, detail="Repositorio no encontrado")
        return repo_data
    except Exception as e:
        logger.error(f"Error al obtener repositorio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/github/{user_login}")
async def get_user(
    user_login: str,
    save_to_db: bool = Query(default=True, description="Guardar en base de datos")
):
    """
    Obtiene información de un usuario de GitHub.
    
    Args:
        user_login: Login del usuario
        save_to_db: Si se debe guardar en la base de datos
    """
    try:
        user_data = extract_user(user_login, save_to_db)
        if not user_data:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return user_data
    except Exception as e:
        logger.error(f"Error al obtener usuario: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search/repositories")
async def search_repos(
    query: str = Query(..., description="Query de búsqueda"),
    first: int = Query(default=10, ge=1, le=100, description="Número de resultados"),
    save_to_db: bool = Query(default=False, description="Guardar en base de datos")
):
    """
    Busca repositorios en GitHub.
    
    Args:
        query: Query de búsqueda
        first: Número de resultados (1-100)
        save_to_db: Si se debe guardar en la base de datos
    """
    try:
        repositories = search_repositories(query, first, save_to_db)
        return {
            "query": query,
            "count": len(repositories),
            "repositories": repositories
        }
    except Exception as e:
        logger.error(f"Error al buscar repositorios: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE LISTADO (desde base de datos)
# ============================================================================

@router.get("/repositories")
async def list_repositories(
    skip: int = Query(default=0, ge=0, description="Número de documentos a saltar"),
    limit: int = Query(default=0, ge=0, description="Límite de resultados (0 = sin límite)"),
    language: Optional[str] = Query(None, description="Filtrar por lenguaje"),
    min_stars: Optional[int] = Query(None, ge=0, description="Estrellas mínimas")
):
    """
    Lista repositorios desde la base de datos con paginación y filtros.
    """
    try:
        from ..core.db import db
        
        # Construir filtro
        filter_query = {}
        if language:
            filter_query["primary_language.name"] = language
        if min_stars is not None:
            filter_query["stargazer_count"] = {"$gte": min_stars}
        
        # Obtener repositorios
        repo_collection = db.get_collection("repositories")
        cursor = repo_collection.find(filter_query).skip(skip)
        if limit > 0:
            cursor = cursor.limit(limit)
        repositories = list(cursor)
        
        # Convertir ObjectId a string
        for repo in repositories:
            repo["_id"] = str(repo["_id"])
        
        return repositories
    except Exception as e:
        logger.error(f"Error al listar repositorios: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/repositories/db/{repo_id}")
async def get_repository_by_id(repo_id: str):
    """
    Obtiene un repositorio por su ID de MongoDB.
    """
    try:
        from ..core.db import db
        from bson import ObjectId
        
        repo_collection = db.get_collection("repositories")
        repo = repo_collection.find_one({"_id": ObjectId(repo_id)})
        
        if not repo:
            raise HTTPException(status_code=404, detail="Repositorio no encontrado")
        
        repo["_id"] = str(repo["_id"])
        return repo
    except Exception as e:
        logger.error(f"Error al obtener repositorio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users")
async def list_users(
    skip: int = Query(default=0, ge=0, description="Número de documentos a saltar"),
    limit: int = Query(default=0, ge=0, description="Límite de resultados (0 = sin límite)")
):
    """
    Lista usuarios desde la base de datos con paginación.
    """
    try:
        from ..core.db import db
        
        user_collection = db.get_collection("users")
        cursor = user_collection.find({}).skip(skip)
        if limit > 0:
            cursor = cursor.limit(limit)
        users = list(cursor)
        
        # Convertir ObjectId a string
        for user in users:
            user["_id"] = str(user["_id"])
        
        return users
    except Exception as e:
        logger.error(f"Error al listar usuarios: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/db/{user_id}")
async def get_user_by_id(user_id: str):
    """
    Obtiene un usuario por su ID de MongoDB.
    """
    try:
        from ..core.db import db
        from bson import ObjectId
        
        user_collection = db.get_collection("users")
        user = user_collection.find_one({"_id": ObjectId(user_id)})
        
        if not user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        user["_id"] = str(user["_id"])
        return user
    except Exception as e:
        logger.error(f"Error al obtener usuario: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/organizations")
async def list_organizations(
    skip: int = Query(default=0, ge=0, description="Número de documentos a saltar"),
    limit: int = Query(default=0, ge=0, description="Límite de resultados (0 = sin límite)")
):
    """
    Lista organizaciones desde la base de datos con paginación.
    """
    try:
        from ..core.db import db
        
        org_collection = db.get_collection("organizations")
        cursor = org_collection.find({}).skip(skip)
        if limit > 0:
            cursor = cursor.limit(limit)
        organizations = list(cursor)
        
        # Convertir ObjectId a string
        for org in organizations:
            org["_id"] = str(org["_id"])
        
        return organizations
    except Exception as e:
        logger.error(f"Error al listar organizaciones: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/organizations/db/{org_id}")
async def get_organization_by_id(org_id: str):
    """
    Obtiene una organización por su ID de MongoDB.
    """
    try:
        from ..core.db import db
        from bson import ObjectId
        
        org_collection = db.get_collection("organizations")
        org = org_collection.find_one({"_id": ObjectId(org_id)})
        
        if not org:
            raise HTTPException(status_code=404, detail="Organización no encontrada")
        
        org["_id"] = str(org["_id"])
        return org
    except Exception as e:
        logger.error(f"Error al obtener organización: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE INGESTA
# ============================================================================

@router.post("/ingestion/repositories")
async def ingest_repositories(
    background_tasks: BackgroundTasks,
    max_results: Optional[int] = Query(None, description="Máximo de repositorios a ingerir"),
    incremental: bool = Query(False, description="Modo incremental (solo actualizar cambios)"),
    use_segmentation: bool = Query(True, description="Usar segmentación dinámica para más de 1000 repos")
):
    """
    Ejecuta la ingesta de repositorios usando la configuración de ingestion_config.json.
    
    Args:
        max_results: Límite opcional de repositorios a ingerir
        incremental: Si True, solo actualiza documentos modificados
        use_segmentation: Si True, usa segmentación para superar límite de 1000 resultados
        
    Returns:
        Estado inicial de la tarea y task_id para consultar progreso
    """
    try:
        task_id = f"repo_ingestion_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Inicializar estado de la tarea
        background_tasks_status[task_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "progress": "Inicializando ingesta de repositorios...",
            "stats": None,
            "error": None
        }
        
        # Ejecutar en background
        background_tasks.add_task(
            _run_repository_ingestion,
            task_id,
            max_results,
            incremental,
            use_segmentation
        )
        
        logger.info(f"✅ Tarea de ingesta de repositorios iniciada: {task_id}")
        
        return {
            "task_id": task_id,
            "status": "running",
            "message": "Ingesta de repositorios iniciada en segundo plano",
            "check_status_url": f"/api/v1/ingestion/status/{task_id}"
        }
        
    except Exception as e:
        logger.error(f"Error al iniciar ingesta de repositorios: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingestion/users")
async def ingest_users(
    background_tasks: BackgroundTasks,
    max_repos: Optional[int] = Query(None, description="Máximo de repositorios a procesar"),
    batch_size: int = Query(50, description="Tamaño del lote para procesamiento")
):
    """
    Ejecuta la ingesta de usuarios desde los repositorios ya ingestados.
    Extrae usuarios del campo 'collaborators' de cada repositorio.
    
    Args:
        max_repos: Límite opcional de repositorios a procesar
        batch_size: Tamaño del lote para procesamiento
        
    Returns:
        Estado inicial de la tarea y task_id para consultar progreso
    """
    try:
        task_id = f"user_ingestion_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        background_tasks_status[task_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "progress": "Inicializando ingesta de usuarios...",
            "stats": None,
            "error": None
        }
        
        background_tasks.add_task(
            _run_user_ingestion,
            task_id,
            max_repos,
            batch_size
        )
        
        logger.info(f"✅ Tarea de ingesta de usuarios iniciada: {task_id}")
        
        return {
            "task_id": task_id,
            "status": "running",
            "message": "Ingesta de usuarios iniciada en segundo plano",
            "check_status_url": f"/api/v1/ingestion/status/{task_id}"
        }
        
    except Exception as e:
        logger.error(f"Error al iniciar ingesta de usuarios: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE ENRIQUECIMIENTO
# ============================================================================

@router.post("/enrichment/repositories")
async def enrich_repositories(
    background_tasks: BackgroundTasks,
    max_repos: Optional[int] = Query(None, description="Máximo de repositorios a enriquecer"),
    force_reenrich: bool = Query(False, description="Re-enriquecer incluso repositorios ya enriquecidos"),
    batch_size: int = Query(10, description="Tamaño del lote para procesamiento")
):
    """
    Ejecuta el enriquecimiento de repositorios ya ingestados.
    Completa información faltante usando GraphQL y REST API.
    
    Args:
        max_repos: Límite opcional de repositorios a enriquecer
        force_reenrich: Si True, re-enriquece todos los repositorios
        batch_size: Tamaño del lote para procesamiento
        
    Returns:
        Estado inicial de la tarea y task_id para consultar progreso
    """
    try:
        task_id = f"repo_enrichment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        background_tasks_status[task_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "progress": "Inicializando enriquecimiento de repositorios...",
            "stats": None,
            "error": None
        }
        
        background_tasks.add_task(
            _run_repository_enrichment,
            task_id,
            max_repos,
            force_reenrich,
            batch_size
        )
        
        logger.info(f"✅ Tarea de enriquecimiento de repositorios iniciada: {task_id}")
        
        return {
            "task_id": task_id,
            "status": "running",
            "message": "Enriquecimiento de repositorios iniciado en segundo plano",
            "check_status_url": f"/api/v1/enrichment/status/{task_id}"
        }
        
    except Exception as e:
        logger.error(f"Error al iniciar enriquecimiento de repositorios: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/enrichment/users")
async def enrich_users(
    background_tasks: BackgroundTasks,
    max_users: Optional[int] = Query(None, description="Máximo de usuarios a enriquecer"),
    force_reenrich: bool = Query(False, description="Re-enriquecer incluso usuarios ya enriquecidos"),
    batch_size: int = Query(10, description="Tamaño del lote para procesamiento")
):
    """
    Ejecuta el enriquecimiento de usuarios ya ingestados.
    Completa información faltante usando GraphQL y REST API.
    
    Args:
        max_users: Límite opcional de usuarios a enriquecer
        force_reenrich: Si True, re-enriquece todos los usuarios
        batch_size: Tamaño del lote para procesamiento
        
    Returns:
        Estado inicial de la tarea y task_id para consultar progreso
    """
    try:
        task_id = f"user_enrichment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        background_tasks_status[task_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "progress": "Inicializando enriquecimiento de usuarios...",
            "stats": None,
            "error": None
        }
        
        background_tasks.add_task(
            _run_user_enrichment,
            task_id,
            max_users,
            force_reenrich,
            batch_size
        )
        
        logger.info(f"✅ Tarea de enriquecimiento de usuarios iniciada: {task_id}")
        
        return {
            "task_id": task_id,
            "status": "running",
            "message": "Enriquecimiento de usuarios iniciado en segundo plano",
            "check_status_url": f"/api/v1/enrichment/status/{task_id}"
        }
        
    except Exception as e:
        logger.error(f"Error al iniciar enriquecimiento de usuarios: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingestion/organizations")
async def ingest_organizations(
    background_tasks: BackgroundTasks,
    force_update: bool = Query(False, description="Actualizar organizaciones ya existentes"),
    batch_size: int = Query(5, description="Tamaño del lote para procesamiento")
):
    """
    Ejecuta la ingesta de organizaciones desde usuarios existentes.
    Estrategia Bottom-Up: descubre organizaciones desde los usuarios ya ingestados.
    
    Args:
        force_update: Si True, actualiza organizaciones existentes
        batch_size: Tamaño del lote para procesamiento (default 5 para Rate Limit)
        
    Returns:
        Estado inicial de la tarea y task_id para consultar progreso
    """
    try:
        task_id = f"org_ingestion_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        background_tasks_status[task_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "progress": "Inicializando ingesta de organizaciones...",
            "stats": None,
            "error": None
        }
        
        background_tasks.add_task(
            _run_organization_ingestion,
            task_id,
            force_update,
            batch_size
        )
        
        logger.info(f"✅ Tarea de ingesta de organizaciones iniciada: {task_id}")
        
        return {
            "task_id": task_id,
            "status": "running",
            "message": "Ingesta de organizaciones iniciada en segundo plano",
            "check_status_url": f"/api/v1/ingestion/status/{task_id}"
        }
        
    except Exception as e:
        logger.error(f"Error al iniciar ingesta de organizaciones: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/enrichment/organizations")
async def enrich_organizations(
    background_tasks: BackgroundTasks,
    max_orgs: Optional[int] = Query(None, description="Máximo de organizaciones a enriquecer"),
    force_reenrich: bool = Query(False, description="Re-enriquecer incluso organizaciones ya enriquecidas"),
    batch_size: int = Query(5, description="Tamaño del lote para procesamiento")
):
    """
    Ejecuta el enriquecimiento de organizaciones ya ingestadas.
    Calcula métricas quantum: quantum_focus_score, repos quantum, top contributors.
    
    Args:
        max_orgs: Límite opcional de organizaciones a enriquecer
        force_reenrich: Si True, re-enriquece todas las organizaciones
        batch_size: Tamaño del lote para procesamiento (default 5 para Rate Limit)
        
    Returns:
        Estado inicial de la tarea y task_id para consultar progreso
    """
    try:
        task_id = f"org_enrichment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        background_tasks_status[task_id] = {
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "progress": "Inicializando enriquecimiento de organizaciones...",
            "stats": None,
            "error": None
        }
        
        background_tasks.add_task(
            _run_organization_enrichment,
            task_id,
            max_orgs,
            force_reenrich,
            batch_size
        )
        
        logger.info(f"✅ Tarea de enriquecimiento de organizaciones iniciada: {task_id}")
        
        return {
            "task_id": task_id,
            "status": "running",
            "message": "Enriquecimiento de organizaciones iniciado en segundo plano",
            "check_status_url": f"/api/v1/enrichment/status/{task_id}"
        }
        
    except Exception as e:
        logger.error(f"Error al iniciar enriquecimiento de organizaciones: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ENDPOINTS DE ESTADO
# ============================================================================

@router.get("/ingestion/status/{task_id}")
@router.get("/enrichment/status/{task_id}")
async def get_task_status(task_id: str):
    """
    Consulta el estado de una tarea de ingesta o enriquecimiento.
    
    Args:
        task_id: ID de la tarea a consultar
        
    Returns:
        Estado actual de la tarea con estadísticas
    """
    if task_id not in background_tasks_status:
        raise HTTPException(status_code=404, detail=f"Tarea {task_id} no encontrada")
    
    return background_tasks_status[task_id]


@router.get("/tasks")
async def list_tasks():
    """
    Lista todas las tareas de ingesta y enriquecimiento.
    
    Returns:
        Lista de tareas con su estado
    """
    return {
        "total_tasks": len(background_tasks_status),
        "tasks": [
            {
                "task_id": task_id,
                "status": info["status"],
                "started_at": info["started_at"],
                "progress": info["progress"]
            }
            for task_id, info in background_tasks_status.items()
        ]
    }


# ============================================================================
# FUNCIONES AUXILIARES PARA BACKGROUND TASKS
# ============================================================================

def _run_repository_ingestion(
    task_id: str,
    max_results: Optional[int],
    incremental: bool,
    use_segmentation: bool
):
    """Ejecuta la ingesta de repositorios en background."""
    try:
        background_tasks_status[task_id]["progress"] = "Creando motor de ingesta..."
        
        # 1. Creamos el motor
        engine = IngestionEngine(incremental=incremental)
        
        # 2. Forzamos la configuración de segmentación según lo que pidió el usuario
        # (Esto asegura que el motor use segmentación si use_segmentation=True)
        if use_segmentation:
            # Inyectamos la preferencia en la configuración del motor
            if hasattr(engine.config, '_config_data'):
                engine.config._config_data['enable_segmentation'] = True
        
        background_tasks_status[task_id]["progress"] = "Ejecutando ingesta..."
        
        # 3. LLAMADA ÚNICA Y CORRECTA
        # El método run() ya decide internamente si usa segmentación o no
        stats = engine.run(max_results=max_results)
        
        background_tasks_status[task_id]["status"] = "completed"
        background_tasks_status[task_id]["progress"] = "Ingesta completada exitosamente"
        background_tasks_status[task_id]["stats"] = stats
        background_tasks_status[task_id]["completed_at"] = datetime.now().isoformat()
        
        logger.info(f"✅ Tarea {task_id} completada exitosamente")
        
    except Exception as e:
        logger.error(f"❌ Error en tarea {task_id}: {e}")
        background_tasks_status[task_id]["status"] = "failed"
        background_tasks_status[task_id]["progress"] = f"Error: {str(e)}"
        background_tasks_status[task_id]["error"] = str(e)
        background_tasks_status[task_id]["failed_at"] = datetime.now().isoformat()

def _run_user_ingestion(
    task_id: str,
    max_repos: Optional[int],
    batch_size: int
):
    """Ejecuta la ingesta de usuarios en background."""
    try:
        background_tasks_status[task_id]["progress"] = "Creando motor de ingesta de usuarios..."
        
        github_client = GitHubGraphQLClient()
        repos_repo = MongoRepository("repositories")
        users_repo = MongoRepository("users", unique_fields=["id"])
        
        engine = UserIngestionEngine(
            github_client=github_client,
            repos_repository=repos_repo,
            users_repository=users_repo,
            batch_size=batch_size
        )
        
        background_tasks_status[task_id]["progress"] = "Ejecutando ingesta de usuarios..."
        
        stats = engine.run(max_repos=max_repos)
        
        background_tasks_status[task_id]["status"] = "completed"
        background_tasks_status[task_id]["progress"] = "Ingesta de usuarios completada"
        background_tasks_status[task_id]["stats"] = stats
        background_tasks_status[task_id]["completed_at"] = datetime.now().isoformat()
        
        logger.info(f"✅ Tarea {task_id} completada exitosamente")
        
    except Exception as e:
        logger.error(f"❌ Error en tarea {task_id}: {e}")
        background_tasks_status[task_id]["status"] = "failed"
        background_tasks_status[task_id]["progress"] = f"Error: {str(e)}"
        background_tasks_status[task_id]["error"] = str(e)
        background_tasks_status[task_id]["failed_at"] = datetime.now().isoformat()


def _run_repository_enrichment(
    task_id: str,
    max_repos: Optional[int],
    force_reenrich: bool,
    batch_size: int
):
    """Ejecuta el enriquecimiento de repositorios en background."""
    try:
        background_tasks_status[task_id]["progress"] = "Creando motor de enriquecimiento..."
        
        repos_repo = MongoRepository("repositories")
        
        engine = EnrichmentEngine(
            github_token=config.GITHUB_TOKEN,
            repos_repository=repos_repo,
            batch_size=batch_size
        )
        
        background_tasks_status[task_id]["progress"] = "Ejecutando enriquecimiento de repositorios..."
        
        stats = engine.enrich_all_repositories(
            max_repos=max_repos,
            force_reenrich=force_reenrich
        )
        
        background_tasks_status[task_id]["status"] = "completed"
        background_tasks_status[task_id]["progress"] = "Enriquecimiento completado"
        background_tasks_status[task_id]["stats"] = stats
        background_tasks_status[task_id]["completed_at"] = datetime.now().isoformat()
        
        logger.info(f"✅ Tarea {task_id} completada exitosamente")
        
    except Exception as e:
        logger.error(f"❌ Error en tarea {task_id}: {e}")
        background_tasks_status[task_id]["status"] = "failed"
        background_tasks_status[task_id]["progress"] = f"Error: {str(e)}"
        background_tasks_status[task_id]["error"] = str(e)
        background_tasks_status[task_id]["failed_at"] = datetime.now().isoformat()


def _run_user_enrichment(
    task_id: str,
    max_users: Optional[int],
    force_reenrich: bool,
    batch_size: int
):
    """Ejecuta el enriquecimiento de usuarios en background."""
    try:
        background_tasks_status[task_id]["progress"] = "Creando motor de enriquecimiento de usuarios..."
        
        users_repo = MongoRepository("users")
        repos_repo = MongoRepository("repositories")
        
        engine = UserEnrichmentEngine(
            github_token=config.GITHUB_TOKEN,
            users_repository=users_repo,
            repos_repository=repos_repo,
            batch_size=batch_size
        )
        
        background_tasks_status[task_id]["progress"] = "Ejecutando enriquecimiento de usuarios..."
        
        stats = engine.enrich_all_users(
            max_users=max_users,
            force_reenrich=force_reenrich
        )
        
        background_tasks_status[task_id]["status"] = "completed"
        background_tasks_status[task_id]["progress"] = "Enriquecimiento de usuarios completado"
        background_tasks_status[task_id]["stats"] = stats
        background_tasks_status[task_id]["completed_at"] = datetime.now().isoformat()
        
        logger.info(f"✅ Tarea {task_id} completada exitosamente")
        
    except Exception as e:
        logger.error(f"❌ Error en tarea {task_id}: {e}")
        background_tasks_status[task_id]["status"] = "failed"
        background_tasks_status[task_id]["progress"] = f"Error: {str(e)}"
        background_tasks_status[task_id]["error"] = str(e)
        background_tasks_status[task_id]["failed_at"] = datetime.now().isoformat()


def _run_organization_ingestion(
    task_id: str,
    force_update: bool,
    batch_size: int
):
    """Ejecuta la ingesta de organizaciones en background."""
    try:
        background_tasks_status[task_id]["progress"] = "Creando motor de ingesta de organizaciones..."
        
        users_repo = MongoRepository("users")
        orgs_repo = MongoRepository("organizations", unique_fields=["id"])
        
        engine = OrganizationIngestionEngine(
            github_token=config.GITHUB_TOKEN,
            users_repository=users_repo,
            organizations_repository=orgs_repo,
            batch_size=batch_size
        )
        
        background_tasks_status[task_id]["progress"] = "Ejecutando ingesta de organizaciones..."
        
        stats = engine.run(force_update=force_update)
        
        background_tasks_status[task_id]["status"] = "completed"
        background_tasks_status[task_id]["progress"] = "Ingesta de organizaciones completada"
        background_tasks_status[task_id]["stats"] = stats
        background_tasks_status[task_id]["completed_at"] = datetime.now().isoformat()
        
        logger.info(f"✅ Tarea {task_id} completada exitosamente")
        
    except Exception as e:
        logger.error(f"❌ Error en tarea {task_id}: {e}")
        background_tasks_status[task_id]["status"] = "failed"
        background_tasks_status[task_id]["progress"] = f"Error: {str(e)}"
        background_tasks_status[task_id]["error"] = str(e)
        background_tasks_status[task_id]["failed_at"] = datetime.now().isoformat()


def _run_organization_enrichment(
    task_id: str,
    max_orgs: Optional[int],
    force_reenrich: bool,
    batch_size: int
):
    """Ejecuta el enriquecimiento de organizaciones en background."""
    try:
        background_tasks_status[task_id]["progress"] = "Creando motor de enriquecimiento de organizaciones..."
        
        orgs_repo = MongoRepository("organizations")
        repos_repo = MongoRepository("repositories")
        users_repo = MongoRepository("users")
        
        engine = OrganizationEnrichmentEngine(
            github_token=config.GITHUB_TOKEN,
            organizations_repository=orgs_repo,
            repositories_repository=repos_repo,
            users_repository=users_repo,
            batch_size=batch_size
        )
        
        background_tasks_status[task_id]["progress"] = "Ejecutando enriquecimiento de organizaciones..."
        
        stats = engine.enrich_all_organizations(
            max_orgs=max_orgs,
            force_reenrich=force_reenrich
        )
        
        background_tasks_status[task_id]["status"] = "completed"
        background_tasks_status[task_id]["progress"] = "Enriquecimiento de organizaciones completado"
        background_tasks_status[task_id]["stats"] = stats
        background_tasks_status[task_id]["completed_at"] = datetime.now().isoformat()
        
        logger.info(f"✅ Tarea {task_id} completada exitosamente")
        
    except Exception as e:
        logger.error(f"❌ Error en tarea {task_id}: {e}")
        background_tasks_status[task_id]["status"] = "failed"
        background_tasks_status[task_id]["progress"] = f"Error: {str(e)}"
        background_tasks_status[task_id]["error"] = str(e)
        background_tasks_status[task_id]["failed_at"] = datetime.now().isoformat()




@router.post("/pipeline/run-all")
async def run_full_pipeline(background_tasks: BackgroundTasks):
    """
    Ejecuta el pipeline completo de ingesta y enriquecimiento. Este es el que debes ejecutar si quieres una ingesta completa desde 0
    
    Ejecuta directamente todas las operaciones en orden (con logs visibles en Azure):
    1. Ingesta de Repositorios
    2. Enriquecimiento de Repositorios
    3. Ingesta de Usuarios
    4. Enriquecimiento de Usuarios
    5. Ingesta de Organizaciones
    6. Enriquecimiento de Organizaciones
    
    Retorna un task_id para consultar el progreso.
    """
    import uuid
    
    task_id = f"full-pipeline-{uuid.uuid4()}"
    
    background_tasks_status[task_id] = {
        "task_id": task_id,
        "task_type": "full_pipeline",
        "status": "running",
        "progress": "Iniciando pipeline completo...",
        "started_at": datetime.now().isoformat()
    }
    
    background_tasks.add_task(_run_full_pipeline_direct, task_id)
    
    return {
        "task_id": task_id,
        "status": "started",
        "message": "Pipeline completo iniciado. Usa GET /pipeline/status/{task_id} para ver el estado."
    }


def _run_full_pipeline_direct(task_id: str):
    """Ejecuta el pipeline completo llamando directamente a las funciones (logs visibles en Azure)."""
    from dataclasses import dataclass
    from typing import List
    import traceback
    from ..core.db import get_database
    from ..github.user_ingestion import run_user_ingestion
    
    @dataclass
    class OperationResult:
        """Resultado de una operación del pipeline."""
        name: str
        success: bool
        duration: float
        records_processed: int = 0
        error_message: str = ""
    
    def run_operation(name: str, func, *args, **kwargs) -> OperationResult:
        """Ejecuta una operación y registra su resultado."""
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"EJECUTANDO: {name}")
        logger.info("=" * 80)
        
        start_time = datetime.now()
        success = False
        records_processed = 0
        error_message = ""
        
        try:
            result = func(*args, **kwargs)
            success = True
            
            # Extraer el número de registros procesados según el tipo de resultado
            if isinstance(result, dict):
                records_processed = (
                    result.get('total', 0) or 
                    result.get('total_processed', 0) or
                    result.get('stats', {}).get('total_found', 0) or
                    result.get('total_organizations', 0) or
                    result.get('total_users', 0) or
                    result.get('enriched', 0) or
                    result.get('new_organizations', 0) or
                    result.get('new_users', 0) or
                    result.get('users_inserted', 0) or
                    0
                )
            elif isinstance(result, int):
                records_processed = result
                
            logger.info(f"✅ {name} completado exitosamente")
            if records_processed > 0:
                logger.info(f"   Registros procesados: {records_processed:,}")
            
        except Exception as e:
            success = False
            error_message = str(e)
            logger.error(f"❌ Error en {name}: {error_message}")
            logger.error(traceback.format_exc())
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        return OperationResult(
            name=name,
            success=success,
            duration=duration,
            records_processed=records_processed,
            error_message=error_message
        )
    
    try:
        total_start = datetime.now()
        results: List[OperationResult] = []
        
        logger.info("🚀 INICIANDO PIPELINE COMPLETO DE INGESTA Y ENRIQUECIMIENTO")
        logger.info("=" * 80)
        
        # Obtener dependencias comunes
        import os
        github_token = os.getenv("GITHUB_TOKEN")
        
        if not github_token:
            raise ValueError("GITHUB_TOKEN no configurado en variables de entorno")
        
        # 1. Ingesta de Repositorios
        background_tasks_status[task_id]["progress"] = "1/6 - Ingesta de Repositorios"
        result = run_operation(
            "1. Ingesta de Repositorios",
            lambda: IngestionEngine(incremental=False).run(max_results=None, save_to_json=False)
        )
        results.append(result)
        
        # 2. Enriquecimiento de Repositorios  
        background_tasks_status[task_id]["progress"] = "2/6 - Enriquecimiento de Repositorios"
        repo_repo = MongoRepository("repositories")
        
        result = run_operation(
            "2. Enriquecimiento de Repositorios",
            lambda: EnrichmentEngine(
                github_token=github_token,
                repos_repository=repo_repo,
                batch_size=100  # ✅ OPTIMIZADO para vCore M30
            ).enrich_all_repositories(max_repos=None)
        )
        results.append(result)
        
        # 3. Ingesta de Usuarios
        background_tasks_status[task_id]["progress"] = "3/6 - Ingesta de Usuarios"
        result = run_operation(
            "3. Ingesta de Usuarios",
            run_user_ingestion
        )
        results.append(result)
        
        # 4. Enriquecimiento de Usuarios
        background_tasks_status[task_id]["progress"] = "4/6 - Enriquecimiento de Usuarios"
        users_repo = MongoRepository("users")
        
        result = run_operation(
            "4. Enriquecimiento de Usuarios",
            lambda: UserEnrichmentEngine(
                github_token=github_token,
                users_repository=users_repo,
                repos_repository=repo_repo,
                batch_size=100  # ✅ OPTIMIZADO para vCore M30
            ).enrich_all_users(
                max_users=None, 
                force_reenrich=False
            )
        )
        results.append(result)
        
        # 5. Ingesta de Organizaciones
        background_tasks_status[task_id]["progress"] = "5/6 - Ingesta de Organizaciones"
        orgs_repo = MongoRepository("organizations")
        
        result = run_operation(
            "5. Ingesta de Organizaciones",
            lambda: OrganizationIngestionEngine(
                github_token=github_token,
                users_repository=users_repo,
                organizations_repository=orgs_repo,
                batch_size=100  # ✅ OPTIMIZADO para vCore M30
            ).run(force_update=False)
        )
        results.append(result)
        
        # 6. Enriquecimiento de Organizaciones
        background_tasks_status[task_id]["progress"] = "6/6 - Enriquecimiento de Organizaciones"
        result = run_operation(
            "6. Enriquecimiento de Organizaciones",
            lambda: OrganizationEnrichmentEngine(
                github_token=github_token,
                organizations_repository=orgs_repo,
                repositories_repository=repo_repo,
                users_repository=users_repo,
                batch_size=100  # ✅ OPTIMIZADO para vCore M30
            ).enrich_all_organizations(max_orgs=None, force_reenrich=False)
        )
        results.append(result)
        
        total_end = datetime.now()
        total_duration = (total_end - total_start).total_seconds()
        
        # Resumen
        logger.info("")
        logger.info("=" * 80)
        logger.info("📊 RESUMEN COMPLETO DE EJECUCIÓN")
        logger.info("=" * 80)
        
        successful = sum(1 for r in results if r.success)
        total_records = sum(r.records_processed for r in results if r.success)
        
        for result in results:
            status = "✅ ÉXITO" if result.success else "❌ ERROR"
            logger.info(f"{result.name}: {status} ({result.records_processed:,} registros, {result.duration:.0f}s)")
            if not result.success:
                logger.error(f"   Error: {result.error_message}")
        
        logger.info("")
        logger.info(f"Total: {successful}/{len(results)} operaciones exitosas")
        logger.info(f"Registros procesados: {total_records:,}")
        logger.info(f"Duración total: {total_duration:.0f}s ({total_duration/60:.1f}m)")
        
        # Actualizar estado final
        if successful == len(results):
            background_tasks_status[task_id]["status"] = "completed"
            background_tasks_status[task_id]["progress"] = "Pipeline completado exitosamente"
            logger.info("🎉 PIPELINE COMPLETADO EXITOSAMENTE 🎉")
        else:
            background_tasks_status[task_id]["status"] = "completed_with_errors"
            background_tasks_status[task_id]["progress"] = f"Completado con {len(results) - successful} errores"
            logger.warning("⚠️  PIPELINE COMPLETADO CON ERRORES ⚠️")
        
        background_tasks_status[task_id]["completed_at"] = datetime.now().isoformat()
        background_tasks_status[task_id]["total_operations"] = len(results)
        background_tasks_status[task_id]["successful_operations"] = successful
        background_tasks_status[task_id]["total_records"] = total_records
        background_tasks_status[task_id]["duration_seconds"] = total_duration
        
    except Exception as e:
        logger.error(f"❌ Error crítico en pipeline {task_id}: {e}")
        logger.error(traceback.format_exc())
        background_tasks_status[task_id]["status"] = "failed"
        background_tasks_status[task_id]["progress"] = f"Error crítico: {str(e)}"
        background_tasks_status[task_id]["error"] = str(e)
        background_tasks_status[task_id]["failed_at"] = datetime.now().isoformat()


def _run_full_pipeline_script(task_id: str):
    """
    DEPRECADO: Ejecuta el script run_full_pipeline.py usando subprocess.
    No se usa porque capture_output=True oculta los logs en Azure.
    Mantenido solo por compatibilidad legacy.
    """
    import subprocess
    import sys
    import os
    
    try:
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "scripts",
            "run_full_pipeline.py"
        )
        
        background_tasks_status[task_id]["progress"] = "Ejecutando pipeline completo..."
        
        logger.info(f"Ejecutando script: {script_path}")
        
        # Ejecutar el script
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        )
        
        if result.returncode == 0:
            background_tasks_status[task_id]["status"] = "completed"
            background_tasks_status[task_id]["progress"] = "Pipeline completado exitosamente"
            background_tasks_status[task_id]["output"] = result.stdout
        else:
            background_tasks_status[task_id]["status"] = "failed"
            background_tasks_status[task_id]["progress"] = f"Pipeline fallo con codigo {result.returncode}"
            background_tasks_status[task_id]["error"] = result.stderr
            background_tasks_status[task_id]["output"] = result.stdout
        
        background_tasks_status[task_id]["completed_at"] = datetime.now().isoformat()
        background_tasks_status[task_id]["exit_code"] = result.returncode
        
        logger.info(f"Pipeline completado - Task ID: {task_id}, Exit Code: {result.returncode}")
        
    except Exception as e:
        logger.error(f"Error ejecutando pipeline {task_id}: {e}")
        background_tasks_status[task_id]["status"] = "failed"
        background_tasks_status[task_id]["progress"] = f"Error: {str(e)}"
        background_tasks_status[task_id]["error"] = str(e)
        background_tasks_status[task_id]["failed_at"] = datetime.now().isoformat()
