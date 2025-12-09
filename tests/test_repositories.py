"""
Tests para filtros y operaciones de repositorios.
Tests unitarios con mocks - NO requieren servicios externos.
"""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone

from src.github.filters import RepositoryFilters
from src.models.repository import Repository


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
        """Verifica la conversión a diccionario."""
        data = {
            "id": "R_12345",
            "name": "test-repo",
            "nameWithOwner": "user/test-repo",
            "url": "https://github.com/user/test-repo"
        }
        
        repo = Repository(**data)
        repo_dict = repo.to_dict()
        
        assert isinstance(repo_dict, dict)
        assert repo_dict["id"] == "R_12345"
        assert "ingested_at" in repo_dict or "ingestedAt" in repo_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
