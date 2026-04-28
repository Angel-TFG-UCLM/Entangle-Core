"""
Tests for enrichment/ingestion engine init and rate_limit module.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestEnrichmentEngineInit:
    @patch('src.github.repositories_enrichment.GitHubGraphQLClient')
    def test_init(self, mock_gql):
        from src.github.repositories_enrichment import EnrichmentEngine
        engine = EnrichmentEngine(
            github_token="ghp_test",
            repos_repository=MagicMock(),
            batch_size=10,
        )
        assert engine.github_token == "ghp_test"
        assert engine.batch_size == 10

    @patch('src.github.repositories_enrichment.GitHubGraphQLClient')
    def test_init_with_config(self, mock_gql):
        from src.github.repositories_enrichment import EnrichmentEngine
        config = {"enrichment": {"max_retries": 5, "base_backoff_seconds": 3}}
        engine = EnrichmentEngine(
            github_token="ghp_test",
            repos_repository=MagicMock(),
            config=config,
        )
        assert engine.max_retries == 5

    @patch('src.github.repositories_enrichment.GitHubGraphQLClient')
    def test_has_super_query(self, mock_gql):
        from src.github.repositories_enrichment import EnrichmentEngine
        assert "repository" in EnrichmentEngine.REPO_ENRICHMENT_SUPER_QUERY


class TestUserEnrichmentEngineInit:
    @patch('src.github.user_enrichment.GitHubGraphQLClient')
    def test_init(self, mock_gql):
        from src.github.user_enrichment import UserEnrichmentEngine
        engine = UserEnrichmentEngine(
            github_token="ghp_test",
            users_repository=MagicMock(),
            repos_repository=MagicMock(),
        )
        assert engine.github_token == "ghp_test"


class TestOrgEnrichmentEngineInit:
    @patch('src.github.organization_enrichment.GitHubGraphQLClient')
    def test_init(self, mock_gql):
        from src.github.organization_enrichment import OrganizationEnrichmentEngine
        engine = OrganizationEnrichmentEngine(
            github_token="ghp_test",
            organizations_repository=MagicMock(),
            repositories_repository=MagicMock(),
            users_repository=MagicMock(),
        )
        assert engine.github_token == "ghp_test"


class TestIngestionEngineInit:
    @patch('src.github.repositories_ingestion.GitHubGraphQLClient')
    @patch('src.github.repositories_ingestion.ingestion_config')
    def test_init(self, mock_config, mock_gql):
        mock_config.keywords = ["quantum"]
        mock_config.search_keywords = ["quantum computing"]
        mock_config.languages = ["Python"]
        mock_config.min_stars = 10
        mock_config.max_inactivity_days = 365
        mock_config.exclude_forks = True
        mock_config.min_contributors = 1
        mock_config.additional_filters = {}
        from src.github.repositories_ingestion import IngestionEngine
        engine = IngestionEngine(
            client=MagicMock(),
        )
        assert engine is not None


class TestUserIngestionEngineInit:
    def test_init(self):
        from src.github.user_ingestion import UserIngestionEngine
        engine = UserIngestionEngine(
            github_client=MagicMock(),
            repos_repository=MagicMock(),
            users_repository=MagicMock(),
        )
        assert engine.stats["repos_processed"] == 0


class TestOrgIngestionEngineInit:
    @patch('src.github.organization_ingestion.GitHubGraphQLClient')
    def test_init(self, mock_gql):
        from src.github.organization_ingestion import OrganizationIngestionEngine
        engine = OrganizationIngestionEngine(
            github_token="ghp_test",
            users_repository=MagicMock(),
            organizations_repository=MagicMock(),
        )
        assert engine.stats["total_discovered"] == 0


class TestRateLimitModule:
    @patch('src.github.rate_limit.github_client')
    def test_get_rate_limit_info(self, mock_client):
        from src.github.rate_limit import get_rate_limit_info
        mock_client.get_rate_limit.return_value = {
            "limit": 5000, "remaining": 4990,
            "resetAt": "2025-01-01T00:00:00Z", "used": 10, "cost": 1
        }
        result = get_rate_limit_info()
        assert result["remaining"] == 4990

    @patch('src.github.rate_limit.github_client')
    def test_get_rate_limit_error(self, mock_client):
        from src.github.rate_limit import get_rate_limit_info
        mock_client.get_rate_limit.side_effect = Exception("Network error")
        with pytest.raises(Exception):
            get_rate_limit_info()
