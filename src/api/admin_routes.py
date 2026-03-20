"""
Admin Routes — Endpoints protegidos para gestión de operaciones ENTANGLE.

Funcionalidades:
- Autenticación por contraseña (bcrypt hash en MongoDB)
- Ejecución de ingestas/enriquecimientos individuales y pipeline completo
- Progreso en tiempo real con ETA
- Cancelación de operaciones en curso
- Historial persistente de operaciones
"""
import bcrypt
import logging
import threading
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from ..core.db import db
from ..core.logger import logger
from ..core.config import config, ingestion_config
from ..core.mongo_repository import MongoRepository
from ..github.repositories_ingestion import IngestionEngine
from ..github.user_ingestion import UserIngestionEngine
from ..github.organization_ingestion import OrganizationIngestionEngine
from ..github.repositories_enrichment import EnrichmentEngine
from ..github.user_enrichment import UserEnrichmentEngine
from ..github.organization_enrichment import OrganizationEnrichmentEngine
from ..github.graphql_client import GitHubGraphQLClient

# Router de administración
admin_router = APIRouter(prefix="/admin", tags=["admin"])

# ============================================================================
# MODELOS
# ============================================================================

class PasswordPayload(BaseModel):
    password: str

class SetPasswordPayload(BaseModel):
    password: str
    current_password: Optional[str] = None

class OperationRequest(BaseModel):
    operation_type: str  # 'ingestion' | 'enrichment' | 'pipeline'
    entity: Optional[str] = None  # 'repositories' | 'users' | 'organizations' | None (pipeline)
    mode: str = "incremental"  # 'incremental' | 'from_scratch' | 'full'
    max_results: Optional[int] = None
    max_workers: int = 4
    batch_size: int = 50
    force_reenrich: bool = False


# ============================================================================
# ESTADO EN MEMORIA — Operaciones activas + flags de cancelación
# ============================================================================

# Operaciones activas con progreso detallado
active_operations: Dict[str, Dict[str, Any]] = {}

# Flags de cancelación (threading.Event para cada operación)
cancel_flags: Dict[str, threading.Event] = {}

# Buffers de logs por operación (captura en tiempo real)
MAX_OPERATION_LOGS = 2000
operation_logs: Dict[str, List[Dict]] = {}

# Thread-local para rastrear qué operación ejecuta cada hilo
_thread_local = threading.local()


class OperationLogHandler(logging.Handler):
    """
    Handler de logging que captura mensajes para la operación activa
    en el hilo actual. Permite al frontend ver logs en tiempo real.
    """

    def __init__(self):
        super().__init__()
        self.setLevel(logging.DEBUG)

    def emit(self, record):
        try:
            op_id = getattr(_thread_local, 'operation_id', None)
            if op_id and op_id in operation_logs:
                entry = {
                    "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                    "level": record.levelname,
                    "msg": record.getMessage(),
                    "src": f"{record.module}.{record.funcName}",
                }
                buf = operation_logs[op_id]
                buf.append(entry)
                # Limitar tamaño del buffer
                if len(buf) > MAX_OPERATION_LOGS:
                    del buf[:len(buf) - MAX_OPERATION_LOGS]
        except Exception:
            pass  # Nunca dejar que un error de logging crashee la operación


# Registrar handler en el logger global para capturar logs de operaciones
_op_log_handler = OperationLogHandler()
logger.addHandler(_op_log_handler)


# ============================================================================
# AUTENTICACIÓN
# ============================================================================

def _get_admin_collection():
    """Obtiene la colección de configuración admin."""
    db.ensure_connection()
    return db.get_collection("admin_config")

def _verify_password(password: str) -> bool:
    """Verifica la contraseña contra el hash almacenado en MongoDB."""
    try:
        col = _get_admin_collection()
        doc = col.find_one({"type": "admin_password"})
        if not doc:
            return False
        stored_hash = doc["password_hash"]
        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode('utf-8')
        return bcrypt.checkpw(password.encode('utf-8'), stored_hash)
    except Exception as e:
        logger.error(f"Error verificando contraseña admin: {e}")
        return False

