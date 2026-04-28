"""
Tests for OrganizationEnrichmentEngine pure-logic methods.
"""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def org_engine():
    with patch('src.github.organization_enrichment.GitHubGraphQLClient'):
        from src.github.organization_enrichment import OrganizationEnrichmentEngine
        engine = OrganizationEnrichmentEngine(
            github_token="ghp_test",
            organizations_repository=MagicMock(),
            repositories_repository=MagicMock(),
            users_repository=MagicMock(),
        )
        return engine


class TestOrgBuildEnrichmentBatchQuery:
    def test_single_org(self, org_engine):
        query, variables = org_engine._build_enrichment_batch_query(["github"])
        assert "org0: organization(login: $login0)" in query
        assert variables["login0"] == "github"

    def test_multiple_orgs(self, org_engine):
        logins = ["github", "microsoft", "google"]
        query, variables = org_engine._build_enrichment_batch_query(logins)
        for i, login in enumerate(logins):
            assert f"org{i}" in query
            assert variables[f"login{i}"] == login
        assert len(variables) == 3

    def test_empty_list(self, org_engine):
        query, variables = org_engine._build_enrichment_batch_query([])
        assert variables == {}

    def test_query_has_fragment(self, org_engine):
        query, _ = org_engine._build_enrichment_batch_query(["test"])
        assert "OrgEnrichmentFields" in query


class TestCalculateEnrichmentUpdates:
    def test_with_quantum_repos(self, org_engine):
        org_engine._find_quantum_repositories = MagicMock(return_value={
            "repo_ids": ["repo1", "repo2"],
            "repos": [{"collaborators": [{"login": "a"}, {"login": "b"}]}],
        })
        org_engine._find_top_quantum_contributors = MagicMock(return_value=[
            {"login": "a", "contributions": 100},
        ])
        org_engine._count_unique_contributors = MagicMock(return_value=5)
        org_engine._calculate_top_languages = MagicMock(return_value=[
            {"language": "Python", "count": 2},
        ])
        org_engine._calculate_total_stars = MagicMock(return_value=500)
        org_engine._calculate_quantum_focus_score = MagicMock(return_value=75.0)

        org = {"login": "quantum-org", "name": "Quantum Org", "description": "Quantum stuff"}
        graphql_data = {
            "repositories": {"totalCount": 50},
            "membersWithRole": {"totalCount": 20},
        }

        updates = org_engine._calculate_enrichment_updates(org, graphql_data)
        assert updates is not None
        assert updates["total_repositories_count"] == 50
        assert updates["total_members_count"] == 20
        assert updates["quantum_repositories_count"] == 2
        assert updates["quantum_focus_score"] == 75.0
        assert updates["is_quantum_focused"] is True
        assert updates["enrichment_status"]["is_complete"] is True

    def test_without_quantum_repos(self, org_engine):
        org_engine._find_quantum_repositories = MagicMock(return_value=None)
        org_engine._calculate_quantum_focus_score = MagicMock(return_value=0.0)

        org = {"login": "normal-org", "name": "Normal Org", "description": ""}
        graphql_data = {
            "repositories": {"totalCount": 10},
            "membersWithRole": {"totalCount": 5},
        }

        updates = org_engine._calculate_enrichment_updates(org, graphql_data)
        assert updates is not None
        assert updates["quantum_repositories"] == []
        assert updates["quantum_repositories_count"] == 0
        assert updates["is_quantum_focused"] is False

    def test_error_returns_none(self, org_engine):
        org_engine._find_quantum_repositories = MagicMock(side_effect=Exception("DB error"))

        org = {"login": "error-org"}
        graphql_data = {
            "repositories": {"totalCount": 10},
            "membersWithRole": {"totalCount": 5},
        }

        updates = org_engine._calculate_enrichment_updates(org, graphql_data)
        assert updates is None


class TestRetryOnCosmosThrottle:
    def test_passthrough(self, org_engine):
        """_retry_on_cosmos_throttle should just call the operation directly."""
        operation = MagicMock(return_value="result")
        result = org_engine._retry_on_cosmos_throttle(operation)
        operation.assert_called_once()
        assert result == "result"
