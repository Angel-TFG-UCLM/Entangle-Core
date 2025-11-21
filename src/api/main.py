"""
Aplicación principal de FastAPI.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import router
from ..core.config import config
from ..core.logger import logger
from ..core.db import db


# Crear aplicación FastAPI
app = FastAPI(
    title="TFG Backend API",
    description="API para extraer y analizar datos de GitHub",
    version="1.0.0",
    debug=config.DEBUG
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, especificar dominios permitidos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir rutas
app.include_router(router, prefix="/api/v1", tags=["api"])


@app.on_event("startup")
async def startup_event():
    """Evento de inicio de la aplicación."""
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


@app.on_event("shutdown")
async def shutdown_event():
    """Evento de cierre de la aplicación."""
    logger.info("Cerrando aplicación...")
    
    try:
        # Desconectar de la base de datos
        db.disconnect()
        logger.info("Base de datos desconectada correctamente")
        
    except Exception as e:
        logger.error(f"Error durante el cierre: {e}")


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=config.DEBUG
    )
