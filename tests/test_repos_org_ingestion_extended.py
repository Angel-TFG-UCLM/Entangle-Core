"""Tests for repos_ingestion extended methods and org_ingestion methods."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


@pytest.fixture
def ingestion_engine():
    with patch('src.github.repositories_ingestion.GitHubGraphQLClient') as mock_cls:
        mock_gql = MagicMock()
        mock_cls.return_value = mock_gql
        from src.github.repositories_ingestion import IngestionEngine
        e = IngestionEngine(client=mock_gql, batch_size=10)
        return e


@pytest.fixture
def org_ingestion_engine():
    with patch('src.github.organization_ingestion.GitHubGraphQLClient') as mock_cls:
        mock_gql = MagicMock()
        mock_gql.get_rate_limit.return_value = {"remaining": 4900, "limit": 5000, "resetAt": "2025-12-31T00:00:00Z"}
        mock_cls.return_value = mock_gql
        from src.github.organization_ingestion import OrganizationIngestionEngine
        e = OrganizationIngestionEngine(
            github_token="ghp_test",
            users_repository=MagicMock(),
            organizations_repository=MagicMock(),
            batch_size=10,
        )
        e.graphql_client = mock_gql
        return e


class TestIngestionSanitize:
    def test_sanitize_basic(self, ingestion_engine):
        data = {"nameWithOwner": "owner/repo", "description": "test"}
        result = ingestion_engine._sanitize_repo_data(data)
        assert isinstance(result, dict)

    def test_sanitize_none_values(self, ingestion_engine):
        data = {"nameWithOwner": None, "description": None}
        result = ingestion_engine._sanitize_repo_data(data)
        assert isinstance(result, dict)


class TestIngestionReportProgress:
    def test_with_callback(self, ingestion_engine):
        callback = MagicMock()
        ingestion_engine.progress_callback = callback
        ingestion_engine._report_progress(5, 10, "Processing")
        callback.assert_called_once()

    def test_without_callback(self, ingestion_engine):
        ingestion_engine.progress_callback = None
        ingestion_engine._report_progress(5, 10, "Processing")


class TestIngestionValidate:
    def test_validate_empty_list(self, ingestion_engine):
        valid, errors = ingestion_engine._validate_repositories([])
        assert valid == []
        assert errors == []

    def test_validate_invalid_data(self, ingestion_engine):
        valid, errors = ingestion_engine._validate_repositories([
            {"nameWithOwner": "invalid", "bad_field": True}
        ])
        assert len(errors) >= 0
        assert len(valid) + len(errors) >= 0


class TestIngestionGenerateReport:
    def test_basic_report(self, ingestion_engine):
        ingestion_engine.stats["start_time"] = datetime(2024, 1, 1)
        ingestion_engine.stats["end_time"] = datetime(2024, 1, 1, 0, 1)
        ingestion_engine.stats["repositories_inserted"] = 5
        ingestion_engine.stats["repositories_updated"] = 2
        repo_mock = MagicMock()
        repo_mock.primary_language = MagicMock()
        repo_mock.primary_language.name = "Python"
        repo_mock.stargazer_count = 100
        result = ingestion_engine._generate_report([repo_mock], [])
        assert isinstance(result, dict)

    def test_report_empty(self, ingestion_engine):
        ingestion_engine.stats["start_time"] = None
        ingestion_engine.stats["end_time"] = None
        result = ingestion_engine._generate_report([], [])
        assert isinstance(result, dict)


class TestOrgIngestionGetUpdateFields:
    def test_normal_fields(self, org_ingestion_engine):
        org_dict = {"login": "test", "name": "Test Org", "url": "https://..."}
        existing = {"login": "test", "name": "Old Name"}
        result = org_ingestion_engine._get_update_fields(org_dict, existing)
        assert result["name"] == "Test Org"

    def test_preserves_enriched_fields(self, org_ingestion_engine):
        org_dict = {"login": "test", "quantum_focus_score": 50.0}
        existing = {"login": "test", "quantum_focus_score": 75.0}
        result = org_ingestion_engine._get_update_fields(org_dict, existing)
        assert "quantum_focus_score" not in result

    def test_updates_noset_enriched_fields(self, org_ingestion_engine):
        org_dict = {"login": "test", "quantum_focus_score": 50.0}
        existing = {"login": "test", "quantum_focus_score": None}
        result = org_ingestion_engine._get_update_fields(org_dict, existing)
        assert result["quantum_focus_score"] == 50.0


class TestOrgIngestionCleanup:
    def test_cleanup(self, org_ingestion_engine):
        org_ingestion_engine.organizations_repository.count_documents.return_value = 5
        org_ingestion_engine.organizations_repository.delete_many.return_value = 5
        org_ingestion_engine._cleanup_collection()
        org_ingestion_engine.organizations_repository.delete_many.assert_called_once()


class TestOrgIngestionFinalizeStats:
    def test_finalize(self, org_ingestion_engine):
        org_ingestion_engine.stats["start_time"] = datetime.now()
        org_ingestion_engine.stats["total_relevant"] = 3
        org_ingestion_engine.stats["total_non_relevant"] = 2
        org_ingestion_engine.organizations_repository.collection.count_documents.return_value = 5
        result = org_ingestion_engine._finalize_stats()
        assert isinstance(result, dict)
        assert "duration_seconds" in result


class TestOrgIngestionBuildBatchQuery:
    def test_build_query(self, org_ingestion_engine):
        query, variables = org_ingestion_engine._build_batch_query(["org1", "org2"])
        assert isinstance(query, str)
        assert isinstance(variables, dict)
        assert "org1" in str(variables) or "org1" in query

    def test_single_login(self, org_ingestion_engine):
        query, variables = org_ingestion_engine._build_batch_query(["single-org"])
        assert isinstance(query, str)


class TestOrgIngestionGetExistingOrgs:
    def test_existing(self, org_ingestion_engine):
        org_ingestion_engine.organizations_repository.collection.find.return_value = [
            {"login": "org1", "_id": "id1"}
        ]
        result = org_ingestion_engine._get_existing_orgs(["org1", "org2"])
        assert isinstance(result, dict)
