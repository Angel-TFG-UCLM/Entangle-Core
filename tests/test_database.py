"""
Tests para la base de datos MongoDB y operaciones de persistencia.
Incluye tests para conexiones, CRUD y operaciones bulk.
"""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from src.core.db import Database
from src.core.config import config
from src.core.mongo_repository import MongoRepository


class TestDatabase:
    """Tests para la clase Database."""
    
    @patch('src.core.db.MongoClient')
    def test_database_connection_success(self, mock_mongo_client):
        """Test de conexión exitosa a MongoDB."""
        # Mock del cliente MongoDB
        mock_client_instance = Mock()
        mock_client_instance.admin.command = Mock(return_value={"ok": 1})
        mock_db_instance = Mock()
        mock_client_instance.__getitem__ = Mock(return_value=mock_db_instance)
        mock_mongo_client.return_value = mock_client_instance
        
        db = Database()
        db.connect()
        
        # Verificar que se creó la conexión
        assert mock_mongo_client.call_count == 1
        
        # Verificar que se ejecutó ping
        mock_client_instance.admin.command.assert_called_once_with('ping')
        
        # Verificar que se asignó la base de datos
        assert db.db is not None
        assert db.client is not None
        assert db.is_connected() is True
    
    @patch('src.core.db.MongoClient')
    def test_database_connection_failure(self, mock_mongo_client):
        """Test de fallo en la conexión a MongoDB."""
        from pymongo.errors import ConnectionFailure
        
        # Mock que lanza excepción
        mock_mongo_client.side_effect = ConnectionFailure("Connection failed")
        
        db = Database()
        
        with pytest.raises(ConnectionFailure):
            db.connect()
    
    @patch('src.core.db.MongoClient')
    def test_database_disconnect(self, mock_mongo_client):
        """Test de desconexión de MongoDB."""
        mock_client_instance = Mock()
        mock_client_instance.admin.command = Mock(return_value={"ok": 1})
        mock_db_instance = Mock()
        mock_client_instance.__getitem__ = Mock(return_value=mock_db_instance)
        mock_mongo_client.return_value = mock_client_instance
        
        db = Database()
        db.connect()
        db.disconnect()
        
        # Verificar que se cerró la conexión
        mock_client_instance.close.assert_called_once()
    
    @patch('src.core.db.MongoClient')
    def test_get_collection(self, mock_mongo_client):
        """Test de obtención de colección."""
        mock_client_instance = Mock()
        mock_client_instance.admin.command = Mock(return_value={"ok": 1})
        mock_db_instance = MagicMock()
        mock_client_instance.__getitem__ = Mock(return_value=mock_db_instance)
        mock_mongo_client.return_value = mock_client_instance
        
        db = Database()
        db.connect()
        
        collection_name = "test_collection"
        collection = db.get_collection(collection_name)
        
        # Verificar que se accedió a la colección correcta
        assert collection is not None
    
    @patch('src.core.db.MongoClient')
    def test_get_collection_without_connection(self, mock_mongo_client):
        """Test de obtención de colección sin conexión."""
        db = Database()
        
        with pytest.raises(Exception) as exc_info:
            db.get_collection("test_collection")
        
        assert "Base de datos no conectada" in str(exc_info.value)
    
    @patch('src.core.db.MongoClient')
    def test_context_manager(self, mock_mongo_client):
        """Test del uso como context manager."""
        mock_client_instance = Mock()
        mock_client_instance.admin.command = Mock(return_value={"ok": 1})
        mock_db_instance = Mock()
        mock_client_instance.__getitem__ = Mock(return_value=mock_db_instance)
        mock_mongo_client.return_value = mock_client_instance
        
        with Database() as db:
            assert db.client is not None
            assert db.db is not None
        
        # Verificar que se cerró la conexión al salir del context
        mock_client_instance.close.assert_called_once()
    
    @patch('src.core.db.MongoClient')
    def test_is_connected(self, mock_mongo_client):
        """Test de verificación de conexión activa."""
        mock_client_instance = Mock()
        mock_client_instance.admin.command = Mock(return_value={"ok": 1})
        mock_db_instance = Mock()
        mock_client_instance.__getitem__ = Mock(return_value=mock_db_instance)
        mock_mongo_client.return_value = mock_client_instance
        
        db = Database()
        assert db.is_connected() is False
        
        db.connect()
        assert db.is_connected() is True
        
        db.disconnect()
        assert db.is_connected() is False


