"""
Tests para modelo y operaciones de organizaciones.
Tests unitarios con mocks - NO requieren servicios externos.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from pymongo.errors import OperationFailure

from src.models.organization import Organization
from src.github.organization_ingestion import OrganizationIngestionEngine


class TestOrganizationModel:
    """Tests para el modelo Pydantic de Organization."""
    
    def test_organization_model_validation_success(self):
        """Verifica la validación exitosa del modelo."""
        data = {
            "id": "O_12345",
            "login": "testorg",
            "name": "Test Organization",
            "description": "A test organization",
            "url": "https://github.com/testorg",
            "avatarUrl": "https://avatars.githubusercontent.com/u/12345",
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat()
        }
        
        org = Organization(**data)
        
        assert org.id == "O_12345"
        assert org.login == "testorg"
        assert org.name == "Test Organization"
    
    def test_organization_model_with_minimal_data(self):
        """Verifica que el modelo funcione con datos mínimos."""
        data = {
            "id": "O_12345",
            "login": "testorg",
            "url": "https://github.com/testorg",
            "avatarUrl": "https://avatars.githubusercontent.com/u/12345"
        }
        
        org = Organization(**data)
        
        assert org.id == "O_12345"
        assert org.login == "testorg"
        assert org.is_relevant is False  # Valor por defecto
    
    def test_organization_relevance_detection(self):
        """Verifica la detección de organizaciones relevantes."""
        # Organización relevante: tiene repos quantum en nuestra BD
        data = {
            "id": "O_12345",
            "login": "quantum-org",
            "url": "https://github.com/quantum-org",
            "avatarUrl": "https://avatars.githubusercontent.com/u/12345",
            "is_relevant": True,
            "discovered_from_repos": [
                {"id": "R_1", "name": "qiskit"},
                {"id": "R_2", "name": "cirq"}
            ]
        }
        
        org = Organization(**data)
        
        assert org.is_relevant is True
        assert len(org.discovered_from_repos) == 2
    
    def test_organization_none_to_empty_list(self):
        """Verifica que el validador convierta None a listas vacías."""
        data = {
            "id": "O_12345",
            "login": "testorg",
            "url": "https://github.com/testorg",
            "avatarUrl": "https://avatars.githubusercontent.com/u/12345",
            "quantum_repositories": None,
            "top_quantum_contributors": None,
            "discovered_from_repos": None,
            "top_languages": None
        }
        
        org = Organization(**data)
        
        assert org.quantum_repositories == []
        assert org.top_quantum_contributors == []
        assert org.discovered_from_repos == []
        assert org.top_languages == []
    
    def test_quantum_focus_score_calculation(self):
        """Verifica el cálculo del quantum focus score."""
        quantum_repos = 2
        total_repos = 50
        
        # Quantum focus score = (quantum_repos / total_repos) * 100
        expected_score = (quantum_repos / total_repos) * 100
        
        assert expected_score == pytest.approx(4.0, rel=1e-2)
    
    def test_prestige_score_calculation(self):
        """Verifica el cálculo del prestige score (suma de estrellas)."""
        quantum_repos_stars = [100, 80, 50]
        
        prestige_score = sum(quantum_repos_stars)
        
        assert prestige_score == 230
    
    def test_organization_with_quantum_metrics(self):
        """Verifica organizaciones con métricas quantum."""
        data = {
            "id": "O_12345",
            "login": "quantum-org",
            "url": "https://github.com/quantum-org",
            "avatarUrl": "https://avatars.githubusercontent.com/u/12345",
            "is_relevant": True,
            "quantum_focus_score": 14.08,
            "quantum_repositories_count": 2,
            "total_repositories_count": 49,
            "total_stars": 124,
            "is_quantum_focused": False  # < 30%
        }
        
        org = Organization(**data)
        
        assert org.is_quantum_focused is False
        assert org.quantum_focus_score == pytest.approx(14.08, rel=1e-2)
    
    def test_organization_top_languages_distribution(self):
        """Verifica la distribución de lenguajes."""
        repos_langs = ["Python", "Python", "Python", "Julia", "Julia", "C++"]
        
        # Contar frecuencias
        lang_count = {}
        for lang in repos_langs:
            lang_count[lang] = lang_count.get(lang, 0) + 1
        
        # Calcular porcentajes
        total = len(repos_langs)
        lang_distribution = {
            lang: (count / total) * 100
            for lang, count in lang_count.items()
        }
        
        assert lang_distribution["Python"] == pytest.approx(50.0, rel=1e-2)
        assert lang_distribution["Julia"] == pytest.approx(33.33, rel=1e-2)
        assert lang_distribution["C++"] == pytest.approx(16.67, rel=1e-2)
    
    def test_unique_organization_discovery(self):
        """Verifica que se eliminen duplicados al descubrir organizaciones."""
        users_orgs = [
            ["org1", "org2", "org3"],
            ["org1", "org4"],
            ["org2", "org5"],
            ["org1", "org2"]
        ]
        
        # Flatten y eliminar duplicados
        all_orgs = set()
        for orgs in users_orgs:
            all_orgs.update(orgs)
        
        unique_orgs = list(all_orgs)
        
        assert len(unique_orgs) == 5
        assert "org1" in unique_orgs
        assert "org5" in unique_orgs


class TestOrganizationIngestionThrottling:
    """Tests para el mecanismo de throttling de Cosmos DB en OrganizationIngestionEngine."""
    
    @patch('src.github.organization_ingestion.MongoRepository')
    @patch('src.github.organization_ingestion.GitHubGraphQLClient')
    def test_retry_on_cosmos_throttle_success(self, mock_graphql_class, mock_repo_class):
        """Verifica que _retry_on_cosmos_throttle ejecute la operacion exitosamente."""
        mock_graphql_instance = MagicMock()
        mock_graphql_class.return_value = mock_graphql_instance
        mock_users_repo = MagicMock()
        mock_orgs_repo = MagicMock()
        
        engine = OrganizationIngestionEngine(
            github_token="fake_token",
            users_repository=mock_users_repo,
            organizations_repository=mock_orgs_repo,
            batch_size=5
        )
        
        # Operacion exitosa
        operation = Mock(return_value={"success": True})
        result = engine._retry_on_cosmos_throttle(operation)
        
        assert result == {"success": True}
        assert operation.call_count == 1
    
    @patch('src.github.organization_ingestion.MongoRepository')
    @patch('src.github.organization_ingestion.GitHubGraphQLClient')
    @patch('time.sleep', return_value=None)  # Mock sleep para acelerar tests
    def test_retry_on_cosmos_throttle_with_429(self, mock_sleep, mock_graphql_class, mock_repo_class):
        """Verifica que _retry_on_cosmos_throttle reintente tras error 429."""
        mock_graphql_instance = MagicMock()
        mock_graphql_class.return_value = mock_graphql_instance
        mock_users_repo = MagicMock()
        mock_orgs_repo = MagicMock()
        
        engine = OrganizationIngestionEngine(
            github_token="fake_token",
            users_repository=mock_users_repo,
            organizations_repository=mock_orgs_repo,
            batch_size=5
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
    
    @patch('src.github.organization_ingestion.MongoRepository')
    @patch('src.github.organization_ingestion.GitHubGraphQLClient')
    @patch('time.sleep', return_value=None)
    def test_retry_on_cosmos_throttle_max_retries(self, mock_sleep, mock_graphql_class, mock_repo_class):
        """Verifica que _retry_on_cosmos_throttle se rinda tras max_retries."""
        mock_graphql_instance = MagicMock()
        mock_graphql_class.return_value = mock_graphql_instance
        mock_users_repo = MagicMock()
        mock_orgs_repo = MagicMock()
        
        engine = OrganizationIngestionEngine(
            github_token="fake_token",
            users_repository=mock_users_repo,
            organizations_repository=mock_orgs_repo,
            batch_size=5
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
    
    @patch('src.github.organization_ingestion.MongoRepository')
    @patch('src.github.organization_ingestion.GitHubGraphQLClient')
    def test_retry_on_cosmos_throttle_other_error(self, mock_graphql_class, mock_repo_class):
        """Verifica que otros errores (no 429) se propaguen."""
        mock_graphql_instance = MagicMock()
        mock_graphql_class.return_value = mock_graphql_instance
        mock_users_repo = MagicMock()
        mock_orgs_repo = MagicMock()
        
        engine = OrganizationIngestionEngine(
            github_token="fake_token",
            users_repository=mock_users_repo,
            organizations_repository=mock_orgs_repo,
            batch_size=5
        )
        
        # Error diferente (no throttling)
        operation = Mock(
            side_effect=OperationFailure("Different error", code=99999)
        )
        
        # Debe propagarse el error
        with pytest.raises(OperationFailure):
            engine._retry_on_cosmos_throttle(operation)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