def _has_password_set() -> bool:
    """Comprueba si ya hay una contraseña configurada."""
    try:
        col = _get_admin_collection()
        return col.count_documents({"type": "admin_password"}) > 0
    except Exception:
        return False


@admin_router.post("/auth")
async def admin_authenticate(payload: PasswordPayload):
    """
    Autentica al administrador con contraseña.
    Retorna un token de sesión temporal (válido mientras el backend esté activo).
    """
    if not _has_password_set():
        raise HTTPException(status_code=403, detail="No hay contraseña configurada. Usa /admin/setup-password primero.")
    
    if not _verify_password(payload.password):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta")
    
    # Generar token de sesión simple (en memoria, no persiste entre reinicios)
    token = str(uuid.uuid4())
    
    # Guardar token activo
    if not hasattr(admin_authenticate, '_active_tokens'):
        admin_authenticate._active_tokens = set()
    admin_authenticate._active_tokens.add(token)
    
    logger.info("🔐 Admin autenticado correctamente")
    
    return {
        "authenticated": True,
        "token": token,
        "message": "Autenticación exitosa"
    }


@admin_router.post("/setup-password")
async def setup_admin_password(payload: SetPasswordPayload):
    """
    Configura o cambia la contraseña de administrador.
    - Si no hay contraseña: la establece sin requerir current_password.
    - Si ya existe: requiere current_password para cambiarla.
    """
    col = _get_admin_collection()
    
    has_password = _has_password_set()
    
    if has_password:
        if not payload.current_password:
            raise HTTPException(status_code=400, detail="Se requiere la contraseña actual para cambiarla")
        if not _verify_password(payload.current_password):
            raise HTTPException(status_code=401, detail="Contraseña actual incorrecta")
    
    # Hashear la nueva contraseña
    salt = bcrypt.gensalt(rounds=12)
    password_hash = bcrypt.hashpw(payload.password.encode('utf-8'), salt)
    
    col.update_one(
        {"type": "admin_password"},
        {"$set": {
            "type": "admin_password",
            "password_hash": password_hash.decode('utf-8'),
            "updated_at": datetime.now().isoformat()
        }},
        upsert=True
    )
    
    logger.info("🔐 Contraseña de admin actualizada")
    
    return {
        "success": True,
        "message": "Contraseña configurada correctamente",
        "is_new": not has_password
    }


@admin_router.get("/has-password")
async def check_has_password():
    """Comprueba si ya hay una contraseña de admin configurada."""
    return {"has_password": _has_password_set()}


def _validate_admin_token(token: str) -> bool:
    """Valida un token de sesión admin."""
    if not hasattr(admin_authenticate, '_active_tokens'):
        return False
    return token in admin_authenticate._active_tokens


def _require_admin(token: str):
    """Middleware que valida el token admin en cada request protegida."""
    if not token or not _validate_admin_token(token):
        raise HTTPException(status_code=401, detail="Token de administrador inválido o expirado")


# ============================================================================
# OPERACIONES — Ejecutar ingestas/enriquecimientos
# ============================================================================

@admin_router.post("/operations/run")
async def run_operation(request: OperationRequest, token: str = Query(..., description="Token de sesión admin")):
    """
    Ejecuta una operación de ingesta, enriquecimiento o pipeline completo.
    Retorna un operation_id para seguimiento.
    """
    _require_admin(token)
    
    operation_id = f"op_{request.operation_type}_{request.entity or 'all'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    
    # Verificar que no haya una operación del mismo tipo en curso
    for op_id, op in active_operations.items():
        if op["status"] == "running":
            if op["operation_type"] == request.operation_type and op.get("entity") == request.entity:
                raise HTTPException(
                    status_code=409, 
                    detail=f"Ya hay una operación '{request.operation_type}/{request.entity}' en curso: {op_id}"
                )
    
    # Crear flag de cancelación
    cancel_event = threading.Event()
    cancel_flags[operation_id] = cancel_event
    
    # Registrar operación
    operation_data = {
        "operation_id": operation_id,
        "operation_type": request.operation_type,
        "entity": request.entity,
        "mode": request.mode,
        "status": "running",
        "progress": 0,
        "progress_message": "Inicializando...",
        "items_processed": 0,
        "items_total": 0,
        "started_at": datetime.now().isoformat(),
        "eta_seconds": None,
        "stats": None,
        "error": None,
    }
    active_operations[operation_id] = operation_data
    
    # Lanzar en hilo separado
    thread = threading.Thread(
        target=_execute_operation,
        args=(operation_id, request, cancel_event),
        daemon=True
    )
    thread.start()
    
    logger.info(f"🚀 Operación admin iniciada: {operation_id}")
    
    return operation_data


