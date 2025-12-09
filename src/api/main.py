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
    title="TFG Backend API",
    description="API para extraer y analizar datos de GitHub",
    version="2.0.0",
    debug=config.DEBUG,
    lifespan=lifespan
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # IMPORTANTEEEE En producción, especificar dominios permitidos
    allow_credentials=True,
    allow_methods=["*"],
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
