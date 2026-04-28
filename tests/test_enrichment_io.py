"""
Tests for EnrichmentEngine I/O methods with full mocking.
"""
import pytest
from unittest.mock import MagicMock, patch
import threading


@pytest.fixture
def enrichment_engine():
    with patch('src.github.repositories_enrichment.GitHubGraphQLClient') as mock_gql_cls:
        mock_gql = MagicMock()
        mock_gql.get_rate_limit.return_value = {
            "limit": 5000, "remaining": 4900,
            "resetAt": "2025-12-31T00:00:00Z", "used": 100, "cost": 1,
        }
        mock_gql_cls.return_value = mock_gql
        from src.github.repositories_enrichment import EnrichmentEngine
        engine = EnrichmentEngine(
            github_token="ghp_test",
            repos_repository=MagicMock(),
            batch_size=5,
        )
        engine.graphql_client = mock_gql
        return engine


class TestCheckAndDisplayRateLimit:
    def test_normal(self, enrichment_engine):
        result = enrichment_engine._check_and_display_rate_limit()
        assert isinstance(result, dict)

    def test_no_rate_limit_data(self, enrichment_engine):
        enrichment_engine.graphql_client.get_rate_limit.return_value = None
        result = enrichment_engine._check_and_display_rate_limit()
        assert result == {}

    def test_exception_handled(self, enrichment_engine):
        enrichment_engine.graphql_client.get_rate_limit.side_effect = Exception("fail")
        result = enrichment_engine._check_and_display_rate_limit()
        assert isinstance(result, dict)


class TestEnrichAllRepos:
    def test_no_repos(self, enrichment_engine):
        coll = MagicMock()
        coll.count_documents.return_value = 0
        coll.find.return_value = MagicMock(batch_size=MagicMock(return_value=[]))
        enrichment_engine.repos_repository.collection = coll
        result = enrichment_engine.enrich_all_repositories()
        assert isinstance(result, dict)

    def test_cancelled(self, enrichment_engine):
        cancel = threading.Event()
        cancel.set()
        enrichment_engine.cancel_event = cancel
        coll = MagicMock()
        coll.count_documents.return_value = 10
        enrichment_engine.repos_repository.collection = coll
        result = enrichment_engine.enrich_all_repositories()
        assert isinstance(result, dict)


class TestEnrichmentStats:
    def test_initial_stats(self, enrichment_engine):
        assert enrichment_engine.stats["total_processed"] == 0
        assert enrichment_engine.stats["total_enriched"] == 0
        assert enrichment_engine.stats["total_errors"] == 0

    def test_config_overrides(self):
        with patch('src.github.repositories_enrichment.GitHubGraphQLClient'):
            from src.github.repositories_enrichment import EnrichmentEngine
            config = {"enrichment": {"max_retries": 10, "base_backoff_seconds": 5}}
            engine = EnrichmentEngine(
                github_token="ghp_test",
                repos_repository=MagicMock(),
                config=config,
            )
            assert engine.max_retries == 10
            assert engine.base_backoff == 5


class TestRetryWithBackoff:
    def test_success(self, enrichment_engine):
        func = MagicMock(return_value="ok")
        result = enrichment_engine._retry_with_backoff(func)
        assert result == "ok"