@admin_router.get("/operations/active")
async def get_active_operations(token: str = Query(..., description="Token de sesión admin")):
    """Lista todas las operaciones activas (en curso)."""
    _require_admin(token)
    
    running = {k: v for k, v in active_operations.items() if v["status"] == "running"}
    return {
        "count": len(running),
        "operations": list(running.values())
    }


@admin_router.get("/operations/{operation_id}")
async def get_operation_status(operation_id: str, token: str = Query(..., description="Token de sesión admin")):
    """Obtiene el estado detallado de una operación."""
    _require_admin(token)
    
    if operation_id in active_operations:
        return active_operations[operation_id]
    
    # Buscar en historial persistente
    try:
        col = _get_history_collection()
        doc = col.find_one({"operation_id": operation_id}, {"_id": 0})
        if doc:
            return doc
    except Exception:
        pass
    
    raise HTTPException(status_code=404, detail=f"Operación {operation_id} no encontrada")


@admin_router.post("/operations/{operation_id}/cancel")
async def cancel_operation(operation_id: str, token: str = Query(..., description="Token de sesión admin")):
    """Cancela una operación en curso."""
    _require_admin(token)
    
    if operation_id not in active_operations:
        raise HTTPException(status_code=404, detail="Operación no encontrada")
    
    if active_operations[operation_id]["status"] != "running":
        raise HTTPException(status_code=400, detail="La operación no está en curso")
    
    # Señalizar cancelación
    if operation_id in cancel_flags:
        cancel_flags[operation_id].set()
    
    active_operations[operation_id]["status"] = "cancelling"
    active_operations[operation_id]["progress_message"] = "Cancelando operación..."
    
    logger.info(f"⚠️ Cancelación solicitada para: {operation_id}")
    
    return {"message": "Cancelación solicitada", "operation_id": operation_id}


@admin_router.get("/operations/{operation_id}/logs")
async def get_operation_logs(
    operation_id: str,
    token: str = Query(..., description="Token de sesión admin"),
    since: int = Query(0, ge=0, description="Índice desde el que obtener logs nuevos")
):
    """
    Obtiene los logs de ejecución de una operación en tiempo real.
    Usa el parámetro `since` para obtener solo logs nuevos (polling incremental).
    """
    _require_admin(token)

    if operation_id not in operation_logs:
        return {"logs": [], "total": 0, "next_index": 0}

    logs = operation_logs[operation_id]
    total = len(logs)
    new_logs = logs[since:] if since < total else []

    return {
        "logs": new_logs,
        "total": total,
        "next_index": total,
    }


# ============================================================================
# HISTORIAL PERSISTENTE
# ============================================================================

def _get_history_collection():
    """Obtiene la colección de historial de operaciones."""
    db.ensure_connection()
    return db.get_collection("operation_history")


