"""
Tests para filtros y operaciones de repositorios.
Tests unitarios con mocks - NO requieren servicios externos.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone
from pymongo.errors import OperationFailure

from src.github.filters import RepositoryFilters
from src.models.repository import Repository
from src.github.repositories_ingestion import IngestionEngine


class TestRepositoryFilters:
    """Tests para los filtros de repositorios."""
    
    def test_is_active_with_recent_update(self):
        """Verifica que repositorios activos pasen el filtro."""
        repo = {
            "nameWithOwner": "user/repo",
            "updatedAt": datetime.now(timezone.utc).isoformat()
        }
        
        assert RepositoryFilters.is_active(repo, max_inactivity_days=365) is True
    
    def test_is_active_with_old_update(self):
        """Verifica que repositorios inactivos sean rechazados."""
        old_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
        repo = {
            "nameWithOwner": "user/repo",
            "updatedAt": old_date.isoformat()
        }
        
        assert RepositoryFilters.is_active(repo, max_inactivity_days=365) is False
    
    def test_is_active_without_date(self):
        """Verifica que repos sin fecha sean rechazados."""
        repo = {
            "nameWithOwner": "user/repo"
        }
        
        assert RepositoryFilters.is_active(repo) is False
    
    def test_is_valid_fork_non_fork(self):
        """Verifica que repos que no son forks pasen."""
        repo = {
            "isFork": False
        }
        
        assert RepositoryFilters.is_valid_fork(repo) is True
    
    def test_has_minimum_stars_passes(self):
        """Verifica el filtro de estrellas mínimas."""
        repo = {
            "stargazerCount": 50
        }
        
        assert RepositoryFilters.has_minimum_stars(repo, min_stars=10) is True
    
    def test_has_minimum_stars_fails(self):
        """Verifica que repos con pocas estrellas sean rechazados."""
        repo = {
            "stargazerCount": 5
        }
        
        assert RepositoryFilters.has_minimum_stars(repo, min_stars=10) is False


class TestRepositoryModel:
    """Tests para el modelo Pydantic de Repository."""
    
    def test_repository_model_validation_success(self):
        """Verifica la validación exitosa del modelo."""
        data = {
            "id": "R_12345",
            "name": "test-repo",
            "nameWithOwner": "user/test-repo",
            "description": "A test repository",
            "url": "https://github.com/user/test-repo",
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
            "pushedAt": datetime.now(timezone.utc)
        }
        
        repo = Repository(**data)
        
        assert repo.id == "R_12345"
        assert repo.name == "test-repo"
        assert repo.name_with_owner == "user/test-repo"

class TestRepositoryIngestionThrottling:
    """Tests para el mecanismo de throttling de Cosmos DB en IngestionEngine."""
    
    @patch('src.github.repositories_ingestion.MongoRepository')
    @patch('src.github.repositories_ingestion.GitHubGraphQLClient')
    @patch('src.github.repositories_ingestion.db')
    def test_retry_on_cosmos_throttle_success(self, mock_db, mock_graphql_class, mock_repo_class):
        """Verifica que _retry_on_cosmos_throttle ejecute la operacion exitosamente."""
        mock_db.is_connected.return_value = True
        mock_graphql_instance = MagicMock()
        mock_graphql_class.return_value = mock_graphql_instance
        
        engine = IngestionEngine(
            client=mock_graphql_instance,
            incremental=False,
            batch_size=10
        )
        
        # Operacion exitosa
        operation = Mock(return_value={"success": True})
        result = engine._retry_on_cosmos_throttle(operation)
        
        assert result == {"success": True}
        assert operation.call_count == 1
    
    @pytest.mark.skip(reason="DEPRECATED: vCore no tiene throttling code 16500, _retry_on_cosmos_throttle ya no reintenta")
    @patch('src.github.repositories_ingestion.MongoRepository')
    @patch('src.github.repositories_ingestion.GitHubGraphQLClient')
    @patch('src.github.repositories_ingestion.db')
    @patch('time.sleep', return_value=None)  # Mock sleep para acelerar tests
    def test_retry_on_cosmos_throttle_with_429(self, mock_sleep, mock_db, mock_graphql_class, mock_repo_class):
        """Verifica que _retry_on_cosmos_throttle reintente tras error 429."""
        mock_db.is_connected.return_value = True
        mock_graphql_instance = MagicMock()
        mock_graphql_class.return_value = mock_graphql_instance
        
        engine = IngestionEngine(
            client=mock_graphql_instance,
            incremental=False,
            batch_size=10
        )
        
        # Primera llamada falla con 429, segunda tiene exito
        operation = Mock(
            side_effect=[
                OperationFailure(
                    "Request rate is large, RetryAfterMs=1000, Details='...'",
                    code=16500
                ),
                {"success": True}
            ]
        )
        
        result = engine._retry_on_cosmos_throttle(operation)
        
        assert result == {"success": True}
        assert operation.call_count == 2
        assert mock_sleep.call_count == 1  # Debe haber dormido una vez
    
    @pytest.mark.skip(reason="DEPRECATED: vCore no tiene throttling code 16500, _retry_on_cosmos_throttle ya no reintenta")
    @patch('src.github.repositories_ingestion.MongoRepository')
    @patch('src.github.repositories_ingestion.GitHubGraphQLClient')
    @patch('src.github.repositories_ingestion.db')
    @patch('time.sleep', return_value=None)
    def test_retry_on_cosmos_throttle_max_retries(self, mock_sleep, mock_db, mock_graphql_class, mock_repo_class):
        """Verifica que _retry_on_cosmos_throttle se rinda tras max_retries."""
        mock_db.is_connected.return_value = True
        mock_graphql_instance = MagicMock()
        mock_graphql_class.return_value = mock_graphql_instance
        
        engine = IngestionEngine(
            client=mock_graphql_instance,
            incremental=False,
            batch_size=10
        )
        
        # Siempre falla con 429
        operation = Mock(
            side_effect=OperationFailure(
                "Request rate is large, RetryAfterMs=500, Details='...'",
                code=16500
            )
        )
        
        result = engine._retry_on_cosmos_throttle(operation, max_retries=3)
        
        assert result is None  # Degradacion graciosa
        assert operation.call_count == 3
        assert mock_sleep.call_count == 2  # max_retries - 1
    
    @patch('src.github.repositories_ingestion.MongoRepository')
    @patch('src.github.repositories_ingestion.GitHubGraphQLClient')
    @patch('src.github.repositories_ingestion.db')
    def test_retry_on_cosmos_throttle_other_error(self, mock_db, mock_graphql_class, mock_repo_class):
        """Verifica que otros errores (no 429) se propaguen."""
        mock_db.is_connected.return_value = True
        mock_graphql_instance = MagicMock()
        mock_graphql_class.return_value = mock_graphql_instance
        
        engine = IngestionEngine(
            client=mock_graphql_instance,
            incremental=False,
            batch_size=10
        )
        
        # Error diferente (no throttling)
        operation = Mock(
            side_effect=OperationFailure("Different error", code=99999)
        )
        
        # Debe propagarse el error
        with pytest.raises(OperationFailure):
            engine._retry_on_cosmos_throttle(operation)


class TestRepositoryModel2:
    """Tests adicionales para el modelo Repository."""
    
    def test_repository_model_with_minimal_data(self):
        """Verifica que el modelo funcione con datos minimos."""
        data = {
            "id": "R_12345",
            "name": "test-repo",
            "nameWithOwner": "user/test-repo",
            "url": "https://github.com/user/test-repo"
        }
        
        repo = Repository(**data)
        
        assert repo.id == "R_12345"
        assert repo.name == "test-repo"
    
    def test_repository_model_to_dict(self):
        """Verifica que el modelo pueda convertirse a diccionario."""
        data = {
            "id": "R_12345",
            "name": "test-repo",
            "nameWithOwner": "user/test-repo",
            "url": "https://github.com/user/test-repo"
        }
        
        repo = Repository(**data)
        repo_dict = repo.model_dump()  # Pydantic v2 usa model_dump()
        
        assert isinstance(repo_dict, dict)
        assert repo_dict["id"] == "R_12345"
        assert repo_dict["name"] == "test-repo"    
    def test_repository_model_with_minimal_data(self):
        """Verifica que el modelo funcione con datos mínimos."""
        data = {
            "id": "R_12345",
            "name": "test-repo",
            "nameWithOwner": "user/test-repo",
            "url": "https://github.com/user/test-repo"
        }
        
        repo = Repository(**data)
        
        assert repo.id == "R_12345"
        assert repo.stargazer_count == 0  # Valor por defecto
        assert repo.fork_count == 0  # Valor por defecto
    
    def test_repository_model_to_dict(self):
        """Verifica la conversion a diccionario."""
        data = {
            "id": "R_12345",
            "name": "test-repo",
            "nameWithOwner": "user/test-repo",
            "url": "https://github.com/user/test-repo"
        }
        
        repo = Repository(**data)
        repo_dict = repo.model_dump()  # Pydantic v2 usa model_dump()
        
        assert isinstance(repo_dict, dict)
        assert repo_dict["id"] == "R_12345"
        assert "ingested_at" in repo_dict or "ingestedAt" in repo_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
