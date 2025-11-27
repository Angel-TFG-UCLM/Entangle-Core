"""
Conexión a MongoDB.
Este módulo proporciona una clase Database para gestionar la conexión a MongoDB
y expone funciones auxiliares para obtener referencias a la base de datos y colecciones.
"""
from typing import Optional
from pymongo import MongoClient
from pymongo.database import Database as PyMongoDatabase
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from .config import config
from .logger import logger


class Database:
    """
    Clase para gestionar la conexión a MongoDB.
    
    Attributes:
        client: Cliente de MongoDB (MongoClient)
        db: Base de datos activa
    """
    
    def __init__(self):
        self.client: Optional[MongoClient] = None
        self.db: Optional[PyMongoDatabase] = None
        self._is_connected: bool = False
    
    def connect(self) -> None:
        """
        Establece la conexión a MongoDB.
        
        Raises:
            ConnectionFailure: Si no se puede conectar a MongoDB
            ServerSelectionTimeoutError: Si se agota el tiempo de espera
        """
        if self._is_connected:
            logger.warning("Ya existe una conexión activa a MongoDB")
            return
            
        try:
            logger.info(f"Conectando a MongoDB: {config.MONGO_URI}")
            self.client = MongoClient(
                config.MONGO_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=10000,
                socketTimeoutMS=10000,
                retryReads=True,
                retryWrites=True
            )
            
            # Verificar la conexión con ping
            self.client.admin.command('ping')
            
            self.db = self.client[config.MONGO_DB_NAME]
            self._is_connected = True
            
            logger.info(f"✅ Conexión exitosa a la base de datos: {config.MONGO_DB_NAME}")
            
        except ConnectionFailure as e:
            logger.error(f"❌ Error al conectar a MongoDB: {e}")
            self._is_connected = False
            raise
        except ServerSelectionTimeoutError as e:
            logger.error(f"❌ Timeout al conectar a MongoDB: {e}")
            self._is_connected = False
            raise
        except Exception as e:
            logger.error(f"❌ Error inesperado al conectar a MongoDB: {e}")
            self._is_connected = False
            raise
    
    def disconnect(self) -> None:
        """Cierra la conexión a MongoDB."""
        if self.client:
            self.client.close()
            self._is_connected = False
            logger.info("🔌 Conexión a MongoDB cerrada")
    
    def get_collection(self, collection_name: str) -> Collection:
        """
        Obtiene una colección de la base de datos.
        
        Args:
            collection_name: Nombre de la colección (repositories, organizations, users, relations)
            
        Returns:
            Collection: Colección de MongoDB
            
        Raises:
            Exception: Si la base de datos no está conectada
        """
        if self.db is None:
            raise Exception("Base de datos no conectada. Ejecuta connect() primero.")
        return self.db[collection_name]
    
    def is_connected(self) -> bool:
        """
        Verifica si la conexión está activa.
        
        Returns:
            bool: True si está conectado, False en caso contrario
        """
        return self._is_connected and self.client is not None
    
    def get_database(self) -> PyMongoDatabase:
        """
        Obtiene la referencia a la base de datos.
        
        Returns:
            Database: Instancia de la base de datos
            
        Raises:
            Exception: Si la base de datos no está conectada
        """
        if self.db is None:
            raise Exception("Base de datos no conectada. Ejecuta connect() primero.")
        return self.db
    
    def list_collections(self) -> list:
        """
        Lista todas las colecciones en la base de datos.
        
        Returns:
            list: Lista de nombres de colecciones
        """
        if not self.db:
            raise Exception("Base de datos no conectada. Ejecuta connect() primero.")
        return self.db.list_collection_names()
    
    def drop_collection(self, collection_name: str) -> None:
        """
        Elimina una colección completa. USAR CON PRECAUCIÓN.
        
        Args:
            collection_name: Nombre de la colección a eliminar
        """
        if not self.db:
            raise Exception("Base de datos no conectada. Ejecuta connect() primero.")
        self.db.drop_collection(collection_name)
        logger.warning(f"⚠️  Colección '{collection_name}' eliminada")
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


# Instancia global de la base de datos
db = Database()


def get_database() -> PyMongoDatabase:
    """
    Función auxiliar para obtener la base de datos.
    Conecta automáticamente si no está conectado.
    
    Returns:
        Database: Instancia de la base de datos MongoDB
    """
    if not db.is_connected():
        db.connect()
    return db.get_database()


def get_collection(collection_name: str) -> Collection:
    """
    Función auxiliar para obtener una colección.
    Conecta automáticamente si no está conectado.
    
    Args:
        collection_name: Nombre de la colección
        
    Returns:
        Collection: Colección de MongoDB
    """
    if not db.is_connected():
        db.connect()
    return db.get_collection(collection_name)