class TestMongoRepository:
    """Tests para la clase MongoRepository."""
    
    @pytest.fixture
    def mock_collection(self):
        """Fixture que crea una colección mock."""
        return MagicMock()
    
    @pytest.fixture
    def repository(self, mock_collection):
        """Fixture que crea un repositorio con colección mock."""
        with patch('src.core.mongo_repository.get_collection', return_value=mock_collection):
            repo = MongoRepository("test_collection", unique_fields=["id", "login"])
            return repo
    
    def test_repository_initialization(self, repository):
        """Test de inicialización del repositorio."""
        assert repository.collection_name == "test_collection"
        assert repository.unique_fields == ["id", "login"]
    
    def test_insert_one_success(self, repository, mock_collection):
        """Test de inserción exitosa de un documento."""
        # Mock del resultado
        mock_result = Mock()
        mock_result.inserted_id = "507f1f77bcf86cd799439011"
        mock_collection.insert_one.return_value = mock_result
        mock_collection.find_one.return_value = None  # No duplicado
        
        document = {"id": "repo123", "name": "Test Repo", "stars": 100}
        result = repository.insert_one(document, check_duplicates=True)
        
        assert result == "507f1f77bcf86cd799439011"
        mock_collection.insert_one.assert_called_once()
    
    def test_insert_one_duplicate(self, repository, mock_collection):
        """Test de inserción de documento duplicado."""
        # Mock que indica que existe duplicado
        mock_collection.find_one.return_value = {"_id": "existing_id"}
        
        document = {"id": "repo123", "name": "Test Repo"}
        result = repository.insert_one(document, check_duplicates=True)
        
        # No debe insertar
        assert result is None
        mock_collection.insert_one.assert_not_called()
    
    def test_insert_many_success(self, repository, mock_collection):
        """Test de inserción múltiple exitosa."""
        # Mock del resultado
        mock_result = Mock()
        mock_result.inserted_ids = ["id1", "id2", "id3"]
        mock_collection.insert_many.return_value = mock_result
        mock_collection.find_one.return_value = None  # No duplicados
        
        documents = [
            {"id": f"repo{i}", "name": f"Repo {i}"} 
            for i in range(1, 4)
        ]
        result = repository.insert_many(documents, check_duplicates=True)
        
        assert result["inserted_count"] == 3
        assert result["duplicate_count"] == 0
        assert len(result["inserted_ids"]) == 3
    
    def test_find_one_success(self, repository, mock_collection):
        """Test de búsqueda exitosa de un documento."""
        expected_doc = {"_id": "123", "id": "repo123", "name": "Test"}
        mock_collection.find_one.return_value = expected_doc
        
        result = repository.find_one({"id": "repo123"})
        
        assert result == expected_doc
        mock_collection.find_one.assert_called_once_with({"id": "repo123"}, None)
    
    def test_find_multiple_documents(self, repository, mock_collection):
        """Test de búsqueda de múltiples documentos."""
        expected_docs = [
            {"id": "repo1", "name": "Repo 1"},
            {"id": "repo2", "name": "Repo 2"}
        ]
        
        # Mock del cursor
        mock_cursor = MagicMock()
        mock_cursor.__iter__.return_value = iter(expected_docs)
        mock_collection.find.return_value = mock_cursor
        
        result = repository.find({"stars": {"$gt": 100}})
        
        assert len(result) == 2
        mock_collection.find.assert_called_once()
    
    def test_count_documents(self, repository, mock_collection):
        """Test de conteo de documentos."""
        mock_collection.count_documents.return_value = 42
        
        count = repository.count_documents({"stars": {"$gt": 100}})
        
        assert count == 42
        mock_collection.count_documents.assert_called_once_with({"stars": {"$gt": 100}})
    
    def test_update_one_success(self, repository, mock_collection):
        """Test de actualización exitosa."""
        mock_result = Mock()
        mock_result.matched_count = 1
        mock_result.modified_count = 1
        mock_result.upserted_id = None
        mock_collection.update_one.return_value = mock_result
        
        result = repository.update_one(
            {"id": "repo123"},
            {"name": "Updated Name"},
            upsert=False
        )
        
        assert result["matched_count"] == 1
        assert result["modified_count"] == 1
        mock_collection.update_one.assert_called_once()
    
    def test_upsert_one_insert(self, repository, mock_collection):
        """Test de upsert que resulta en inserción."""
        mock_result = Mock()
        mock_result.matched_count = 0
        mock_result.modified_count = 0
        mock_result.upserted_id = "new_id_123"
        mock_collection.update_one.return_value = mock_result
        
        document = {"id": "repo123", "name": "New Repo"}
        result = repository.upsert_one({"id": "repo123"}, document)
        
        assert result["operation"] == "insert"
        assert result["upserted_id"] == "new_id_123"
    
    def test_upsert_one_update(self, repository, mock_collection):
        """Test de upsert que resulta en actualización."""
        mock_result = Mock()
        mock_result.matched_count = 1
        mock_result.modified_count = 1
        mock_result.upserted_id = None
        mock_collection.update_one.return_value = mock_result
        
        document = {"id": "repo123", "name": "Updated Repo"}
        result = repository.upsert_one({"id": "repo123"}, document)
        
        assert result["operation"] == "update"
        assert result["upserted_id"] is None
    
    def test_delete_one_success(self, repository, mock_collection):
        """Test de eliminación exitosa."""
        mock_result = Mock()
        mock_result.deleted_count = 1
        mock_collection.delete_one.return_value = mock_result
        
        count = repository.delete_one({"id": "repo123"})
        
        assert count == 1
        mock_collection.delete_one.assert_called_once_with({"id": "repo123"})
    
    def test_delete_many_success(self, repository, mock_collection):
        """Test de eliminación múltiple."""
        mock_result = Mock()
        mock_result.deleted_count = 5
        mock_collection.delete_many.return_value = mock_result
        
        count = repository.delete_many({"stars": {"$lt": 10}})
        
        assert count == 5
        mock_collection.delete_many.assert_called_once()
    
    def test_to_dict_with_pydantic_model(self, repository):
        """Test de conversión de modelo Pydantic a dict."""
        from src.models import Repository
        
        # Crear modelo Pydantic con campos requeridos
        repo = Repository(
            id="repo123",
            name="Test Repo",
            full_name="owner/test-repo",
            nameWithOwner="owner/test-repo",
            url="https://github.com/owner/test-repo"
        )
        
        # Convertir a dict
        result = repository._to_dict(repo)
        
        assert isinstance(result, dict)
        # El método to_mongo_dict() usa _id en lugar de id
        assert result.get("_id") == "repo123" or result.get("id") == "repo123"
        assert result["name"] == "Test Repo"
    
    def test_to_dict_with_regular_dict(self, repository):
        """Test de conversión de dict regular."""
        doc = {"id": "repo123", "name": "Test"}
        result = repository._to_dict(doc)
        
        assert result == doc
    
    def test_is_duplicate_true(self, repository, mock_collection):
        """Test de detección de duplicado."""
        mock_collection.find_one.return_value = {"_id": "existing"}
        
        document = {"id": "repo123", "login": "owner"}
        result = repository._is_duplicate(document)
        
        assert result is True
    
    def test_is_duplicate_false(self, repository, mock_collection):
        """Test de no duplicado."""
        mock_collection.find_one.return_value = None
        
        document = {"id": "repo123", "login": "owner"}
        result = repository._is_duplicate(document)
        
        assert result is False


# Nota: Tests de integración real movidos a test suite de integración
# Los tests unitarios con mocks cubren toda la funcionalidad necesaria


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
