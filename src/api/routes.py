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
