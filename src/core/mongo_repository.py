"""
Capa de persistencia genérica para MongoDB.
Proporciona operaciones CRUD reutilizables para todas las colecciones.
"""
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, UTC
from pymongo.collection import Collection
from pymongo.results import InsertOneResult, InsertManyResult, UpdateResult, DeleteResult
from pymongo.errors import DuplicateKeyError, PyMongoError
from pydantic import BaseModel

from .db import get_collection
from .logger import logger


class MongoRepository:
    """
    Repositorio genérico para operaciones CRUD en MongoDB.
    
    Esta clase proporciona métodos comunes para insertar, actualizar, buscar y eliminar
    documentos en cualquier colección de MongoDB, con integración automática de modelos Pydantic.
    
    Attributes:
        collection_name: Nombre de la colección en MongoDB
        collection: Referencia a la colección de MongoDB
        unique_fields: Campos que deben ser únicos en la colección
    """
    
    def __init__(self, collection_name: str, unique_fields: Optional[List[str]] = None):
        """
        Inicializa el repositorio para una colección específica.
        
        Args:
            collection_name: Nombre de la colección (repositories, organizations, users, relations)
            unique_fields: Lista de campos que deben ser únicos (ej: ["login", "id"])
        """
        self.collection_name = collection_name
        self.collection: Collection = get_collection(collection_name)
        self.unique_fields = unique_fields or []
        
        logger.info(f"MongoRepository inicializado para colección: {collection_name}")
        if self.unique_fields:
            logger.debug(f"Campos únicos configurados: {self.unique_fields}")
    
    # ==================== INSERT OPERATIONS ====================
    
    def insert_one(
        self,
        document: Union[Dict[str, Any], BaseModel],
        check_duplicates: bool = True
    ) -> Optional[str]:
        """
        Inserta un documento en la colección.
        
        Args:
            document: Documento a insertar (dict o modelo Pydantic)
            check_duplicates: Si True, verifica duplicados antes de insertar
            
        Returns:
            str: ID del documento insertado, None si es duplicado
            
        Raises:
            PyMongoError: Si ocurre un error en MongoDB
        """
        try:
            # Convertir modelo Pydantic a dict si es necesario
            doc_dict = self._to_dict(document)
            
            # Verificar duplicados si está habilitado
            if check_duplicates and self.unique_fields:
                if self._is_duplicate(doc_dict):
                    logger.warning(
                        f"⚠️  Documento duplicado en {self.collection_name}: "
                        f"{self._get_unique_identifier(doc_dict)}"
                    )
                    return None
            
            # Insertar documento
            result: InsertOneResult = self.collection.insert_one(doc_dict)
            inserted_id = str(result.inserted_id)
            
            logger.info(f"✅ Documento insertado en {self.collection_name}: {inserted_id}")
            return inserted_id
            
        except DuplicateKeyError as e:
            logger.warning(f"⚠️  Clave duplicada en {self.collection_name}: {e}")
            return None
        except PyMongoError as e:
            logger.error(f"❌ Error al insertar en {self.collection_name}: {e}")
            raise
    
    def insert_many(
        self,
        documents: List[Union[Dict[str, Any], BaseModel]],
        check_duplicates: bool = True,
        ordered: bool = False
    ) -> Dict[str, Any]:
        """
        Inserta múltiples documentos en la colección.
        
        Args:
            documents: Lista de documentos a insertar
            check_duplicates: Si True, verifica duplicados antes de insertar
            ordered: Si True, detiene la inserción al primer error
            
        Returns:
            dict: Estadísticas de la inserción (inserted_count, duplicate_count, inserted_ids)
        """
        if not documents:
            logger.warning(f"⚠️  Lista vacía para insert_many en {self.collection_name}")
            return {"inserted_count": 0, "duplicate_count": 0, "inserted_ids": []}
        
        try:
            # Convertir todos los documentos a dict
            docs_dict = [self._to_dict(doc) for doc in documents]
            
            # Filtrar duplicados si está habilitado
            duplicate_count = 0
            if check_duplicates and self.unique_fields:
                filtered_docs = []
                for doc in docs_dict:
                    if not self._is_duplicate(doc):
                        filtered_docs.append(doc)
                    else:
                        duplicate_count += 1
                docs_dict = filtered_docs
                
                if duplicate_count > 0:
                    logger.info(f"⚠️  {duplicate_count} documentos duplicados filtrados")
            
            # Insertar documentos
            if not docs_dict:
                logger.warning(f"⚠️  Todos los documentos eran duplicados en {self.collection_name}")
                return {"inserted_count": 0, "duplicate_count": duplicate_count, "inserted_ids": []}
            
            result: InsertManyResult = self.collection.insert_many(docs_dict, ordered=ordered)
            inserted_ids = [str(oid) for oid in result.inserted_ids]
            
            logger.info(
                f"✅ {len(inserted_ids)} documentos insertados en {self.collection_name} "
                f"({duplicate_count} duplicados omitidos)"
            )
            
            return {
                "inserted_count": len(inserted_ids),
                "duplicate_count": duplicate_count,
                "inserted_ids": inserted_ids
            }
            
        except PyMongoError as e:
            logger.error(f"❌ Error al insertar múltiples documentos en {self.collection_name}: {e}")
            raise
    
    # ==================== FIND OPERATIONS ====================
    
    def find_one(
        self,
        query: Dict[str, Any],
        projection: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Busca un documento que coincida con el query.
        
        Args:
            query: Filtro de búsqueda (ej: {"login": "qiskit"})
            projection: Campos a incluir/excluir (ej: {"_id": 0, "name": 1})
            
        Returns:
            dict: Documento encontrado o None
        """
        try:
            result = self.collection.find_one(query, projection)
            
            if result:
                logger.debug(f"🔍 Documento encontrado en {self.collection_name}")
            else:
                logger.debug(f"🔍 No se encontró documento en {self.collection_name} con query: {query}")
            
            return result
            
        except PyMongoError as e:
            logger.error(f"❌ Error en find_one en {self.collection_name}: {e}")
            raise
    
    def find(
        self,
        query: Dict[str, Any] = None,
        projection: Optional[Dict[str, Any]] = None,
        limit: int = 0,
        skip: int = 0,
        sort: Optional[List[tuple]] = None
    ) -> List[Dict[str, Any]]:
        """
        Busca múltiples documentos que coincidan con el query.
        
        Args:
            query: Filtro de búsqueda (None = todos los documentos)
            projection: Campos a incluir/excluir
            limit: Número máximo de documentos a retornar (0 = sin límite)
            skip: Número de documentos a omitir
            sort: Lista de tuplas (campo, dirección) para ordenar (ej: [("name", 1)])
            
        Returns:
            list: Lista de documentos encontrados
        """
        try:
            query = query or {}
            cursor = self.collection.find(query, projection)
            
            if skip > 0:
                cursor = cursor.skip(skip)
            if limit > 0:
                cursor = cursor.limit(limit)
            if sort:
                cursor = cursor.sort(sort)
            
            results = list(cursor)
            logger.debug(f"🔍 {len(results)} documentos encontrados en {self.collection_name}")
            
            return results
            
        except PyMongoError as e:
            logger.error(f"❌ Error en find en {self.collection_name}: {e}")
            raise
    
    def count_documents(self, query: Dict[str, Any] = None) -> int:
        """
        Cuenta documentos que coincidan con el query.
        
        Args:
            query: Filtro de búsqueda (None = todos)
            
        Returns:
            int: Número de documentos
        """
        try:
            query = query or {}
            count = self.collection.count_documents(query)
            logger.debug(f"📊 {count} documentos en {self.collection_name}")
            return count
            
        except PyMongoError as e:
            logger.error(f"❌ Error en count_documents en {self.collection_name}: {e}")
            raise
    
    # ==================== UPDATE OPERATIONS ====================
    
    def update_one(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        upsert: bool = False
    ) -> Dict[str, Any]:
        """
        Actualiza un documento que coincida con el query.
        
        Args:
            query: Filtro para encontrar el documento
            update: Operaciones de actualización (debe usar operadores $set, $inc, etc.)
            upsert: Si True, inserta el documento si no existe
            
        Returns:
            dict: Estadísticas de la actualización (matched_count, modified_count, upserted_id)
        """
        try:
            # Asegurar que update tenga operadores de MongoDB
            if not any(key.startswith('$') for key in update):
                update = {"$set": update}
            
            result: UpdateResult = self.collection.update_one(query, update, upsert=upsert)
            
            stats = {
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "upserted_id": str(result.upserted_id) if result.upserted_id else None
            }
            
            if result.upserted_id:
                logger.info(f"✅ Documento insertado (upsert) en {self.collection_name}: {stats['upserted_id']}")
            elif result.modified_count > 0:
                logger.info(f"✅ Documento actualizado en {self.collection_name}")
            else:
                logger.debug(f"ℹ️  No se modificó ningún documento en {self.collection_name}")
            
            return stats
            
        except PyMongoError as e:
            logger.error(f"❌ Error en update_one en {self.collection_name}: {e}")
            raise
    
    def update_many(
        self,
        query: Dict[str, Any],
        update: Dict[str, Any],
        upsert: bool = False
    ) -> Dict[str, Any]:
        """
        Actualiza múltiples documentos que coincidan con el query.
        
        Args:
            query: Filtro para encontrar documentos
            update: Operaciones de actualización
            upsert: Si True, inserta si no existen
            
        Returns:
            dict: Estadísticas de la actualización
        """
        try:
            # Asegurar que update tenga operadores
            if not any(key.startswith('$') for key in update):
                update = {"$set": update}
            
            result: UpdateResult = self.collection.update_many(query, update, upsert=upsert)
            
            stats = {
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "upserted_id": str(result.upserted_id) if result.upserted_id else None
            }
            
            logger.info(
                f"✅ {result.modified_count} documentos actualizados en {self.collection_name} "
                f"(matched: {result.matched_count})"
            )
            
            return stats
            
        except PyMongoError as e:
            logger.error(f"❌ Error en update_many en {self.collection_name}: {e}")
            raise
    
    def upsert_one(
        self,
        query: Dict[str, Any],
        document: Union[Dict[str, Any], BaseModel],
        update_timestamp: bool = True
    ) -> Dict[str, Any]:
        """
        Inserta o actualiza un documento (operación upsert).
        Útil para reingestas incrementales.
        
        Args:
            query: Filtro para encontrar el documento (ej: {"id": "repo123"})
            document: Documento completo a insertar o actualizar
            update_timestamp: Si True, actualiza el campo updated_at
            
        Returns:
            dict: Estadísticas de la operación
        """
        try:
            doc_dict = self._to_dict(document)
            
            # Agregar timestamp de actualización
            if update_timestamp:
                doc_dict["updated_at"] = datetime.now(UTC)
            
            # Usar $set para actualizar todo el documento
            update = {"$set": doc_dict}
            
            result: UpdateResult = self.collection.update_one(query, update, upsert=True)
            
            stats = {
                "matched_count": result.matched_count,
                "modified_count": result.modified_count,
                "upserted_id": str(result.upserted_id) if result.upserted_id else None,
                "operation": "insert" if result.upserted_id else "update"
            }
            
            if result.upserted_id:
                logger.info(f"✅ Documento insertado (upsert) en {self.collection_name}")
            else:
                logger.info(f"✅ Documento actualizado (upsert) en {self.collection_name}")
            
            return stats
            
        except PyMongoError as e:
            logger.error(f"❌ Error en upsert_one en {self.collection_name}: {e}")
            raise
    
    # ==================== DELETE OPERATIONS ====================
    
    def delete_one(self, query: Dict[str, Any]) -> int:
        """
        Elimina un documento que coincida con el query.
        
        Args:
            query: Filtro para encontrar el documento
            
        Returns:
            int: Número de documentos eliminados (0 o 1)
        """
        try:
            result: DeleteResult = self.collection.delete_one(query)
            
            if result.deleted_count > 0:
                logger.info(f"🗑️  Documento eliminado de {self.collection_name}")
            else:
                logger.debug(f"ℹ️  No se encontró documento para eliminar en {self.collection_name}")
            
            return result.deleted_count
            
        except PyMongoError as e:
            logger.error(f"❌ Error en delete_one en {self.collection_name}: {e}")
            raise
    
    def delete_many(self, query: Dict[str, Any]) -> int:
        """
        Elimina múltiples documentos que coincidan con el query.
        
        Args:
            query: Filtro para encontrar documentos
            
        Returns:
            int: Número de documentos eliminados
        """
        try:
            result: DeleteResult = self.collection.delete_many(query)
            
            logger.info(f"🗑️  {result.deleted_count} documentos eliminados de {self.collection_name}")
            
            return result.deleted_count
            
        except PyMongoError as e:
            logger.error(f"❌ Error en delete_many en {self.collection_name}: {e}")
            raise
    
    # ==================== BULK OPERATIONS ====================
    
    def bulk_upsert(
        self,
        documents: List[Union[Dict[str, Any], BaseModel]],
        unique_field: str = "id"
    ) -> Dict[str, Any]:
        """
        Realiza operaciones upsert masivas de forma eficiente.
        
        Args:
            documents: Lista de documentos a insertar o actualizar
            unique_field: Campo único para identificar documentos (default: "id")
            
        Returns:
            dict: Estadísticas de la operación (upserted, modified, errors)
        """
        if not documents:
            return {"upserted_count": 0, "modified_count": 0, "errors": []}
        
        try:
            from pymongo import UpdateOne
            
            # Preparar operaciones bulk
            operations = []
            for doc in documents:
                # Usar dict() en lugar de to_mongo_dict() para preservar el campo 'id'
                if isinstance(doc, BaseModel):
                    doc_dict = doc.dict(exclude_none=False) if hasattr(doc, 'dict') else doc.model_dump()
                else:
                    doc_dict = doc
                
                # Extraer el valor del campo único ANTES de agregar updated_at
                unique_value = doc_dict.get(unique_field)
                if unique_value is None:
                    logger.warning(f"⚠️ Documento sin campo '{unique_field}', se omite del bulk_upsert")
                    continue
                
                doc_dict["updated_at"] = datetime.now(UTC)
                
                # Crear operación de upsert con el campo único correcto
                query = {unique_field: unique_value}
                update = {"$set": doc_dict}
                operations.append(UpdateOne(query, update, upsert=True))
            
            # Ejecutar bulk write
            result = self.collection.bulk_write(operations, ordered=False)
            
            stats = {
                "upserted_count": result.upserted_count,
                "modified_count": result.modified_count,
                "matched_count": result.matched_count,
                "errors": []
            }
            
            logger.info(
                f"✅ Bulk upsert completado en {self.collection_name}: "
                f"{result.upserted_count} insertados, {result.modified_count} actualizados"
            )
            
            return stats
            
        except PyMongoError as e:
            logger.error(f"❌ Error en bulk_upsert en {self.collection_name}: {e}")
            raise
    
    # ==================== HELPER METHODS ====================
    
    def _to_dict(self, document: Union[Dict[str, Any], BaseModel]) -> Dict[str, Any]:
        """
        Convierte un documento a diccionario.
        
        Args:
            document: Documento (dict o modelo Pydantic)
            
        Returns:
            dict: Documento como diccionario
        """
        if isinstance(document, BaseModel):
            # Usar to_mongo_dict() si existe, sino dict()
            if hasattr(document, 'to_mongo_dict'):
                return document.to_mongo_dict()
            elif hasattr(document, 'dict'):
                return document.dict(exclude_none=False)
            else:
                return document.model_dump()
        return document
    
    def _is_duplicate(self, document: Dict[str, Any]) -> bool:
        """
        Verifica si un documento es duplicado basándose en unique_fields.
        
        Args:
            document: Documento a verificar
            
        Returns:
            bool: True si es duplicado
        """
        if not self.unique_fields:
            return False
        
        # Crear query con campos únicos
        query = {}
        for field in self.unique_fields:
            if field in document:
                query[field] = document[field]
        
        # Si no hay campos únicos en el documento, no es duplicado
        if not query:
            return False
        
        # Verificar existencia
        existing = self.collection.find_one(query, {"_id": 1})
        return existing is not None
    
    def _get_unique_identifier(self, document: Dict[str, Any]) -> str:
        """
        Obtiene un identificador único del documento para logging.
        
        Args:
            document: Documento
            
        Returns:
            str: Identificador único
        """
        for field in self.unique_fields:
            if field in document:
                return f"{field}={document[field]}"
        return str(document.get("_id", "unknown"))
    
    def create_indexes(self, indexes: List[Dict[str, Any]]) -> None:
        """
        Crea índices en la colección.
        
        Args:
            indexes: Lista de definiciones de índices
                    Ejemplo: [
                        {"keys": [("login", 1)], "unique": True},
                        {"keys": [("stars_count", -1)]}
                    ]
        """
        try:
            for index_spec in indexes:
                keys = index_spec.get("keys", [])
                options = {k: v for k, v in index_spec.items() if k != "keys"}
                
                self.collection.create_index(keys, **options)
                logger.info(f"✅ Índice creado en {self.collection_name}: {keys}")
                
        except PyMongoError as e:
            logger.error(f"❌ Error al crear índices en {self.collection_name}: {e}")
            raise
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas de la colección.
        
        Returns:
            dict: Estadísticas (count, indexes, size_mb, etc.)
        """
        try:
            stats = self.collection.database.command("collStats", self.collection_name)
            
            return {
                "collection": self.collection_name,
                "count": stats.get("count", 0),
                "size_mb": round(stats.get("size", 0) / (1024 * 1024), 2),
                "avg_doc_size_bytes": stats.get("avgObjSize", 0),
                "indexes": stats.get("nindexes", 0),
                "total_index_size_mb": round(stats.get("totalIndexSize", 0) / (1024 * 1024), 2)
            }
            
        except PyMongoError as e:
            logger.error(f"❌ Error al obtener estadísticas de {self.collection_name}: {e}")
            return {}
