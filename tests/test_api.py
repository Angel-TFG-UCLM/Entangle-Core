"""
Tests para la API REST del backend.
Prueba todos los endpoints principales de la API usando TestClient de FastAPI.
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from typing import Dict, Any
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Agregar el directorio raíz al path para importar módulos
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.main import app


@pytest.fixture
def client():
    """Fixture que proporciona un cliente de prueba para la API."""
    return TestClient(app)


@pytest.fixture
def mock_db():
    """Mock de la base de datos para tests de API."""
    mock_collection = MagicMock()
    
    # Mock de datos
    sample_repos = [
        {
            "_id": "507f1f77bcf86cd799439011",
            "full_name": "user/repo1",
            "description": "Test repo 1",
            "stars": 100,
            "primary_language": {"name": "Python"},
            "stargazer_count": 100
        },
        {
            "_id": "507f1f77bcf86cd799439012",
            "full_name": "user/repo2",
            "description": "Test repo 2",
            "stars": 200,
            "primary_language": {"name": "JavaScript"},
            "stargazer_count": 200
        }
    ]
    
    sample_users = [
        {
            "_id": "507f1f77bcf86cd799439021",
            "login": "testuser1",
            "type": "User"
        },
        {
            "_id": "507f1f77bcf86cd799439022",
            "login": "testuser2",
            "type": "User"
        }
    ]
    
    sample_orgs = [
        {
            "_id": "507f1f77bcf86cd799439031",
            "login": "testorg1",
            "description": "Test organization 1"
        },
        {
            "_id": "507f1f77bcf86cd799439032",
            "login": "testorg2",
            "description": "Test organization 2"
        }
    ]
    
    # Configurar el mock para diferentes colecciones
    def mock_find(query=None):
        mock_cursor = MagicMock()
        
        # Determinar qué datos devolver según la colección actual
        if hasattr(mock_collection, '_current_collection'):
            if mock_collection._current_collection == 'repositories':
                data = sample_repos
            elif mock_collection._current_collection == 'users':
                data = sample_users
            elif mock_collection._current_collection == 'organizations':
                data = sample_orgs
            else:
                data = []
        else:
            data = []
        
        # Aplicar filtros si existen
        if query:
            if "primary_language.name" in query:
                data = [r for r in data if r.get("primary_language", {}).get("name") == query["primary_language.name"]]
            if "stargazer_count" in query:
                min_stars = query["stargazer_count"].get("$gte", 0)
                data = [r for r in data if r.get("stargazer_count", 0) >= min_stars]
        
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = data
        return mock_cursor
    
    def mock_find_one(query=None):
        if not query:
            return None
        
        # Determinar qué datos devolver según la colección actual
        if hasattr(mock_collection, '_current_collection'):
            if mock_collection._current_collection == 'repositories':
                return sample_repos[0]
            elif mock_collection._current_collection == 'users':
                return sample_users[0]
            elif mock_collection._current_collection == 'organizations':
                return sample_orgs[0]
        return None
    
    mock_collection.find.side_effect = mock_find
    mock_collection.find_one.side_effect = mock_find_one
    
    return mock_collection


class TestHealthEndpoints:
    """Tests para endpoints de health y status."""
    
    def test_health_check(self, client):
        """Verifica que el endpoint de health responda correctamente."""
        response = client.get("/api/v1/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
    
    def test_rate_limit_info(self, client):
        """Verifica que el endpoint de rate limit devuelva información correcta."""
        response = client.get("/api/v1/rate-limit")
        
        assert response.status_code == 200
        data = response.json()
        assert "remaining" in data
        assert "limit" in data
        assert "resetAt" in data
        assert isinstance(data["remaining"], int)
        assert isinstance(data["limit"], int)


class TestRepositoryEndpoints:
    """Tests para endpoints de repositorios."""
    
    @patch('src.core.db.db')
    def test_list_repositories(self, mock_db_instance, client, mock_db):
        """Verifica que se puedan listar repositorios."""
        mock_db._current_collection = 'repositories'
        mock_db_instance.get_collection.return_value = mock_db
        
        response = client.get("/api/v1/repositories")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        repo = data[0]
        assert "full_name" in repo
        assert "description" in repo
    
    @patch('src.core.db.db')
    def test_get_repository_by_id(self, mock_db_instance, client, mock_db):
        """Verifica que se pueda obtener un repositorio específico."""
        mock_db._current_collection = 'repositories'
        mock_db_instance.get_collection.return_value = mock_db
        
        repo_id = "507f1f77bcf86cd799439011"
        response = client.get(f"/api/v1/repositories/db/{repo_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert "_id" in data
        assert "full_name" in data


class TestUserEndpoints:
    """Tests para endpoints de usuarios."""
    
    @patch('src.core.db.db')
    def test_list_users(self, mock_db_module, client, mock_db):
        """Verifica que se puedan listar usuarios."""
        mock_db._current_collection = 'users'
        mock_db_module.get_collection.return_value = mock_db
        
        response = client.get("/api/v1/users")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        user = data[0]
        assert "login" in user
        assert "type" in user
    
    @patch('src.core.db.db')
    def test_get_user_by_id(self, mock_db_instance, client, mock_db):
        """Verifica que se pueda obtener un usuario específico."""
        mock_db._current_collection = 'users'
        mock_db_instance.get_collection.return_value = mock_db
        
        user_id = "507f1f77bcf86cd799439021"
        response = client.get(f"/api/v1/users/db/{user_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert "_id" in data
        assert "login" in data


class TestOrganizationEndpoints:
    """Tests para endpoints de organizaciones."""
    
    @patch('src.core.db.db')
    def test_list_organizations(self, mock_db_module, client, mock_db):
        """Verifica que se puedan listar organizaciones."""
        mock_db._current_collection = 'organizations'
        mock_db_module.get_collection.return_value = mock_db
        
        response = client.get("/api/v1/organizations")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        
        org = data[0]
        assert "login" in org
    
    @patch('src.core.db.db')
    def test_get_organization_by_id(self, mock_db_instance, client, mock_db):
        """Verifica que se pueda obtener una organización específica."""
        mock_db._current_collection = 'organizations'
        mock_db_instance.get_collection.return_value = mock_db
        
        org_id = "507f1f77bcf86cd799439031"
        response = client.get(f"/api/v1/organizations/db/{org_id}")
        
        assert response.status_code == 200
        data = response.json()
        assert "_id" in data
        assert "login" in data


class TestFilterEndpoints:
    """Tests para endpoints con filtros y búsqueda."""
    
    @patch('src.core.db.db')
    def test_filter_repositories_by_language(self, mock_db_module, client, mock_db):
        """Verifica que se puedan filtrar repositorios por lenguaje."""
        mock_db._current_collection = 'repositories'
        mock_db_module.get_collection.return_value = mock_db
        
        response = client.get(
            "/api/v1/repositories",
            params={"language": "Python"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    @patch('src.core.db.db')
    def test_filter_repositories_by_min_stars(self, mock_db_module, client, mock_db):
        """Verifica que se puedan filtrar repositorios por estrellas mínimas."""
        mock_db._current_collection = 'repositories'
        mock_db_module.get_collection.return_value = mock_db
        
        min_stars = 10
        response = client.get(
            "/api/v1/repositories",
            params={"min_stars": min_stars}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    @patch('src.core.db.db')
    def test_pagination(self, mock_db_module, client, mock_db):
        """Verifica que la paginación funcione correctamente."""
        mock_db._current_collection = 'repositories'
        mock_db_module.get_collection.return_value = mock_db
        
        # Primera página
        response1 = client.get(
            "/api/v1/repositories",
            params={"limit": 5, "skip": 0}
        )
        
        # Segunda página
        response2 = client.get(
            "/api/v1/repositories",
            params={"limit": 5, "skip": 5}
        )
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        data1 = response1.json()
        data2 = response2.json()
        
        assert isinstance(data1, list)
        assert isinstance(data2, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
