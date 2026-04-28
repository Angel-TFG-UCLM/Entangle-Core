"""Tests for organization_enrichment.py extended methods."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


@pytest.fixture
def org_engine():
    with patch('src.github.organization_enrichment.GitHubGraphQLClient') as mock_cls:
        mock_gql = MagicMock()
        mock_gql.get_rate_limit.return_value = {
            "remaining": 4900, "limit": 5000, "resetAt": "2025-12-31T00:00:00Z"
        }
        mock_cls.return_value = mock_gql
        from src.github.organization_enrichment import OrganizationEnrichmentEngine
        e = OrganizationEnrichmentEngine(
            github_token="ghp_test",
            organizations_repository=MagicMock(),
            repositories_repository=MagicMock(),
            users_repository=MagicMock(),
            batch_size=5,
        )
        e.graphql_client = mock_gql
        return e


class TestCountUniqueContributors:
    def test_with_collaborators(self, org_engine):
        repos = [
            {"collaborators": [{"login": "a"}, {"login": "b"}]},
            {"collaborators": [{"login": "b"}, {"login": "c"}]},
        ]
        assert org_engine._count_unique_contributors(repos) == 3

    def test_empty_repos(self, org_engine):
        assert org_engine._count_unique_contributors([]) == 0

    def test_no_collaborators(self, org_engine):
        repos = [{"collaborators": None}, {"collaborators": []}]
        assert org_engine._count_unique_contributors(repos) == 0

    def test_empty_logins(self, org_engine):
        repos = [{"collaborators": [{"login": ""}, {"login": "a"}]}]
        assert org_engine._count_unique_contributors(repos) == 1


class TestCalculateQuantumFocusScore:
    def test_basic_score(self, org_engine):
        score = org_engine._calculate_quantum_focus_score(5, 10, False, "TestOrg", "A test org")
        assert score == 50.0

    def test_with_quantum_keyword(self, org_engine):
        score = org_engine._calculate_quantum_focus_score(5, 10, False, "QuantumOrg", "quantum computing")
        assert score == 60.0

    def test_with_verification(self, org_engine):
        score = org_engine._calculate_quantum_focus_score(5, 10, True, "TestOrg", "no keywords")
        assert score == 60.0

    def test_zero_total(self, org_engine):
        score = org_engine._calculate_quantum_focus_score(0, 0, False, "Org", "desc")
        assert score == 0.0

    def test_cap_at_100(self, org_engine):
        score = org_engine._calculate_quantum_focus_score(10, 10, True, "Quantum", "quantum qiskit")
        assert score == 100.0

    def test_various_keywords(self, org_engine):
        for kw in ["qiskit", "cirq", "pennylane", "braket"]:
            score = org_engine._calculate_quantum_focus_score(1, 10, False, kw, "")
            assert score == 20.0


class TestCalculateTopLanguages:
    def test_with_repos(self, org_engine):
        org_engine._retry_on_cosmos_throttle = lambda fn: fn()
        org_engine.repos_repository.collection.find.return_value = [
            {"primary_language": {"name": "Python"}},
            {"primary_language": {"name": "Python"}},
            {"primary_language": {"name": "Rust"}},
        ]
        result = org_engine._calculate_top_languages(["id1", "id2", "id3"])
        assert len(result) >= 1
        assert result[0]["name"] == "Python"
        assert result[0]["repo_count"] == 2

    def test_empty_ids(self, org_engine):
        assert org_engine._calculate_top_languages([]) == []

    def test_string_language(self, org_engine):
        org_engine._retry_on_cosmos_throttle = lambda fn: fn()
        org_engine.repos_repository.collection.find.return_value = [
            {"primary_language": "Julia"},
        ]
        result = org_engine._calculate_top_languages(["id1"])
        assert len(result) == 1
        assert result[0]["name"] == "Julia"


class TestCalculateTotalStars:
    def test_with_stars(self, org_engine):
        org_engine._retry_on_cosmos_throttle = lambda fn: fn()
        org_engine.repos_repository.collection.find.return_value = [
            {"stargazer_count": 100},
            {"stargazer_count": 50},
        ]
        assert org_engine._calculate_total_stars(["id1", "id2"]) == 150

    def test_empty_ids(self, org_engine):
        assert org_engine._calculate_total_stars([]) == 0

    def test_none_result(self, org_engine):
        org_engine._retry_on_cosmos_throttle = lambda fn: fn()
        org_engine.repos_repository.collection.find.return_value = []
        assert org_engine._calculate_total_stars(["id1"]) == 0


class TestFinalizeStats:
    def test_finalize(self, org_engine):
        org_engine.stats["start_time"] = datetime.now()
        org_engine.stats["total_processed"] = 5
        org_engine.stats["total_enriched"] = 3
        org_engine.stats["total_errors"] = 1
        result = org_engine._finalize_stats()
        assert isinstance(result, dict)
        assert "duration_seconds" in result


class TestLogEnrichmentResult:
    def test_log(self, org_engine):
        org = {"login": "test-org"}
        updates = {
            "quantum_repositories_count": 5, "total_repositories_count": 10,
            "quantum_focus_score": 50.0, "total_stars": 100,
            "quantum_contributors_count": 3,
        }
        org_engine._log_enrichment_result(org, updates)


class TestCheckRateLimit:
    def test_enough_remaining(self, org_engine):
        result = org_engine._check_rate_limit()
        assert result is True

    def test_low_remaining(self, org_engine):
        org_engine.graphql_client.get_rate_limit.return_value = {
            "remaining": 5, "limit": 5000, "resetAt": "2025-12-31T00:00:00Z"
        }
        with patch.object(org_engine, '_wait_for_rate_limit_reset'):
            result = org_engine._check_rate_limit()
