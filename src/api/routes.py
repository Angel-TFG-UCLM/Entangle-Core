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
async def get_dashboard_stats():
    """
    Endpoint inteligente para dashboard con sistema de caché MongoDB.
    
    Estrategia de Caché:
    - Consulta colección 'metrics' buscando { "type": "dashboard_stats" }
    - Si existe y updated_at < 24h → Retorna caché (0ms latency)
    - Si NO existe o es antiguo → Calcula con agregaciones y guarda
    
    Retorna:
    - kpis: { totalRepos, totalUsers, totalOrgs }
    - topLanguages: [{ name, count, percentage }, ...] (Top 5)
    - topOrganizations: [{ name, repoCount, totalStars }, ...] (Top 5)
    - metadata: { cached, calculatedAt, expiresAt }
    """
    try:
        from ..core.db import db
        from datetime import timedelta
        
        # Asegurar conexión activa
        db.ensure_connection()
        
        # Configuración de caché (24 horas)
        CACHE_TTL_HOURS = 24
        current_time = datetime.now()
        
        # 1. INTENTAR OBTENER CACHÉ
        metrics_collection = db.get_collection("metrics")
        cached_stats = metrics_collection.find_one({"type": "dashboard_stats"})
        
        if cached_stats:
            updated_at = cached_stats.get("updated_at")
            if updated_at and isinstance(updated_at, datetime):
                age_hours = (current_time - updated_at).total_seconds() / 3600
                
                # Si el caché es fresco (< 24h), retornarlo
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
        
        logger.info("📊 Cache MISS - Calculando dashboard stats desde MongoDB...")
        
        # 2. CALCULAR ESTADÍSTICAS (Caché expirado o no existe)
        repos_collection = db.get_collection("repositories")
        users_collection = db.get_collection("users")
        orgs_collection = db.get_collection("organizations")
        
        # === KPIs: Conteos básicos ===
        total_repos = repos_collection.count_documents({}, maxTimeMS=10000)
        total_users = users_collection.count_documents({}, maxTimeMS=10000)
        total_orgs = orgs_collection.count_documents({}, maxTimeMS=10000)
        
        kpis = {
            "totalRepos": total_repos,
            "totalUsers": total_users,
            "totalOrgs": total_orgs
        }
        
        # === TOP LENGUAJES: Agregación ===
        # Agrupar repos por primary_language.name, contar y ordenar descendente
        language_pipeline = [
            # Filtrar repos que tengan lenguaje definido
            {"$match": {"primary_language.name": {"$exists": True, "$ne": None}}},
            # Agrupar por lenguaje
            {"$group": {
                "_id": "$primary_language.name",
                "count": {"$sum": 1}
            }},
            # Ordenar por count descendente
            {"$sort": {"count": -1}},
            # Limitar a Top 5
            {"$limit": 5},
            # Renombrar _id a name
            {"$project": {
                "_id": 0,
                "name": "$_id",
                "count": 1
            }}
        ]
        
        top_languages_cursor = repos_collection.aggregate(language_pipeline)
        top_languages_raw = list(top_languages_cursor)
        
        # Calcular porcentajes
        total_repos_with_lang = sum(item["count"] for item in top_languages_raw)
        top_languages = [
            {
                "name": item["name"],
                "count": item["count"],
                "percentage": round((item["count"] / total_repos_with_lang * 100), 2) if total_repos_with_lang > 0 else 0
            }
            for item in top_languages_raw
        ]
        
        # === TOP ORGANIZACIONES: Agregación ===
        # Agrupar repos por owner.login, contar y sumar stars
        org_pipeline = [
            # Filtrar repos que tengan owner definido
            {"$match": {"owner.login": {"$exists": True, "$ne": None}}},
            # Agrupar por organización
            {"$group": {
                "_id": "$owner.login",
                "repoCount": {"$sum": 1},
                "totalStars": {"$sum": "$stargazer_count"}
            }},
            # Ordenar por repoCount descendente
            {"$sort": {"repoCount": -1}},
            # Limitar a Top 5
            {"$limit": 5},
            # Renombrar campos
            {"$project": {
                "_id": 0,
                "name": "$_id",
                "repoCount": 1,
                "totalStars": 1
            }}
        ]
        
        top_orgs_cursor = repos_collection.aggregate(org_pipeline)
        top_organizations = list(top_orgs_cursor)
        
        # 3. PREPARAR RESPUESTA
        response_data = {
            "kpis": kpis,
            "topLanguages": top_languages,
            "topOrganizations": top_organizations,
            "metadata": {
                "cached": False,
                "calculatedAt": current_time.isoformat(),
                "expiresAt": (current_time + timedelta(hours=CACHE_TTL_HOURS)).isoformat(),
                "ageHours": 0
            }
        }
        
        # 4. GUARDAR EN CACHÉ (Upsert)
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
        
        logger.info(f"✅ Dashboard stats calculado y guardado en caché (válido por {CACHE_TTL_HOURS}h)")
        
        return response_data
        
    except Exception as e:
        error_msg = f"Error al obtener dashboard stats: {str(e)}"
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
    limit: int = Query(default=50, ge=1, le=1000, description="Límite de resultados"),
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
        repositories = list(repo_collection.find(filter_query).skip(skip).limit(limit))
        
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
    limit: int = Query(default=50, ge=1, le=1000, description="Límite de resultados")
):
    """
    Lista usuarios desde la base de datos con paginación.
    """
    try:
        from ..core.db import db
        
        user_collection = db.get_collection("users")
        users = list(user_collection.find({}).skip(skip).limit(limit))
        
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
    limit: int = Query(default=50, ge=1, le=1000, description="Límite de resultados")
):
    """
    Lista organizaciones desde la base de datos con paginación.
    """
    try:
        from ..core.db import db
        
        org_collection = db.get_collection("organizations")
        organizations = list(org_collection.find({}).skip(skip).limit(limit))
        
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
