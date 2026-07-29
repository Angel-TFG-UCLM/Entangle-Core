"""
Aplicación principal de FastAPI.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .routes import router
from .admin_routes import admin_router
from .chat_routes import chat_router
from ..core.config import config
from ..core.logger import logger
from ..core.db import db


# Referencias fuertes a tasks de fondo (p.ej. el pre-warm del modelo). asyncio
# solo guarda referencias débiles a los tasks; sin esta colección el recolector
# de basura podría destruirlos antes de que terminen.
_background_tasks: set = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Eventos de ciclo de vida de la aplicación."""
    # Startup
    logger.info("Iniciando aplicación...")
    
    try:
        # Validar configuración
        config.validate()
        logger.info("Configuración validada correctamente")
        
        # Conectar a la base de datos
        db.connect()
        logger.info("Base de datos conectada correctamente")

        # Pre-warm is only meaningful for a configured remote provider.
        # de cold start en la primera petición real del usuario tras un
        # rato de inactividad. La llamada es mínima (1 token) y no bloquea
        # el arranque del servidor: corre en un task separado.
        import asyncio as _asyncio
        async def _warmup():
            try:
                from ..ai.agent import _api_call_with_retry, _build_api_url
                payload = {
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "temperature": 1,
                    "reasoning_effort": "minimal",
                }
                await _asyncio.get_event_loop().run_in_executor(
                    None, _api_call_with_retry, _build_api_url(), payload,
                )
                logger.info("🔥 Modelo gpt-5-mini pre-calentado")
            except Exception as exc:
                logger.warning(f"⚠️ Pre-warm del modelo falló (no bloqueante): {exc}")
        # Guardamos una referencia fuerte al task: asyncio solo mantiene
        # referencias débiles a los tasks, así que sin esto el GC podría
        # recolectarlo antes de que termine (ver docs de asyncio.create_task).
        if config.AI_PROVIDER not in {"offline", "disabled"}:
            task = _asyncio.create_task(_warmup())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
        
    except Exception as e:
        logger.error(f"Error durante el inicio: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Cerrando aplicación...")
    
    try:
        # Desconectar de la base de datos
        db.disconnect()
        logger.info("Base de datos desconectada correctamente")
        
    except Exception as e:
        logger.error(f"Error durante el cierre: {e}")


# Crear aplicación FastAPI
app = FastAPI(
    title="Entangle Backend API",
    description="API para extraer y analizar datos de GitHub - Computación Cuántica.",
    version="1.0.0",
    debug=config.DEBUG,
    lifespan=lifespan
)

# Configurar CORS dinámicamente
# Combina orígenes de desarrollo con los de producción desde variables de entorno
cors_origins = [
    "http://localhost:5173",      # Desarrollo local (Vite)
    "http://localhost:5174",      # Puerto alternativo Vite
    "http://localhost:3000",      # Alternativa desarrollo
    "http://127.0.0.1:5173",      # IP local
    "http://127.0.0.1:5174",      # IP local puerto alternativo
]

# Agregar URL del frontend desde variable de entorno (Azure Static Web Apps)
if config.FRONTEND_URL:
    cors_origins.append(config.FRONTEND_URL)
    logger.info(f"CORS habilitado para frontend: {config.FRONTEND_URL}")

# GZip: comprimir respuestas grandes (>1KB). Reduce ~22MB de JSON del grafo a ~2-3MB.
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS debe añadirse último para que se ejecute primero (LIFO)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Incluir rutas
app.include_router(router, prefix="/api/v1", tags=["api"])
app.include_router(admin_router, prefix="/api/v1", tags=["admin"])
app.include_router(chat_router, prefix="/api/v1", tags=["chat"])


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=config.DEBUG
    )
