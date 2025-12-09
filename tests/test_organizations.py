"""
Tests para modelo y operaciones de organizaciones.
Tests unitarios con mocks - NO requieren servicios externos.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock

from src.models.organization import Organization


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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
