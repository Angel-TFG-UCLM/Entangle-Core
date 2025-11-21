"""
Módulo core del proyecto.
Contiene la configuración, logging, conexión a la base de datos y capa de persistencia.
"""

from .config import config, Config, IngestionConfig
from .logger import logger, setup_logger
from .db import Database, db, get_database, get_collection
from .mongo_repository import MongoRepository

__all__ = [
    # Configuración
    "config",
    "Config",
    "IngestionConfig",
    
    # Logging
    "logger",
    "setup_logger",
    
    # Base de datos
    "Database",
    "db",
    "get_database",
    "get_collection",
    
    # Repositorio MongoDB
    "MongoRepository",
]