@admin_router.get("/history")
async def get_operation_history(
    token: str = Query(..., description="Token de sesión admin"),
    limit: int = Query(50, ge=1, le=200),
    operation_type: Optional[str] = Query(None)
):
    """Obtiene el historial de operaciones ejecutadas."""
    _require_admin(token)
    
    try:
        col = _get_history_collection()
        query = {}
        if operation_type:
            query["operation_type"] = operation_type
        
        cursor = col.find(query, {"_id": 0}).sort("started_at", -1).limit(limit)
        history = list(cursor)
        
        return {
            "count": len(history),
            "operations": history
        }
    except Exception as e:
        logger.error(f"Error obteniendo historial: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.delete("/history")
async def clear_history(token: str = Query(..., description="Token de sesión admin")):
    """Limpia el historial de operaciones."""
    _require_admin(token)
    
    try:
        col = _get_history_collection()
        result = col.delete_many({})
        return {"deleted": result.deleted_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ESTADÍSTICAS DB
# ============================================================================

@admin_router.get("/db-stats")
async def get_db_stats(token: str = Query(..., description="Token de sesión admin")):
    """Obtiene estadísticas de las colecciones de la base de datos."""
    _require_admin(token)
    
    try:
        db.ensure_connection()
        database = db.get_database()
        
        collections_info = {}
        # Mapeo colección → clave en ingestion_metadata
        metadata_keys = {
            "repositories": "repositories_last_ingestion",
            "users": "users_last_ingestion",
            "organizations": "organizations_last_ingestion",
        }
        for col_name in ["repositories", "users", "organizations"]:
            col = database[col_name]
            count = col.count_documents({})
            
            # Obtener última fecha de actualización desde los documentos
            last_updated = None
            last_doc = col.find_one({"ingested_at": {"$exists": True}}, sort=[("ingested_at", -1)])
            if last_doc and last_doc.get("ingested_at"):
                last_updated = last_doc["ingested_at"]
            
            # Fallback: buscar en ingestion_metadata
            if not last_updated:
                meta_col = database.get_collection("ingestion_metadata")
                meta_doc = meta_col.find_one({"type": metadata_keys.get(col_name)})
                if meta_doc and meta_doc.get("date"):
                    last_updated = meta_doc["date"]
            
            collections_info[col_name] = {
                "count": count,
                "last_updated": last_updated
            }
        
        return {
            "database": config.MONGO_DB_NAME,
            "collections": collections_info
        }
    except Exception as e:
        logger.error(f"Error obteniendo stats DB: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# EJECUCIÓN DE OPERACIONES EN BACKGROUND
# ============================================================================

def _save_to_history(operation_data: dict):
    """Guarda una operación completada en el historial persistente."""
    try:
        col = _get_history_collection()
        # Copiar datos relevantes
        history_entry = {
            "operation_id": operation_data["operation_id"],
            "operation_type": operation_data["operation_type"],
            "entity": operation_data.get("entity"),
            "mode": operation_data.get("mode"),
            "status": operation_data["status"],
            "started_at": operation_data["started_at"],
            "completed_at": operation_data.get("completed_at"),
            "duration_seconds": operation_data.get("duration_seconds"),
            "items_processed": operation_data.get("items_processed", 0),
            "items_total": operation_data.get("items_total", 0),
            "stats": operation_data.get("stats"),
            "error": operation_data.get("error"),
        }
        col.insert_one(history_entry)
        logger.info(f"📝 Operación guardada en historial: {operation_data['operation_id']}")
    except Exception as e:
        logger.error(f"Error guardando en historial: {e}")


def _update_progress(operation_id: str, message: str, items_processed: int = 0, items_total: int = 0):
    """Actualiza el progreso de una operación activa."""
    if operation_id not in active_operations:
        return
    
    op = active_operations[operation_id]
    op["progress_message"] = message
    op["items_processed"] = items_processed
    op["items_total"] = items_total
    
    if items_total > 0:
        pct = (items_processed / items_total) * 100
        op["progress"] = round(pct, 1)
        
        # ETA suavizado con EMA (Exponential Moving Average)
        now_ts = datetime.now().timestamp()
        prev_ts = op.get("_eta_last_ts")
        prev_items = op.get("_eta_last_items", 0)
        
        if prev_ts is not None and items_processed > prev_items:
            dt = now_ts - prev_ts
            dp = items_processed - prev_items
            if dt > 0:
                instant_rate = dp / dt  # items/segundo
                
                # EMA: suavizar con factor alpha=0.2 (80% peso anterior, 20% nuevo)
                alpha = 0.2
                prev_rate = op.get("_eta_smooth_rate")
                if prev_rate and prev_rate > 0:
                    smooth_rate = prev_rate * (1 - alpha) + instant_rate * alpha
                else:
                    smooth_rate = instant_rate
                op["_eta_smooth_rate"] = smooth_rate
                
                remaining = items_total - items_processed
                new_eta = remaining / smooth_rate if smooth_rate > 0 else None
                
                if new_eta is not None and pct >= 5:
                    # Damping: el ETA no puede cambiar más de 25% respecto al anterior
                    prev_eta = op.get("eta_seconds")
                    if prev_eta and prev_eta > 0:
                        max_eta = prev_eta * 1.25
                        min_eta = prev_eta * 0.75
                        new_eta = max(min_eta, min(new_eta, max_eta))
                    op["eta_seconds"] = min(round(new_eta), 86400)
                else:
                    op["eta_seconds"] = None
        
        op["_eta_last_ts"] = now_ts
        op["_eta_last_items"] = items_processed
        
        # No mostrar ETA hasta tener suficiente progreso
        if pct < 5:
            op["eta_seconds"] = None
    else:
        op["progress"] = 0
        op["eta_seconds"] = None

    # También registrar en el buffer de logs de la operación
    if operation_id in operation_logs:
        operation_logs[operation_id].append({
            "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "level": "PROGRESS",
            "msg": message,
            "src": "admin.progress",
        })


def _is_cancelled(operation_id: str) -> bool:
    """Comprueba si una operación ha sido cancelada."""
    if operation_id in cancel_flags:
        return cancel_flags[operation_id].is_set()
    return False


def _finalize_operation(operation_id: str, status: str, stats: Any = None, error: str = None):
    """Finaliza una operación: actualiza estado, guarda en historial, limpia."""
    if operation_id not in active_operations:
        return
    
    op = active_operations[operation_id]
    op["status"] = status
    op["completed_at"] = datetime.now().isoformat()
    op["stats"] = stats
    op["error"] = error
    
    # Calcular duración
    started = datetime.fromisoformat(op["started_at"])
    op["duration_seconds"] = round((datetime.now() - started).total_seconds(), 1)
    
    if status == "completed":
        op["progress"] = 100
        op["progress_message"] = "Completado exitosamente"
    elif status == "cancelled":
        op["progress_message"] = "Operación cancelada por el usuario"
    elif status == "failed":
        op["progress_message"] = f"Error: {error}"
    
    # Guardar en historial persistente
    _save_to_history(op)
    
    # Limpiar flag de cancelación
    cancel_flags.pop(operation_id, None)
    
    # Invalidar cachés del backend principal
    try:
        from .routes import invalidate_all_caches
        invalidate_all_caches()
    except Exception:
        pass
    
    logger.info(f"{'✅' if status == 'completed' else '⚠️'} Operación finalizada [{status}]: {operation_id} ({op['duration_seconds']}s)")

    # Recortar buffer de logs (mantener últimas 500 entradas para revisión post-ejecución)
    if operation_id in operation_logs:
        operation_logs[operation_id] = operation_logs[operation_id][-500:]


def _execute_operation(operation_id: str, request: OperationRequest, cancel_event: threading.Event):
    """Ejecutor principal de operaciones en background."""
    # Inicializar buffer de logs y marcar hilo para captura
    operation_logs[operation_id] = []
    _thread_local.operation_id = operation_id

    try:
        if request.operation_type == "pipeline":
            _run_pipeline_operation(operation_id, request, cancel_event)
        elif request.operation_type == "ingestion":
            _run_ingestion_operation(operation_id, request, cancel_event)
        elif request.operation_type == "enrichment":
            _run_enrichment_operation(operation_id, request, cancel_event)
        else:
            _finalize_operation(operation_id, "failed", error=f"Tipo de operación desconocido: {request.operation_type}")
    except Exception as e:
        logger.error(f"❌ Error en operación {operation_id}: {e}")
        _finalize_operation(operation_id, "failed", error=str(e))
    finally:
        # Limpiar contexto del hilo
        _thread_local.operation_id = None


# ── Ingesta ──────────────────────────────────────────────────────────────────

def _run_ingestion_operation(operation_id: str, request: OperationRequest, cancel_event: threading.Event):
    """Ejecuta una operación de ingesta."""
    entity = request.entity
    from_scratch = request.mode == "from_scratch"
    incremental = request.mode == "incremental"
    
    def progress_cb(processed, total, message):
        _update_progress(operation_id, message, processed, total)
    
    if entity == "repositories":
        _update_progress(operation_id, "Creando motor de ingesta de repositorios...")
        
        engine = IngestionEngine(
            incremental=incremental,
            from_scratch=from_scratch,
            max_workers=request.max_workers,
            progress_callback=progress_cb,
            cancel_event=cancel_event
        )
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        
        _update_progress(operation_id, "Ejecutando ingesta de repositorios...")
        stats = engine.run(max_results=request.max_results)
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled", stats=stats)
        else:
            _finalize_operation(operation_id, "completed", stats=stats)
    
    elif entity == "users":
        _update_progress(operation_id, "Creando motor de ingesta de usuarios...")
        
        github_client = GitHubGraphQLClient()
        repos_repo = MongoRepository("repositories")
        users_repo = MongoRepository("users", unique_fields=["id"])
        
        engine = UserIngestionEngine(
            github_client=github_client,
            repos_repository=repos_repo,
            users_repository=users_repo,
            batch_size=request.batch_size,
            from_scratch=from_scratch,
            progress_callback=progress_cb,
            cancel_event=cancel_event
        )
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        
        _update_progress(operation_id, "Ejecutando ingesta de usuarios...")
        stats = engine.run(max_repos=request.max_results)
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled", stats=stats)
        else:
            _finalize_operation(operation_id, "completed", stats=stats)
    
    elif entity == "organizations":
        _update_progress(operation_id, "Creando motor de ingesta de organizaciones...")
        
        users_repo = MongoRepository("users")
        orgs_repo = MongoRepository("organizations", unique_fields=["id"])
        
        engine = OrganizationIngestionEngine(
            github_token=config.GITHUB_TOKEN,
            users_repository=users_repo,
            organizations_repository=orgs_repo,
            batch_size=request.batch_size,
            from_scratch=from_scratch,
            progress_callback=progress_cb,
            cancel_event=cancel_event
        )
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        
        _update_progress(operation_id, "Ejecutando ingesta de organizaciones...")
        stats = engine.run(force_update=from_scratch)
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled", stats=stats)
        else:
            _finalize_operation(operation_id, "completed", stats=stats)
    
    else:
        _finalize_operation(operation_id, "failed", error=f"Entidad desconocida: {entity}")


# ── Enriquecimiento ─────────────────────────────────────────────────────────

def _run_enrichment_operation(operation_id: str, request: OperationRequest, cancel_event: threading.Event):
    """Ejecuta una operación de enriquecimiento."""
    entity = request.entity
    
    def progress_cb(processed, total, message):
        _update_progress(operation_id, message, processed, total)
    
    if entity == "repositories":
        _update_progress(operation_id, "Creando motor de enriquecimiento de repositorios...")
        
        repos_repo = MongoRepository("repositories")
        engine = EnrichmentEngine(
            github_token=config.GITHUB_TOKEN,
            repos_repository=repos_repo,
            batch_size=request.batch_size,
            progress_callback=progress_cb,
            cancel_event=cancel_event
        )
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        
        _update_progress(operation_id, "Ejecutando enriquecimiento de repositorios...")
        stats = engine.enrich_all_repositories(
            max_repos=request.max_results,
            force_reenrich=request.force_reenrich
        )
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled", stats=stats)
        else:
            _finalize_operation(operation_id, "completed", stats=stats)
    
    elif entity == "users":
        _update_progress(operation_id, "Creando motor de enriquecimiento de usuarios...")
        
        users_repo = MongoRepository("users")
        repos_repo = MongoRepository("repositories")
        engine = UserEnrichmentEngine(
            github_token=config.GITHUB_TOKEN,
            users_repository=users_repo,
            repos_repository=repos_repo,
            batch_size=request.batch_size,
            progress_callback=progress_cb,
            cancel_event=cancel_event
        )
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        
        _update_progress(operation_id, "Ejecutando enriquecimiento de usuarios...")
        stats = engine.enrich_all_users(
            max_users=request.max_results,
            force_reenrich=request.force_reenrich
        )
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled", stats=stats)
        else:
            _finalize_operation(operation_id, "completed", stats=stats)
    
    elif entity == "organizations":
        _update_progress(operation_id, "Creando motor de enriquecimiento de organizaciones...")
        
        orgs_repo = MongoRepository("organizations")
        repos_repo = MongoRepository("repositories")
        users_repo = MongoRepository("users")
        engine = OrganizationEnrichmentEngine(
            github_token=config.GITHUB_TOKEN,
            organizations_repository=orgs_repo,
            repositories_repository=repos_repo,
            users_repository=users_repo,
            batch_size=request.batch_size,
            progress_callback=progress_cb,
            cancel_event=cancel_event
        )
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        
        _update_progress(operation_id, "Ejecutando enriquecimiento de organizaciones...")
        stats = engine.enrich_all_organizations(
            max_orgs=request.max_results,
            force_reenrich=request.force_reenrich
        )
        
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled", stats=stats)
        else:
            _finalize_operation(operation_id, "completed", stats=stats)
    
    else:
        _finalize_operation(operation_id, "failed", error=f"Entidad desconocida: {entity}")


# ── Pipeline completo ────────────────────────────────────────────────────────

def _run_pipeline_operation(operation_id: str, request: OperationRequest, cancel_event: threading.Event):
    """Ejecuta el pipeline completo (6 fases) con progreso granular."""
    import os
    import traceback
    from ..github.user_ingestion import run_user_ingestion
    
    from_scratch = request.mode == "from_scratch"
    mode_label = "desde cero" if from_scratch else "incremental"
    github_token = os.getenv("GITHUB_TOKEN")
    
    if not github_token:
        _finalize_operation(operation_id, "failed", error="GITHUB_TOKEN no configurado")
        return
    
    phase_names = [
        "Ingesta de Repositorios",
        "Enriquecimiento de Repositorios",
        "Ingesta de Usuarios",
        "Enriquecimiento de Usuarios",
        "Ingesta de Organizaciones",
        "Enriquecimiento de Organizaciones",
    ]
    
    total_phases = len(phase_names)
    results = []

    # items_total=600 para resolución de sub-progreso (100 unidades por fase)
    active_operations[operation_id]["items_total"] = total_phases * 100

    def make_phase_progress_cb(phase_index):
        """Crea un callback que mapea el progreso interno del engine al progreso global del pipeline."""
        phase_label = phase_names[phase_index]
        def cb(processed, total, message):
            if total > 0:
                sub_pct = processed / total
            else:
                sub_pct = 0
            global_items = int((phase_index + sub_pct) * 100)
            _update_progress(
                operation_id,
                f"{phase_index + 1}/{total_phases} - {phase_label}: {message}",
                global_items,
                total_phases * 100
            )
        return cb
    
    try:
        # Fase 1: Ingesta de Repositorios
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        _update_progress(operation_id, f"1/{total_phases} - {phase_names[0]} ({mode_label})", 0, total_phases * 100)
        
        try:
            stats = IngestionEngine(
                incremental=not from_scratch,
                from_scratch=from_scratch,
                max_workers=request.max_workers,
                progress_callback=make_phase_progress_cb(0),
                cancel_event=cancel_event
            ).run(max_results=None, save_to_json=False)
            results.append({"phase": phase_names[0], "success": True, "stats": stats})
        except Exception as e:
            results.append({"phase": phase_names[0], "success": False, "error": str(e)})
            logger.error(f"Error en fase 1: {e}")
        
        # Fase 2: Enriquecimiento de Repositorios
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        _update_progress(operation_id, f"2/{total_phases} - {phase_names[1]}", 100, total_phases * 100)
        
        repo_repo = MongoRepository("repositories")
        try:
            stats = EnrichmentEngine(
                github_token=github_token,
                repos_repository=repo_repo,
                batch_size=100,
                progress_callback=make_phase_progress_cb(1),
                cancel_event=cancel_event
            ).enrich_all_repositories(max_repos=None, force_reenrich=request.force_reenrich)
            results.append({"phase": phase_names[1], "success": True, "stats": stats})
        except Exception as e:
            results.append({"phase": phase_names[1], "success": False, "error": str(e)})
            logger.error(f"Error en fase 2: {e}")
        
        # Fase 3: Ingesta de Usuarios
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        _update_progress(operation_id, f"3/{total_phases} - {phase_names[2]} ({mode_label})", 200, total_phases * 100)
        
        try:
            github_client = GitHubGraphQLClient()
            repos_repo_u = MongoRepository("repositories")
            users_repo = MongoRepository("users", unique_fields=["id"])
            
            user_engine = UserIngestionEngine(
                github_client=github_client,
                repos_repository=repos_repo_u,
                users_repository=users_repo,
                batch_size=request.batch_size,
                from_scratch=from_scratch,
                progress_callback=make_phase_progress_cb(2),
                cancel_event=cancel_event
            )
            stats = user_engine.run(max_repos=None)
            results.append({"phase": phase_names[2], "success": True, "stats": stats})
        except Exception as e:
            results.append({"phase": phase_names[2], "success": False, "error": str(e)})
            logger.error(f"Error en fase 3: {e}")
        
        # Fase 4: Enriquecimiento de Usuarios
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        _update_progress(operation_id, f"4/{total_phases} - {phase_names[3]}", 300, total_phases * 100)
        
        users_repo = MongoRepository("users")
        try:
            stats = UserEnrichmentEngine(
                github_token=github_token,
                users_repository=users_repo,
                repos_repository=repo_repo,
                batch_size=100,
                progress_callback=make_phase_progress_cb(3),
                cancel_event=cancel_event
            ).enrich_all_users(max_users=None, force_reenrich=request.force_reenrich)
            results.append({"phase": phase_names[3], "success": True, "stats": stats})
        except Exception as e:
            results.append({"phase": phase_names[3], "success": False, "error": str(e)})
            logger.error(f"Error en fase 4: {e}")
        
        # Fase 5: Ingesta de Organizaciones
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        _update_progress(operation_id, f"5/{total_phases} - {phase_names[4]} ({mode_label})", 400, total_phases * 100)
        
        orgs_repo = MongoRepository("organizations")
        try:
            stats = OrganizationIngestionEngine(
                github_token=github_token,
                users_repository=users_repo,
                organizations_repository=orgs_repo,
                batch_size=100,
                from_scratch=from_scratch,
                progress_callback=make_phase_progress_cb(4),
                cancel_event=cancel_event
            ).run(force_update=from_scratch)
            results.append({"phase": phase_names[4], "success": True, "stats": stats})
        except Exception as e:
            results.append({"phase": phase_names[4], "success": False, "error": str(e)})
            logger.error(f"Error en fase 5: {e}")
        
        # Fase 6: Enriquecimiento de Organizaciones
        if cancel_event.is_set():
            _finalize_operation(operation_id, "cancelled")
            return
        _update_progress(operation_id, f"6/{total_phases} - {phase_names[5]}", 500, total_phases * 100)
        
        try:
            stats = OrganizationEnrichmentEngine(
                github_token=github_token,
                organizations_repository=orgs_repo,
                repositories_repository=repo_repo,
                users_repository=users_repo,
                batch_size=100,
                progress_callback=make_phase_progress_cb(5),
                cancel_event=cancel_event
            ).enrich_all_organizations(max_orgs=None, force_reenrich=request.force_reenrich)
            results.append({"phase": phase_names[5], "success": True, "stats": stats})
        except Exception as e:
            results.append({"phase": phase_names[5], "success": False, "error": str(e)})
            logger.error(f"Error en fase 6: {e}")
        
        # Resultado final
        successful = sum(1 for r in results if r["success"])
        pipeline_stats = {
            "total_phases": total_phases,
            "successful": successful,
            "failed": total_phases - successful,
            "phases": results
        }
        
        if successful == total_phases:
            _finalize_operation(operation_id, "completed", stats=pipeline_stats)
        elif successful > 0:
            _finalize_operation(operation_id, "completed_with_errors", stats=pipeline_stats)
        else:
            _finalize_operation(operation_id, "failed", stats=pipeline_stats, error="Todas las fases fallaron")
    
    except Exception as e:
        logger.error(f"❌ Error crítico en pipeline {operation_id}: {e}")
        _finalize_operation(operation_id, "failed", error=str(e))
