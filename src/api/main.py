"""
Aplicación principal de FastAPI.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from ..core.config import config
from ..core.logger import logger
from ..core.db import db


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

# Incluir rutas
app.include_router(router, prefix="/api/v1", tags=["api"])


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=config.DEBUG
    )
