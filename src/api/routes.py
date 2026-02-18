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
from ..analysis.network_metrics import CollaborationNetworkAnalyzer

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
    
    Caché PERMANENTE en colección 'metrics'. Se invalida vía refresh-metrics
    o al completarse ingestas/enriquecimientos.
    
    NOTA: Para dashboard completo con caché, usar /dashboard/stats
    """
    try:
        from ..core.db import db
        
        # Asegurar conexión activa (reconecta automáticamente si está caída)
        db.ensure_connection()
        
        metrics_collection = db.get_collection("metrics")
        
        # 1. Intentar servir desde caché permanente
        cached = metrics_collection.find_one({"type": "simple_counts"})
        if cached and "data" in cached:
            logger.info("📊 /stats servido desde caché permanente")
            return cached["data"]
        
        # 2. Calcular y guardar en caché
        repos_collection = db.get_collection("repositories")
        users_collection = db.get_collection("users")
        orgs_collection = db.get_collection("organizations")
        
        # Contar documentos con timeout de 5 segundos
        repos_count = repos_collection.count_documents({}, maxTimeMS=5000)
        users_count = users_collection.count_documents({}, maxTimeMS=5000)
        orgs_count = orgs_collection.count_documents({}, maxTimeMS=5000)
        
        result = {
            "repositories": repos_count,
            "users": users_count,
            "organizations": orgs_count,
            "timestamp": datetime.now().isoformat()
        }
        
        # Guardar en caché permanente
        metrics_collection.update_one(
            {"type": "simple_counts"},
            {"$set": {"type": "simple_counts", "data": result, "updated_at": datetime.now()}},
            upsert=True
        )
        logger.info(f"📊 /stats calculado y cacheado: {repos_count} repos, {users_count} users, {orgs_count} orgs")
        
        return result
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
        
        current_time = datetime.now()
        
        # Detectar si hay filtros activos
        # include_bots=False es el default, solo cuenta como filtro si es True
        has_filters = bool(org or language or repo or collab_type or include_bots)
        
        # 1. INTENTAR OBTENER CACHÉ (solo si no hay filtros y no se fuerza refresh)
        # Caché PERMANENTE: sin TTL, persiste hasta invalidación explícita
        metrics_collection = db.get_collection("metrics")
        
        if not force_refresh and not has_filters:
            cached_stats = metrics_collection.find_one({"type": "dashboard_stats"})
            
            if cached_stats:
                updated_at = cached_stats.get("updated_at", current_time)
                logger.info(f"📊 Cache HIT - Dashboard stats servido desde caché permanente")
                
                response_data = cached_stats.get("data", {})
                response_data["metadata"] = {
                    "cached": True,
                    "calculatedAt": updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at),
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
            
            logger.info("✅ Dashboard stats COMPLETO calculado y guardado en caché permanente")
        else:
            logger.info(f"✅ Dashboard stats CON FILTROS calculado (no cacheado)")
        
        return response_data
        
    except Exception as e:
        error_msg = f"Error al obtener dashboard stats: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


def invalidate_all_caches():
    """
    Invalida TODAS las cachés de la aplicación (MongoDB + memoria).
    
    Se llama desde:
    - POST /dashboard/refresh-metrics (botón de actualizar)
    - Al completarse cualquier tarea de ingesta o enriquecimiento
    
    Cachés invalidadas:
    - collaboration_graph (chunked en metrics)
    - network_metrics (chunked en metrics + in-memory)
    - dashboard_stats (doc en metrics)
    - simple_counts (doc en metrics)
    - collab_analysis_* (docs de análisis por usuario/repos/orgs en metrics)
    """
    from ..core.db import db
    from ..core.chunked_cache import delete_chunked
    
    db.ensure_connection()
    metrics = db.get_collection("metrics")
    
    # Cachés chunked (documentos grandes >2MB)
    graph_deleted = delete_chunked(metrics, "collaboration_graph")
    nm_deleted = delete_chunked(metrics, "network_metrics")
    
    # Caché en memoria de network metrics
    _network_metrics_cache["json_bytes"] = None
    _network_metrics_cache["computed_at"] = None
    _network_metrics_cache["analyzer"] = None
    
    # Cachés de documento simple
    stats_deleted = metrics.delete_one({"type": "dashboard_stats"}).deleted_count
    counts_deleted = metrics.delete_one({"type": "simple_counts"}).deleted_count
    
    # Cachés de análisis de colaboración (por usuario/repos/orgs)
    analyze_deleted = metrics.delete_many(
        {"_id": {"$regex": "^collab_analysis_"}}
    ).deleted_count
    
    summary = {
        "collaboration_graph_chunks": graph_deleted,
        "network_metrics_chunks": nm_deleted,
        "dashboard_stats": stats_deleted,
        "simple_counts": counts_deleted,
        "collaboration_analyses": analyze_deleted,
    }
    
    logger.info(f"[INVALIDATE_ALL] Todas las cachés invalidadas: {summary}")
    return summary


@router.post("/dashboard/refresh-metrics")
async def refresh_dashboard_metrics():
    """
    Invalida TODAS las cachés de la aplicación.
    El frontend se encarga de recargar datos frescos con force_refresh
    después de llamar a este endpoint.
    
    Útil después de ingestas/enriquecimientos o al pulsar el botón de actualizar.
    """
    try:
        result = invalidate_all_caches()
        return {"invalidated": True, "details": result}
    except Exception as e:
        logger.error(f"Error al invalidar cachés: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# COLLABORATION DISCOVERY - Auto-detección de colaboración real
# ============================================================================

@router.get("/collaboration/discover")
async def discover_collaboration(force: bool = False):
    """
    Auto-descubre patrones de colaboración analizando TODA la base de datos.
    Usa caché en MongoDB (colección 'metrics', doc 'collaboration_graph')
    para servir resultados instantáneamente. Pasar ?force=true recalcula.
    
    Busca automáticamente:
    1. Bridge Users: Usuarios que contribuyen a 2+ repositorios
    2. Repos conectados: Repositorios que comparten colaboradores
    3. Colaboración cross-org: Usuarios que participan en múltiples organizaciones
    
    Returns:
        - available: bool - Si hay colaboración detectable
        - summary: Resumen textual de lo descubierto
        - graph: Grafo completo con nodos y enlaces reales
        - metrics: Estadísticas de colaboración
        - bridge_users: Top usuarios puente
        - connected_pairs: Pares de repos/orgs más conectados
    """
    try:
        import orjson
        from fastapi.responses import Response
        from ..core.db import db
        from ..core.chunked_cache import load_chunked, save_chunked
        
        db.ensure_connection()
        
        # ── CACHÉ: intentar servir desde metrics (chunked para >2MB) ──
        if not force:
            metrics_collection = db.get_collection("metrics")
            cached = load_chunked(metrics_collection, "collaboration_graph")
            if cached:
                logger.info(f"[DISCOVER] Sirviendo grafo desde caché chunked ({cached.get('metrics', {}).get('graph_nodes', '?')} nodos)")
                return Response(content=orjson.dumps(cached), media_type="application/json")
        
        repos_collection = db.get_collection("repositories")
        users_collection = db.get_collection("users")
        orgs_collection = db.get_collection("organizations")
        
        # ============================================================
        # PASO 1: Mapear todos los repos y sus colaboradores
        # ============================================================
        
        # Helper para detectar bots por login
        def _is_bot_login(login: str) -> bool:
            if not login:
                return False
            ll = login.lower()
            return (
                "[bot]" in ll or
                ll.endswith("-bot") or
                ll.startswith("bot-") or
                ll in ["dependabot", "renovate", "greenkeeper", "snyk-bot", "codecov", "sonarcloud"]
            )
        
        all_repos = list(repos_collection.find(
            {"collaborators": {"$exists": True, "$ne": []}},
            {"_id": 0, "name": 1, "full_name": 1, "owner": 1, "stargazer_count": 1,
             "primary_language": 1, "collaborators": 1, "organization": 1}
        ))
        
        # Mapa: user_login → [repos donde contribuye]
        user_to_repos = {}
        # Mapa: repo_full_name → set(user_logins)
        repo_to_users = {}
        
        for repo in all_repos:
            full_name = repo.get("full_name")
            if not full_name:
                continue
            
            collabs = set()
            for c in repo.get("collaborators", []):
                login = c.get("login")
                if login:
                    collabs.add(login)
                    if login not in user_to_repos:
                        user_to_repos[login] = []
                    user_to_repos[login].append({
                        "full_name": full_name,
                        "name": repo.get("name"),
                        "stars": repo.get("stargazer_count", 0),
                        "owner": repo.get("owner", {}).get("login", ""),
                        "language": repo.get("primary_language", {}).get("name") if isinstance(repo.get("primary_language"), dict) else repo.get("primary_language")
                    })
            
            repo_to_users[full_name] = collabs
        
        # ============================================================
        # PASO 2: Identificar Bridge Users (usuarios en 2+ repos)
        # ============================================================
        bridge_users = {}
        for login, repos_list in user_to_repos.items():
            if len(repos_list) >= 2:
                bridge_users[login] = repos_list
        
        # ============================================================
        # PASO 3: Encontrar pares de repos conectados (via índice invertido)
        # ============================================================
        # En vez de O(N²) comparando todos los pares de repos,
        # iteramos los bridge users y generamos pares desde sus repos
        pair_shared = {}  # (repo_a, repo_b) → set(shared_users)
        for login, repos_list in bridge_users.items():
            repo_fns = [r["full_name"] for r in repos_list]
            for i in range(len(repo_fns)):
                for j in range(i + 1, len(repo_fns)):
                    a, b = min(repo_fns[i], repo_fns[j]), max(repo_fns[i], repo_fns[j])
                    key = (a, b)
                    if key not in pair_shared:
                        pair_shared[key] = set()
                    pair_shared[key].add(login)
        
        connected_repo_pairs = [
            {"repo_a": k[0], "repo_b": k[1], "shared_users": list(v), "shared_count": len(v)}
            for k, v in pair_shared.items()
        ]
        connected_repo_pairs.sort(key=lambda x: x["shared_count"], reverse=True)
        
        # ============================================================
        # PASO 4: Colaboración cross-org
        # ============================================================
        # Mapear usuarios a sus organizaciones
        user_to_orgs = {}
        all_org_logins = set()
        
        # Desde la colección de users
        all_users_cursor = users_collection.find(
            {"organizations": {"$exists": True, "$ne": []}},
            {"_id": 0, "login": 1, "organizations": 1}
        )
        
        for user_doc in all_users_cursor:
            login = user_doc.get("login")
            if not login:
                continue
            user_orgs = []
            for org in (user_doc.get("organizations") or []):
                org_login = org.get("login") if isinstance(org, dict) else org
                if org_login:
                    user_orgs.append(org_login)
                    all_org_logins.add(org_login)
            if len(user_orgs) >= 2:
                user_to_orgs[login] = user_orgs
        
        # También desde repos: usuario contribuye a repos de distintas orgs
        user_repo_orgs = {}
        for login in bridge_users:
            repo_orgs = set()
            for r in bridge_users[login]:
                owner = r.get("owner")
                if owner:
                    repo_orgs.add(owner)
            if len(repo_orgs) >= 2:
                user_repo_orgs[login] = list(repo_orgs)
        
        # Combinar cross-org users
        cross_org_users = set(user_to_orgs.keys()) | set(user_repo_orgs.keys())
        
        # ============================================================
        # PASO 5: Determinar si hay colaboración disponible
        # ============================================================
        has_collaboration = len(bridge_users) > 0 or len(connected_repo_pairs) > 0
        
        if not has_collaboration:
            return {
                "available": False,
                "summary": "No se detectaron patrones de colaboración entre los datos actuales.",
                "graph": {"nodes": [], "links": []},
                "metrics": {
                    "total_repos": len(all_repos),
                    "total_users": len(user_to_repos),
                    "bridge_users": 0,
                    "connected_repo_pairs": 0,
                    "cross_org_users": 0
                },
                "bridge_users": [],
                "connected_pairs": []
            }
        
        # ============================================================
        # PASO 6: Construir grafo de colaboración
        # ============================================================
        nodes = []
        links = []
        added_nodes = set()
        
        # 6a) Filtrar bots ANTES de rankear bridge users
        human_bridge_users = {
            login: repos_list for login, repos_list in bridge_users.items()
            if not _is_bot_login(login)
        }
        bot_bridge_users = {
            login: repos_list for login, repos_list in bridge_users.items()
            if _is_bot_login(login)
        }
        
        # 6b) Ordenar bridge users humanos por número de repos (más conectados primero)
        sorted_bridge = sorted(human_bridge_users.items(), key=lambda x: len(x[1]), reverse=True)
        
        # Tomar TODOS los bridge users humanos (sin límite artificial)
        top_bridge_users = sorted_bridge
        
        # 6c) Recopilar repos conectados por bridge users
        connected_repos = set()
        for login, repos_list in top_bridge_users:
            for r in repos_list:
                connected_repos.add(r["full_name"])
        
        # 6d) Añadir nodos de repos
        for repo in all_repos:
            full_name = repo.get("full_name")
            if full_name in connected_repos:
                node_id = f"repo_{full_name}"
                if node_id not in added_nodes:
                    org_login = repo.get("owner", {}).get("login", "")
                    nodes.append({
                        "id": node_id,
                        "type": "repo",
                        "name": repo.get("name"),
                        "full_name": full_name,
                        "stars": repo.get("stargazer_count", 0),
                        "language": repo.get("primary_language", {}).get("name") if isinstance(repo.get("primary_language"), dict) else repo.get("primary_language"),
                        "org": org_login
                    })
                    added_nodes.add(node_id)
        
        # 6e) Bulk fetch de datos de usuarios bridge
        all_user_logins_needed = set()
        for login, _ in top_bridge_users:
            all_user_logins_needed.add(login)
        
        user_info_cache = {}
        if all_user_logins_needed:
            cursor = users_collection.find(
                {"login": {"$in": list(all_user_logins_needed)}},
                {"_id": 0, "login": 1, "name": 1, "avatar_url": 1, "quantum_expertise_score": 1, "is_bot": 1}
            )
            for doc in cursor:
                user_info_cache[doc["login"]] = doc
        
        def _make_user_node(login, repos_list, is_bridge):
            user_info = user_info_cache.get(login)
            user_is_bot = False
            if user_info and "is_bot" in user_info:
                user_is_bot = bool(user_info["is_bot"])
            else:
                user_is_bot = _is_bot_login(login)
            return {
                "id": f"user_{login}",
                "type": "user",
                "login": login,
                "name": (user_info.get("name") if user_info else None) or login,
                "avatar_url": user_info.get("avatar_url") if user_info else None,
                "repos_count": len(repos_list) if repos_list else 1,
                "isBridge": is_bridge,
                "isBot": user_is_bot,
                "quantum_expertise_score": user_info.get("quantum_expertise_score", 0) if user_info else 0
            }
        
        # 6f) Añadir nodos de bridge users + links a sus repos
        enriched_bridge_list = []
        for login, repos_list in top_bridge_users:
            user_id = f"user_{login}"
            user_node = _make_user_node(login, repos_list, True)
            
            if user_id not in added_nodes:
                nodes.append(user_node)
                added_nodes.add(user_id)
            
            # Links usuario → repos
            for r in repos_list:
                repo_node_id = f"repo_{r['full_name']}"
                if repo_node_id in added_nodes:
                    links.append({
                        "source": user_id,
                        "target": repo_node_id,
                        "type": "contributed_to"
                    })
            
            enriched_bridge_list.append({
                "login": login,
                "name": user_node["name"],
                "avatar_url": user_node.get("avatar_url"),
                "quantum_expertise_score": user_node.get("quantum_expertise_score", 0),
                "repos": [r["full_name"] for r in repos_list],
                "repos_count": len(repos_list),
                "cross_org": login in cross_org_users
            })
        
        # 6g) Añadir nodos de usuarios normales (no bridge) vinculados a repos en el grafo
        normal_user_count = 0
        for login, repos_list in user_to_repos.items():
            if login in bridge_users or _is_bot_login(login):
                continue
            user_id = f"user_{login}"
            if user_id in added_nodes:
                continue
            # Solo añadir si al menos uno de sus repos ya está en el grafo
            linked_repo_id = None
            for r in repos_list:
                repo_node_id = f"repo_{r['full_name']}"
                if repo_node_id in added_nodes:
                    linked_repo_id = repo_node_id
                    break
            if linked_repo_id:
                user_node = _make_user_node(login, repos_list, False)
                nodes.append(user_node)
                added_nodes.add(user_id)
                links.append({
                    "source": user_id,
                    "target": linked_repo_id,
                    "type": "contributed_to"
                })
                normal_user_count += 1
        
        logger.info(f"[DISCOVER] Usuarios normales añadidos: {normal_user_count}")
        
        # 6h) Añadir nodos de organizaciones (las que contienen repos conectados)
        org_logins_in_graph = set()
        for repo in all_repos:
            full_name = repo.get("full_name")
            if full_name in connected_repos:
                org_login = repo.get("owner", {}).get("login", "")
                if org_login and org_login not in org_logins_in_graph:
                    org_logins_in_graph.add(org_login)
        
        for org_login in org_logins_in_graph:
            org_id = f"org_{org_login}"
            if org_id not in added_nodes:
                org_doc = orgs_collection.find_one(
                    {"login": org_login},
                    {"_id": 0, "name": 1, "avatar_url": 1}
                )
                nodes.append({
                    "id": org_id,
                    "type": "org",
                    "login": org_login,
                    "name": (org_doc.get("name") if org_doc else None) or org_login,
                    "avatar_url": org_doc.get("avatar_url") if org_doc else None,
                })
                added_nodes.add(org_id)
                
                # Links org → sus repos
                for repo in all_repos:
                    if repo.get("owner", {}).get("login") == org_login:
                        repo_id = f"repo_{repo.get('full_name')}"
                        if repo_id in added_nodes:
                            links.append({
                                "source": org_id,
                                "target": repo_id,
                                "type": "owns"
                            })
        
        # ============================================================
        # PASO 7: Links de entrelazamiento org↔org (bridge users compartidos)
        # ============================================================
        # Para cada par de orgs, contar cuántos bridge users contribuyen a repos de ambas
        org_pair_bridges = {}  # (org_a, org_b) → set(logins)
        for login, repos_list in human_bridge_users.items():
            user_org_set = set()
            for r in repos_list:
                owner = r.get("owner")
                if owner and f"org_{owner}" in added_nodes:
                    user_org_set.add(owner)
            if len(user_org_set) >= 2:
                org_list = sorted(user_org_set)
                for i in range(len(org_list)):
                    for j in range(i + 1, len(org_list)):
                        key = (org_list[i], org_list[j])
                        if key not in org_pair_bridges:
                            org_pair_bridges[key] = set()
                        org_pair_bridges[key].add(login)
        
        # Solo emitir links con ≥ 3 bridge users compartidos para evitar ruido
        entanglement_count = 0
        for (org_a, org_b), shared_logins in org_pair_bridges.items():
            strength = len(shared_logins)
            if strength >= 3:
                links.append({
                    "source": f"org_{org_a}",
                    "target": f"org_{org_b}",
                    "type": "entangled_with",
                    "strength": strength
                })
                entanglement_count += 1
        
        logger.info(f"[DISCOVER] Entrelazamientos org↔org: {entanglement_count} (threshold ≥3 bridge users)")
        
        # ============================================================
        # PASO 8: Construir resumen textual
        # ============================================================
        summary_parts = []
        if len(bridge_users) > 0:
            summary_parts.append(f"{len(bridge_users)} usuarios puente entre {len(connected_repos)} repositorios")
        if len(connected_repo_pairs) > 0:
            summary_parts.append(f"{len(connected_repo_pairs)} pares de repos conectados")
        if len(cross_org_users) > 0:
            summary_parts.append(f"{len(cross_org_users)} usuarios cross-org")
        
        summary = " · ".join(summary_parts)
        
        # Density: ratio of actual links to possible links
        max_possible_links = len(nodes) * (len(nodes) - 1) / 2 if len(nodes) > 1 else 1
        density = round(len(links) / max(max_possible_links, 1) * 100, 2)
        
        # Contar nodos por tipo para métricas
        user_nodes_in_graph = [n for n in nodes if n["type"] == "user"]
        bridge_nodes_in_graph = [n for n in user_nodes_in_graph if n.get("isBridge")]
        
        result = {
            "available": True,
            "summary": summary,
            "graph": {"nodes": nodes, "links": links},
            "metrics": {
                "total_repos_analyzed": len(all_repos),
                "total_users_mapped": len(user_to_repos),
                "bridge_users_count": len(bridge_nodes_in_graph),
                "normal_users_count": normal_user_count,
                "total_bridge_users_found": len(human_bridge_users),
                "connected_repo_pairs": len(connected_repo_pairs),
                "cross_org_users": len(cross_org_users),
                "graph_nodes": len(nodes),
                "graph_links": len(links),
                "collaboration_density": density
            },
            "bridge_users": enriched_bridge_list,
            "connected_pairs": connected_repo_pairs[:20]
        }
        
        # ── GUARDAR EN CACHÉ MongoDB (chunked para >2MB) ──
        try:
            metrics_collection = db.get_collection("metrics")
            save_chunked(
                metrics_collection,
                "collaboration_graph",
                result,
                large_fields=["graph.nodes", "graph.links", "bridge_users"]
            )
            logger.info(f"[DISCOVER] Grafo guardado en caché chunked ({len(nodes)} nodos, {len(links)} links)")
        except Exception as cache_err:
            logger.warning(f"[DISCOVER] No se pudo cachear el grafo: {cache_err}")
        
        return Response(content=orjson.dumps(result), media_type="application/json")
        
    except Exception as e:
        error_msg = f"Error en descubrimiento de colaboración: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/collaboration/discover/invalidate")
async def invalidate_collaboration_cache():
    """Invalida la caché del grafo de colaboración. Útil tras una ingesta de datos."""
    try:
        from ..core.db import db
        from ..core.chunked_cache import delete_chunked
        db.ensure_connection()
        metrics_collection = db.get_collection("metrics")
        deleted_count = delete_chunked(metrics_collection, "collaboration_graph")
        deleted = deleted_count > 0
        logger.info(f"[DISCOVER] Caché invalidada: {'eliminada' if deleted else 'no existía'} ({deleted_count} docs)")
        return {"invalidated": deleted, "message": f"Caché del grafo eliminada ({deleted_count} docs)" if deleted else "No había caché"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collaboration/analyze")
async def analyze_collaboration(
    repos: Optional[list] = Query(default=None, description="Lista de repositorios (full_name) a analizar"),
    orgs: Optional[list] = Query(default=None, description="Lista de organizaciones (login) a analizar"),
    user: Optional[str] = Query(default=None, description="Usuario específico para ver sus colaboraciones")
):
    """
    Análisis de colaboración entre repos/orgs/usuarios.
    
    Modos de operación:
    1. repos=[repo1, repo2...]: Encuentra usuarios compartidos entre repos
    2. orgs=[org1, org2...]: Encuentra usuarios compartidos entre orgs
    3. user=login: Muestra con quién ha colaborado y en qué repos/orgs
    
    Returns:
        - shared_users: Usuarios que aparecen en múltiples selecciones
        - collaboration_graph: Nodos y enlaces para visualización
        - metrics: Estadísticas de colaboración
    """
    try:
        from ..core.db import db
        
        db.ensure_connection()
        repos_collection = db.get_collection("repositories")
        users_collection = db.get_collection("users")
        orgs_collection = db.get_collection("organizations")
        metrics_collection = db.get_collection("metrics")
        
        # ── CACHÉ PERMANENTE: construir clave única según parámetros ──
        import hashlib
        if user:
            cache_key = f"collab_analysis_user_{user}"
        elif repos and len(repos) >= 2:
            sorted_repos = sorted(repos)
            cache_key = f"collab_analysis_repos_{hashlib.md5('|'.join(sorted_repos).encode()).hexdigest()}"
        elif orgs and len(orgs) >= 2:
            sorted_orgs = sorted(orgs)
            cache_key = f"collab_analysis_orgs_{hashlib.md5('|'.join(sorted_orgs).encode()).hexdigest()}"
        else:
            cache_key = None
        
        # Intentar servir desde caché permanente
        if cache_key:
            cached = metrics_collection.find_one({"_id": cache_key})
            if cached:
                cached.pop("_id", None)
                cached.pop("_cached_at", None)
                logger.info(f"[Analyze] Cache HIT: {cache_key}")
                return cached
        
        result = {
            "mode": None,
            "selections": [],
            "shared_users": [],
            "collaboration_graph": {"nodes": [], "links": []},
            "metrics": {}
        }
        
        # ============================================================
        # MODO 1: Análisis de colaboración de un USUARIO específico
        # ============================================================
        if user:
            result["mode"] = "user_focus"
            result["selections"] = [user]
            
            # Buscar el usuario
            user_doc = users_collection.find_one({"login": user})
            if not user_doc:
                raise HTTPException(status_code=404, detail=f"Usuario {user} no encontrado")
            
            # Obtener todos los repos donde este usuario es colaborador
            user_repos = list(repos_collection.find(
                {"collaborators.login": user},
                {"_id": 1, "name": 1, "full_name": 1, "owner": 1, "stargazer_count": 1, 
                 "collaborators": 1, "primary_language": 1}
            ))
            
            # Extraer co-colaboradores (personas con las que ha trabajado)
            co_collaborators = {}
            for repo in user_repos:
                for collab in repo.get("collaborators", []):
                    login = collab.get("login")
                    if login and login != user:
                        if login not in co_collaborators:
                            co_collaborators[login] = {
                                "login": login,
                                "shared_repos": [],
                                "total_shared_contributions": 0
                            }
                        co_collaborators[login]["shared_repos"].append({
                            "name": repo.get("name"),
                            "full_name": repo.get("full_name")
                        })
                        co_collaborators[login]["total_shared_contributions"] += collab.get("contributions", 0)
            
            # Ordenar por número de repos compartidos
            sorted_collaborators = sorted(
                co_collaborators.values(),
                key=lambda x: len(x["shared_repos"]),
                reverse=True
            )[:20]
            
            # Enriquecer con datos de usuario
            for collab in sorted_collaborators:
                user_info = users_collection.find_one({"login": collab["login"]})
                if user_info:
                    collab["name"] = user_info.get("name")
                    collab["avatar_url"] = user_info.get("avatar_url")
                    collab["quantum_expertise_score"] = user_info.get("quantum_expertise_score", 0)
            
            # Construir grafo
            nodes = [{
                "id": f"user_{user}",
                "type": "user",
                "login": user,
                "name": user_doc.get("name") or user,
                "avatar_url": user_doc.get("avatar_url"),
                "isCenter": True
            }]
            links = []
            
            # Añadir repos como nodos
            for repo in user_repos[:15]:
                repo_id = f"repo_{repo.get('full_name')}"
                nodes.append({
                    "id": repo_id,
                    "type": "repo",
                    "name": repo.get("name"),
                    "full_name": repo.get("full_name"),
                    "stars": repo.get("stargazer_count", 0)
                })
                links.append({
                    "source": f"user_{user}",
                    "target": repo_id,
                    "type": "contributed_to"
                })
            
            # Añadir co-colaboradores como nodos
            for collab in sorted_collaborators[:10]:
                collab_id = f"user_{collab['login']}"
                nodes.append({
                    "id": collab_id,
                    "type": "user",
                    "login": collab["login"],
                    "name": collab.get("name") or collab["login"],
                    "avatar_url": collab.get("avatar_url"),
                    "shared_count": len(collab["shared_repos"])
                })
                links.append({
                    "source": f"user_{user}",
                    "target": collab_id,
                    "type": "collaborated_with",
                    "weight": len(collab["shared_repos"])
                })
            
            # Obtener organizaciones del usuario
            user_orgs = user_doc.get("organizations", [])
            for org in user_orgs[:5]:
                org_login = org.get("login") if isinstance(org, dict) else org
                if org_login:
                    nodes.append({
                        "id": f"org_{org_login}",
                        "type": "org",
                        "login": org_login,
                        "name": org.get("name") if isinstance(org, dict) else org_login
                    })
                    links.append({
                        "source": f"user_{user}",
                        "target": f"org_{org_login}",
                        "type": "member_of"
                    })
            
            result["shared_users"] = sorted_collaborators
            result["collaboration_graph"] = {"nodes": nodes, "links": links}
            result["metrics"] = {
                "total_repos": len(user_repos),
                "total_co_collaborators": len(co_collaborators),
                "total_organizations": len(user_orgs)
            }
            
            # Guardar en caché permanente
            if cache_key:
                try:
                    metrics_collection.update_one(
                        {"_id": cache_key},
                        {"$set": {**result, "_cached_at": datetime.now().isoformat()}},
                        upsert=True
                    )
                    logger.info(f"[Analyze] Cacheado: {cache_key}")
                except Exception as ce:
                    logger.warning(f"[Analyze] Error cacheando: {ce}")
            
            return result
        
        # ============================================================
        # MODO 2: Análisis de REPOS seleccionados
        # ============================================================
        if repos and len(repos) >= 2:
            result["mode"] = "repos_comparison"
            result["selections"] = repos
            
            # Obtener colaboradores de cada repo
            repo_collaborators = {}
            all_users = set()
            
            for repo_name in repos:
                repo_doc = repos_collection.find_one(
                    {"full_name": repo_name},
                    {"_id": 1, "name": 1, "full_name": 1, "collaborators": 1, 
                     "stargazer_count": 1, "primary_language": 1, "owner": 1}
                )
                if repo_doc and repo_doc.get("collaborators"):
                    collabs = {c.get("login") for c in repo_doc.get("collaborators", []) if c.get("login")}
                    repo_collaborators[repo_name] = {
                        "doc": repo_doc,
                        "collaborators": collabs
                    }
                    all_users.update(collabs)
            
            # Encontrar usuarios compartidos (aparecen en 2+ repos)
            user_appearances = {}
            for user_login in all_users:
                repos_with_user = [
                    repo_name for repo_name, data in repo_collaborators.items()
                    if user_login in data["collaborators"]
                ]
                if len(repos_with_user) >= 2:
                    user_appearances[user_login] = repos_with_user
            
            # Enriquecer usuarios compartidos
            shared_users = []
            for login, repos_list in sorted(user_appearances.items(), key=lambda x: len(x[1]), reverse=True)[:20]:
                user_info = users_collection.find_one({"login": login})
                shared_users.append({
                    "login": login,
                    "name": user_info.get("name") if user_info else None,
                    "avatar_url": user_info.get("avatar_url") if user_info else None,
                    "quantum_expertise_score": user_info.get("quantum_expertise_score", 0) if user_info else 0,
                    "shared_repos": repos_list,
                    "shared_count": len(repos_list)
                })
            
            # Construir grafo
            nodes = []
            links = []
            
            # Añadir repos como nodos
            for repo_name, data in repo_collaborators.items():
                nodes.append({
                    "id": f"repo_{repo_name}",
                    "type": "repo",
                    "name": data["doc"].get("name"),
                    "full_name": repo_name,
                    "stars": data["doc"].get("stargazer_count", 0)
                })
            
            # Añadir usuarios compartidos
            for user in shared_users[:15]:
                user_id = f"user_{user['login']}"
                nodes.append({
                    "id": user_id,
                    "type": "user",
                    "login": user["login"],
                    "name": user.get("name") or user["login"],
                    "avatar_url": user.get("avatar_url"),
                    "shared_count": user["shared_count"]
                })
                # Enlaces a repos
                for repo_name in user["shared_repos"]:
                    links.append({
                        "source": user_id,
                        "target": f"repo_{repo_name}",
                        "type": "contributed_to"
                    })
            
            result["shared_users"] = shared_users
            result["collaboration_graph"] = {"nodes": nodes, "links": links}
            result["metrics"] = {
                "total_repos_analyzed": len(repo_collaborators),
                "total_unique_users": len(all_users),
                "shared_users_count": len(user_appearances),
                "collaboration_density": round(len(user_appearances) / max(len(all_users), 1) * 100, 2)
            }
            
            # Guardar en caché permanente
            if cache_key:
                try:
                    metrics_collection.update_one(
                        {"_id": cache_key},
                        {"$set": {**result, "_cached_at": datetime.now().isoformat()}},
                        upsert=True
                    )
                    logger.info(f"[Analyze] Cacheado: {cache_key}")
                except Exception as ce:
                    logger.warning(f"[Analyze] Error cacheando: {ce}")
            
            return result
        
        # ============================================================
        # MODO 3: Análisis de ORGS seleccionadas
        # ============================================================
        if orgs and len(orgs) >= 2:
            result["mode"] = "orgs_comparison"
            result["selections"] = orgs
            
            # Obtener usuarios de cada org
            org_users = {}
            all_users = set()
            
            for org_login in orgs:
                # Buscar repos de la org
                org_repos = list(repos_collection.find(
                    {"$or": [{"owner.login": org_login}, {"organization.login": org_login}]},
                    {"collaborators": 1, "full_name": 1}
                ))
                
                # Extraer usuarios únicos
                users_in_org = set()
                for repo in org_repos:
                    for collab in repo.get("collaborators", []):
                        if collab.get("login"):
                            users_in_org.add(collab.get("login"))
                
                # También buscar usuarios que declaren pertenecer a la org
                users_declaring_org = users_collection.find(
                    {"$or": [
                        {"organizations": org_login},
                        {"organizations.login": org_login}
                    ]},
                    {"login": 1}
                )
                for u in users_declaring_org:
                    users_in_org.add(u.get("login"))
                
                org_users[org_login] = users_in_org
                all_users.update(users_in_org)
            
            # Encontrar usuarios compartidos
            user_appearances = {}
            for user_login in all_users:
                orgs_with_user = [
                    org_login for org_login, users in org_users.items()
                    if user_login in users
                ]
                if len(orgs_with_user) >= 2:
                    user_appearances[user_login] = orgs_with_user
            
            # Enriquecer usuarios compartidos
            shared_users = []
            for login, orgs_list in sorted(user_appearances.items(), key=lambda x: len(x[1]), reverse=True)[:20]:
                user_info = users_collection.find_one({"login": login})
                shared_users.append({
                    "login": login,
                    "name": user_info.get("name") if user_info else None,
                    "avatar_url": user_info.get("avatar_url") if user_info else None,
                    "quantum_expertise_score": user_info.get("quantum_expertise_score", 0) if user_info else 0,
                    "shared_orgs": orgs_list,
                    "shared_count": len(orgs_list)
                })
            
            # Construir grafo
            nodes = []
            links = []
            
            # Añadir orgs como nodos
            for org_login in orgs:
                org_doc = orgs_collection.find_one({"login": org_login})
                nodes.append({
                    "id": f"org_{org_login}",
                    "type": "org",
                    "login": org_login,
                    "name": org_doc.get("name") if org_doc else org_login,
                    "avatar_url": org_doc.get("avatar_url") if org_doc else None
                })
            
            # Añadir usuarios compartidos
            for user in shared_users[:15]:
                user_id = f"user_{user['login']}"
                nodes.append({
                    "id": user_id,
                    "type": "user",
                    "login": user["login"],
                    "name": user.get("name") or user["login"],
                    "avatar_url": user.get("avatar_url"),
                    "shared_count": user["shared_count"]
                })
                # Enlaces a orgs
                for org_login in user["shared_orgs"]:
                    links.append({
                        "source": user_id,
                        "target": f"org_{org_login}",
                        "type": "member_of"
                    })
            
            result["shared_users"] = shared_users
            result["collaboration_graph"] = {"nodes": nodes, "links": links}
            result["metrics"] = {
                "total_orgs_analyzed": len(org_users),
                "total_unique_users": len(all_users),
                "shared_users_count": len(user_appearances),
                "collaboration_density": round(len(user_appearances) / max(len(all_users), 1) * 100, 2)
            }
            
            # Guardar en caché permanente
            if cache_key:
                try:
                    metrics_collection.update_one(
                        {"_id": cache_key},
                        {"$set": {**result, "_cached_at": datetime.now().isoformat()}},
                        upsert=True
                    )
                    logger.info(f"[Analyze] Cacheado: {cache_key}")
                except Exception as ce:
                    logger.warning(f"[Analyze] Error cacheando: {ce}")
            
            return result
        
        # Si no hay parámetros válidos
        raise HTTPException(
            status_code=400,
            detail="Se requiere: user=login, repos=[repo1,repo2,...] (mínimo 2), o orgs=[org1,org2,...] (mínimo 2)"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"Error en análisis de colaboración: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/collaboration/user/{user_login}")
async def get_user_collaboration_network(user_login: str):
    """
    Obtiene la red de colaboración de un usuario específico.
    Endpoint simplificado para llamadas GET directas.
    """
    return await analyze_collaboration(user=user_login)


# ==========================================
# ENDPOINTS DE ANÁLISIS DE RED (NetworkX)
# ==========================================

# Caché en memoria del resultado de análisis (evita recalcular en cada request)
# Almacena tanto el dict como los bytes JSON serializados con orjson
# Fallback: si la caché en memoria está vacía, intenta cargar desde MongoDB (chunked)
_network_metrics_cache = {"json_bytes": None, "computed_at": None, "analyzer": None}

@router.get("/collaboration/network-metrics")
async def get_network_metrics(force_refresh: bool = Query(default=False)):
    """
    Computa métricas de red de colaboración optimizadas para el frontend.
    Devuelve solo: node_metrics (compacto), communities, global_metrics.
    Omite edge_metrics, searchable_nodes, bus_factors (no usados por UI).
    Caché PERMANENTE: memoria + MongoDB chunked. Sin TTL. Usa orjson.
    Invalidación solo vía POST /dashboard/refresh-metrics o tras ingesta/enriquecimiento.
    """
    try:
        import orjson
        from fastapi.responses import Response
        from ..core.db import db
        from ..core.chunked_cache import load_chunked, save_chunked
        
        # ── 1. Caché en memoria (más rápido, sin TTL) ──
        cache = _network_metrics_cache
        if not force_refresh and cache["json_bytes"] and cache["computed_at"]:
            logger.info("[NetworkMetrics] Devolviendo desde caché en memoria (permanente)")
            return Response(
                content=cache["json_bytes"],
                media_type="application/json"
            )
        
        db.ensure_connection()
        metrics_collection = db.get_collection("metrics")
        
        # ── 2. Caché en MongoDB chunked (sobrevive restarts, sin TTL) ──
        if not force_refresh:
            cached_result = load_chunked(metrics_collection, "network_metrics")
            if cached_result:
                json_bytes = orjson.dumps(cached_result)
                # Poblar caché en memoria
                _network_metrics_cache["json_bytes"] = json_bytes
                _network_metrics_cache["computed_at"] = datetime.utcnow()
                logger.info(f"[NetworkMetrics] Restaurado desde caché MongoDB chunked permanente ({len(json_bytes) / 1024:.0f} KB)")
                return Response(content=json_bytes, media_type="application/json")
        
        # ── 3. Computar desde cero ──
        logger.info("[NetworkMetrics] Construyendo grafo y computando métricas...")
        repos_col = db.get_collection("repositories")
        users_col = db.get_collection("users")
        orgs_col = db.get_collection("organizations")
        
        analyzer = CollaborationNetworkAnalyzer()
        analyzer.build_from_mongodb(repos_col, users_col, orgs_col)
        full = analyzer.get_full_analysis()
        
        # Construir respuesta compacta — solo lo que el frontend necesita
        compact_node_metrics = {}
        for node_id, m in full.get("node_metrics", {}).items():
            entry = {
                "betweenness": m.get("betweenness", 0),
                "degree": m.get("degree", 0),
                "collab_centrality": m.get("collab_centrality", 0),
                "collab_connectivity": m.get("collab_connectivity", 0),
                "collab_centrality_raw": m.get("collab_centrality_raw", 0),
                "collab_connectivity_raw": m.get("collab_connectivity_raw", 0),
            }
            if "community_id" in m:
                entry["community_id"] = m["community_id"]
                entry["community_color"] = m.get("community_color", "#888888")
            if "bus_factor_risk" in m:
                entry["bus_factor"] = m.get("bus_factor", 0)
                entry["bus_factor_risk"] = m["bus_factor_risk"]
                tc = m.get("top_contributors", [])
                if tc:
                    entry["top_contributors"] = [
                        {"login": c["login"], "percentage": c.get("percentage", 0)}
                        for c in tc[:3]
                    ]
            compact_node_metrics[node_id] = entry
        
        # Comunidades compactas
        compact_communities = [
            {
                "id": c["id"],
                "color": c["color"],
                "size": c["size"],
                "label": c["label"],
            }
            for c in full.get("communities", [])
        ]
        
        result = {
            "node_metrics": compact_node_metrics,
            "communities": compact_communities,
            "global_metrics": full.get("global_metrics", {}),
        }
        
        # Serializar con orjson (~10x más rápido que json.dumps)
        json_bytes = orjson.dumps(result)
        
        # Guardar en caché en memoria
        _network_metrics_cache["json_bytes"] = json_bytes
        _network_metrics_cache["computed_at"] = datetime.utcnow()
        _network_metrics_cache["analyzer"] = analyzer
        
        # Guardar en MongoDB chunked (persistente, sobrevive restarts)
        try:
            save_chunked(
                metrics_collection,
                "network_metrics",
                result,
                large_fields=["node_metrics"]
            )
        except Exception as mongo_err:
            logger.warning(f"[NetworkMetrics] No se pudo persistir a MongoDB: {mongo_err}")
        
        logger.info(
            f"[NetworkMetrics] Respuesta: {len(compact_node_metrics)} nodos, "
            f"{len(compact_communities)} comunidades, "
            f"{len(json_bytes) / 1024:.0f} KB (cacheado en memoria + MongoDB)"
        )
        return Response(content=json_bytes, media_type="application/json")
        
    except Exception as e:
        error_msg = f"Error computing network metrics: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


@router.get("/collaboration/quantum-tunneling")
async def quantum_tunneling(
    source: str = Query(..., description="ID del nodo origen (ej: user_octocat)"),
    target: str = Query(..., description="ID del nodo destino (ej: repo_qiskit/qiskit)")
):
    """
    Encuentra el camino más corto entre dos entidades de la red (Quantum Tunneling).
    Retorna: nodos del camino, aristas, descripción, longitud.
    Reutiliza el grafo cacheado de network-metrics si está disponible.
    """
    try:
        from ..core.db import db
        
        # Reutilizar analyzer del caché si existe
        analyzer = _network_metrics_cache.get("analyzer")
        if not analyzer:
            # Intentar restaurar desde caché MongoDB chunked (persistente)
            from ..core.chunked_cache import load_chunked
            db.ensure_connection()
            metrics_collection = db.get_collection("metrics")
            cached_nm = load_chunked(metrics_collection, "network_metrics")
            
            if cached_nm:
                # Reconstruir grafo NetworkX desde los node_metrics cacheados
                logger.info("[QuantumTunneling] Reconstruyendo analyzer desde caché MongoDB...")
                repos_col = db.get_collection("repositories")
                users_col = db.get_collection("users")
                orgs_col = db.get_collection("organizations")
                
                analyzer = CollaborationNetworkAnalyzer()
                analyzer.build_from_mongodb(repos_col, users_col, orgs_col)
                _network_metrics_cache["analyzer"] = analyzer
                logger.info("[QuantumTunneling] Analyzer reconstruido y cacheado en memoria")
            else:
                logger.info("[QuantumTunneling] Sin caché, construyendo grafo completo...")
                db.ensure_connection()
                repos_col = db.get_collection("repositories")
                users_col = db.get_collection("users")
                orgs_col = db.get_collection("organizations")
                
                analyzer = CollaborationNetworkAnalyzer()
                analyzer.build_from_mongodb(repos_col, users_col, orgs_col)
                _network_metrics_cache["analyzer"] = analyzer
        else:
            logger.info("[QuantumTunneling] Usando grafo cacheado en memoria")
        
        result = analyzer.find_path(source, target)
        return result
        
    except Exception as e:
        error_msg = f"Error in quantum tunneling: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=500, detail=error_msg)


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
        
        # Invalidar cachés para que se recalculen con datos frescos
        try:
            invalidate_all_caches()
            logger.info(f"✅ Tarea {task_id} completada + cachés invalidadas")
        except Exception as cache_err:
            logger.warning(f"✅ Tarea {task_id} completada (error al invalidar cachés: {cache_err})")
        
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
        
        # Invalidar cachés para que se recalculen con datos frescos
        try:
            invalidate_all_caches()
            logger.info(f"✅ Tarea {task_id} completada + cachés invalidadas")
        except Exception as cache_err:
            logger.warning(f"✅ Tarea {task_id} completada (error al invalidar cachés: {cache_err})")
        
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
        
        # Invalidar cachés para que se recalculen con datos frescos
        try:
            invalidate_all_caches()
            logger.info(f"✅ Tarea {task_id} completada + cachés invalidadas")
        except Exception as cache_err:
            logger.warning(f"✅ Tarea {task_id} completada (error al invalidar cachés: {cache_err})")
        
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
        
        # Invalidar cachés para que se recalculen con datos frescos
        try:
            invalidate_all_caches()
            logger.info(f"✅ Tarea {task_id} completada + cachés invalidadas")
        except Exception as cache_err:
            logger.warning(f"✅ Tarea {task_id} completada (error al invalidar cachés: {cache_err})")
        
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
        
        # Invalidar cachés para que se recalculen con datos frescos
        try:
            invalidate_all_caches()
            logger.info(f"✅ Tarea {task_id} completada + cachés invalidadas")
        except Exception as cache_err:
            logger.warning(f"✅ Tarea {task_id} completada (error al invalidar cachés: {cache_err})")
        
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
        
        # Invalidar cachés para que se recalculen con datos frescos
        try:
            invalidate_all_caches()
            logger.info(f"✅ Tarea {task_id} completada + cachés invalidadas")
        except Exception as cache_err:
            logger.warning(f"✅ Tarea {task_id} completada (error al invalidar cachés: {cache_err})")
        
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
        
        # Invalidar cachés para que se recalculen con datos frescos
        try:
            invalidate_all_caches()
            logger.info("🧹 Cachés invalidadas tras pipeline completo")
        except Exception as cache_err:
            logger.warning(f"⚠️ Error al invalidar cachés tras pipeline: {cache_err}")
        
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
        
        # Invalidar cachés para que se recalculen con datos frescos
        try:
            invalidate_all_caches()
            logger.info("🧹 Cachés invalidadas tras pipeline script")
        except Exception as cache_err:
            logger.warning(f"⚠️ Error al invalidar cachés tras pipeline script: {cache_err}")
        
    except Exception as e:
        logger.error(f"Error ejecutando pipeline {task_id}: {e}")
        background_tasks_status[task_id]["status"] = "failed"
        background_tasks_status[task_id]["progress"] = f"Error: {str(e)}"
        background_tasks_status[task_id]["error"] = str(e)
        background_tasks_status[task_id]["failed_at"] = datetime.now().isoformat()
