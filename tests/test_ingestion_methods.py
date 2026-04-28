"""
Tests for IngestionEngine pure-logic methods: filter, validate, sanitize, report, progress.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime


@pytest.fixture
def ingestion_engine():
    with patch('src.github.repositories_ingestion.GitHubGraphQLClient'), \
         patch('src.github.repositories_ingestion.ingestion_config') as mock_cfg:
        mock_cfg.keywords = ["quantum"]
        mock_cfg.search_keywords = ["quantum computing"]
        mock_cfg.languages = ["Python"]
        mock_cfg.min_stars = 10
        mock_cfg.max_inactivity_days = 365
        mock_cfg.exclude_forks = True
        mock_cfg.min_contributors = 1
        mock_cfg.additional_filters = {}
        from src.github.repositories_ingestion import IngestionEngine
        engine = IngestionEngine(client=MagicMock())
        return engine


class TestSanitizeRepoData:
    def test_short_readme_unchanged(self, ingestion_engine):
        repo = {"nameWithOwner": "test/repo", "object": {"text": "short readme"}}
        result = ingestion_engine._sanitize_repo_data(repo)
        assert result["object"]["text"] == "short readme"

    def test_long_readme_truncated(self, ingestion_engine):
        long_text = "x" * 1000
        repo = {"nameWithOwner": "test/repo", "object": {"text": long_text}}
        result = ingestion_engine._sanitize_repo_data(repo)
        assert len(result["object"]["text"]) < 1000
        assert "TRUNCATED" in result["object"]["text"]

    def test_no_object_field(self, ingestion_engine):
        repo = {"nameWithOwner": "test/repo"}
        result = ingestion_engine._sanitize_repo_data(repo)
        assert result["nameWithOwner"] == "test/repo"

    def test_object_without_text(self, ingestion_engine):
        repo = {"object": {"other": "data"}}
        result = ingestion_engine._sanitize_repo_data(repo)
        assert result["object"]["other"] == "data"

    def test_exception_returns_error(self, ingestion_engine):
        # Pass something that causes .copy() to fail
        result = ingestion_engine._sanitize_repo_data(None)
        assert "error" in result


class TestReportProgress:
    def test_with_callback(self, ingestion_engine):
        callback = MagicMock()
        ingestion_engine.progress_callback = callback
        ingestion_engine._report_progress(50, 100, "Processing...")
        callback.assert_called_once_with(50, 100, "Processing...")

    def test_without_callback(self, ingestion_engine):
        ingestion_engine.progress_callback = None
        # Should not raise
        ingestion_engine._report_progress(50, 100, "Processing...")

    def test_callback_exception_swallowed(self, ingestion_engine):
        callback = MagicMock(side_effect=Exception("callback error"))
        ingestion_engine.progress_callback = callback
        # Should not raise
        ingestion_engine._report_progress(50, 100, "Processing...")


class TestFilterRepositories:
    """Test filter_repositories with mocked RepositoryFilters."""

    @patch('src.github.repositories_ingestion.RepositoryFilters')
    def test_all_filters_pass(self, mock_filters, ingestion_engine):
        # Make all filters return True
        mock_filters.is_not_archived.return_value = True
        mock_filters.is_not_blacklisted.return_value = True
        mock_filters.has_quantum_relevance.return_value = True
        mock_filters.has_description.return_value = True
        mock_filters.is_minimal_project.return_value = True
        mock_filters.is_active.return_value = True
        mock_filters.is_valid_fork.return_value = True
        mock_filters.matches_keywords.return_value = True
        mock_filters.has_valid_language.return_value = True
        mock_filters.has_minimum_stars.return_value = True
        mock_filters.has_community_engagement.return_value = True

        repos = [{"nameWithOwner": "test/repo", "stargazerCount": 50}]
        result = ingestion_engine.filter_repositories(repos)
        assert len(result) == 1

    @patch('src.github.repositories_ingestion.RepositoryFilters')
    def test_archived_filtered(self, mock_filters, ingestion_engine):
        mock_filters.is_not_archived.return_value = False
        repos = [{"nameWithOwner": "test/archived"}]
        result = ingestion_engine.filter_repositories(repos)
        assert len(result) == 0
        assert ingestion_engine.stats["filtered_by_archived"] >= 1

    @patch('src.github.repositories_ingestion.RepositoryFilters')
    def test_blacklist_filtered(self, mock_filters, ingestion_engine):
        mock_filters.is_not_archived.return_value = True
        mock_filters.is_not_blacklisted.return_value = False
        repos = [{"nameWithOwner": "test/blacklisted"}]
        result = ingestion_engine.filter_repositories(repos)
        assert len(result) == 0

    @patch('src.github.repositories_ingestion.RepositoryFilters')
    def test_no_description_filtered(self, mock_filters, ingestion_engine):
        mock_filters.is_not_archived.return_value = True
        mock_filters.is_not_blacklisted.return_value = True
        mock_filters.has_quantum_relevance.return_value = True
        mock_filters.has_description.return_value = False
        repos = [{"nameWithOwner": "test/no-desc"}]
        result = ingestion_engine.filter_repositories(repos)
        assert len(result) == 0
        assert ingestion_engine.stats["filtered_by_no_description"] >= 1

    @patch('src.github.repositories_ingestion.RepositoryFilters')
    def test_multiple_repos_mixed(self, mock_filters, ingestion_engine):
        # First passes all, second fails at archived
        mock_filters.is_not_archived.side_effect = [True, False]
        mock_filters.is_not_blacklisted.return_value = True
        mock_filters.has_quantum_relevance.return_value = True
        mock_filters.has_description.return_value = True
        mock_filters.is_minimal_project.return_value = True
        mock_filters.is_active.return_value = True
        mock_filters.is_valid_fork.return_value = True
        mock_filters.matches_keywords.return_value = True
        mock_filters.has_valid_language.return_value = True
        mock_filters.has_minimum_stars.return_value = True
        mock_filters.has_community_engagement.return_value = True

        repos = [
            {"nameWithOwner": "test/good", "stargazerCount": 100},
            {"nameWithOwner": "test/archived"},
        ]
        result = ingestion_engine.filter_repositories(repos)
        assert len(result) == 1
        assert result[0]["nameWithOwner"] == "test/good"

    @patch('src.github.repositories_ingestion.RepositoryFilters')
    def test_stars_filtered(self, mock_filters, ingestion_engine):
        mock_filters.is_not_archived.return_value = True
        mock_filters.is_not_blacklisted.return_value = True
        mock_filters.has_quantum_relevance.return_value = True
        mock_filters.has_description.return_value = True
        mock_filters.is_minimal_project.return_value = True
        mock_filters.is_active.return_value = True
        mock_filters.is_valid_fork.return_value = True
        mock_filters.matches_keywords.return_value = True
        mock_filters.has_valid_language.return_value = True
        mock_filters.has_minimum_stars.return_value = False
        repos = [{"nameWithOwner": "test/low-stars", "stargazerCount": 0}]
        result = ingestion_engine.filter_repositories(repos)
        assert len(result) == 0
        assert ingestion_engine.stats["filtered_by_stars"] >= 1

    @patch('src.github.repositories_ingestion.RepositoryFilters')
    def test_empty_list(self, mock_filters, ingestion_engine):
        result = ingestion_engine.filter_repositories([])
        assert result == []


class TestValidateRepositories:
    @patch('src.github.repositories_ingestion.Repository')
    def test_valid_repo(self, mock_repo_cls, ingestion_engine):
        mock_repo_cls.from_graphql_response.return_value = MagicMock()
        repos = [{"nameWithOwner": "test/repo"}]
        validated, errors = ingestion_engine._validate_repositories(repos)
        assert len(validated) == 1
        assert len(errors) == 0

    @patch('src.github.repositories_ingestion.Repository')
    def test_validation_error(self, mock_repo_cls, ingestion_engine):
        from pydantic import ValidationError
        mock_repo_cls.from_graphql_response.side_effect = ValidationError.from_exception_data(
            title="Repository",
            line_errors=[{
                "type": "missing",
                "loc": ("name",),
                "msg": "Field required",
                "input": {},
            }],
        )
        repos = [{"nameWithOwner": "test/bad"}]
        validated, errors = ingestion_engine._validate_repositories(repos)
        assert len(validated) == 0
        assert len(errors) == 1

    @patch('src.github.repositories_ingestion.Repository')
    def test_unexpected_error(self, mock_repo_cls, ingestion_engine):
        mock_repo_cls.from_graphql_response.side_effect = RuntimeError("unexpected")
        repos = [{"nameWithOwner": "test/crash"}]
        validated, errors = ingestion_engine._validate_repositories(repos)
        assert len(validated) == 0
        assert len(errors) == 1
        assert errors[0]["error"] == "unexpected"

    @patch('src.github.repositories_ingestion.Repository')
    def test_mixed_valid_invalid(self, mock_repo_cls, ingestion_engine):
        mock_repo_cls.from_graphql_response.side_effect = [
            MagicMock(),
            RuntimeError("bad"),
            MagicMock(),
        ]
        repos = [
            {"nameWithOwner": "test/good1"},
            {"nameWithOwner": "test/bad"},
            {"nameWithOwner": "test/good2"},
        ]
        validated, errors = ingestion_engine._validate_repositories(repos)
        assert len(validated) == 2
        assert len(errors) == 1
        assert ingestion_engine.stats["validation_success"] == 2
        assert ingestion_engine.stats["validation_errors"] == 1
