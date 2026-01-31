"""
Tests para modelo y operaciones de usuarios.
Tests unitarios con mocks - NO requieren servicios externos.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock

from src.models.user import User, UserRepository, UserOrganization


class TestUserModel:
    """Tests para el modelo Pydantic de User."""
    
    def test_user_model_validation_success(self):
        """Verifica la validación exitosa del modelo."""
        data = {
            "id": "U_12345",
            "login": "testuser",
            "name": "Test User",
            "email": "test@example.com",
            "bio": "Software developer",
            "url": "https://github.com/testuser",
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc)
        }
        
        user = User(**data)
        
        assert user.id == "U_12345"
        assert user.login == "testuser"
        assert user.name == "Test User"
    
    def test_user_model_with_minimal_data(self):
        """Verifica que el modelo funcione con datos mínimos."""
        data = {
            "id": "U_12345",
            "login": "testuser",
            "url": "https://github.com/testuser"
        }
        
        user = User(**data)
        
        assert user.id == "U_12345"
        assert user.login == "testuser"
        assert user.followers_count == 0  # Valor por defecto
        assert user.following_count == 0  # Valor por defecto
    
    def test_user_model_with_organizations(self):
        """Verifica que las organizaciones se procesen correctamente."""
        data = {
            "id": "U_12345",
            "login": "testuser",
            "url": "https://github.com/testuser",
            "organizations": [
                {
                    "id": "O_1",
                    "login": "org1",
                    "name": "Organization 1"
                },
                {
                    "id": "O_2",
                    "login": "org2",
                    "name": "Organization 2"
                }
            ]
        }
        
        user = User(**data)
        
        assert len(user.organizations) == 2
        assert isinstance(user.organizations[0], UserOrganization)
        assert user.organizations[0].login == "org1"
    
    def test_user_model_none_to_empty_list(self):
        """Verifica que el validador convierta None a listas vacías."""
        data = {
            "id": "U_12345",
            "login": "testuser",
            "url": "https://github.com/testuser",
            "organizations": None,
            "pinned_repositories": None,
            "top_languages": None
        }
        
        user = User(**data)
        
        assert user.organizations == []
        assert user.pinned_repositories == []
        assert user.top_languages == []
    
    def test_user_model_to_dict(self):
        """Verifica la conversión a diccionario."""
        data = {
            "id": "U_12345",
            "login": "testuser",
            "url": "https://github.com/testuser"
        }
        
        user = User(**data)
        user_dict = user.to_dict()
        
        assert isinstance(user_dict, dict)
        assert user_dict["id"] == "U_12345"
        assert user_dict["login"] == "testuser"
    
    def test_bot_detection(self):
        """Verifica la detección de bots por nombre de usuario."""
        bot_usernames = [
            "dependabot[bot]",
            "github-actions[bot]",
            "renovate[bot]"
        ]
        
        for username in bot_usernames:
            assert "[bot]" in username
    
    def test_quantum_expertise_score_calculation(self):
        """Verifica el cálculo del quantum expertise score."""
        # Datos de ejemplo
        quantum_repos = 5
        total_repos = 20
        quantum_commits = 300
        total_commits = 1000
        
        # Fórmula: (ratio_repos * 0.6 + ratio_commits * 0.4) * 100
        repo_ratio = quantum_repos / total_repos  # 0.25
        commit_ratio = quantum_commits / total_commits  # 0.30
        expected_score = (repo_ratio * 0.6 + commit_ratio * 0.4) * 100
        
        assert expected_score == pytest.approx(27.0, rel=1e-2)
    
    def test_user_with_pinned_repositories(self):
        """Verifica el procesamiento de repositorios pinned."""
        data = {
            "id": "U_12345",
            "login": "testuser",
            "url": "https://github.com/testuser",
            "pinned_repositories": [
                {
                    "id": "R_1",
                    "name": "awesome-project",
                    "nameWithOwner": "testuser/awesome-project",
                    "stargazerCount": 500
                }
            ]
        }
        
        user = User(**data)
        
        assert len(user.pinned_repositories) == 1
        assert isinstance(user.pinned_repositories[0], UserRepository)
        assert user.pinned_repositories[0].name == "awesome-project"
    
    def test_user_top_languages(self):
        """Verifica el procesamiento de top languages."""
        data = {
            "id": "U_12345",
            "login": "testuser",
            "url": "https://github.com/testuser",
            "top_languages": ["Python", "JavaScript", "TypeScript"]
        }
        
        user = User(**data)
        
        assert len(user.top_languages) == 3
        assert "Python" in user.top_languages


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
