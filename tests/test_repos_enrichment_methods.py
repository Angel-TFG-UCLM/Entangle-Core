"""Tests for repositories_enrichment.py pure-logic methods."""
import pytest
import threading
from unittest.mock import MagicMock, patch, PropertyMock
import requests


@pytest.fixture
def engine():
    with patch('src.github.repositories_enrichment.GitHubGraphQLClient') as mock_cls:
        mock_gql = MagicMock()
        mock_gql.get_rate_limit.return_value = {
            "limit": 5000, "remaining": 4900,
            "resetAt": "2025-12-31T00:00:00Z", "used": 100, "cost": 1,
        }
        mock_cls.return_value = mock_gql
        from src.github.repositories_enrichment import EnrichmentEngine
        e = EnrichmentEngine(
            github_token="ghp_test",
            repos_repository=MagicMock(),
            batch_size=5,
        )
        e.graphql_client = mock_gql
        e.session = MagicMock()
        return e


class TestCalculateFields:
    def test_languages_count(self, engine):
        repo = {"languages": [{"name": "Python"}, {"name": "JS"}], "languages_count": 0}
        result = engine._calculate_fields(repo)
        assert result["languages_count"] == 2

    def test_topics_count(self, engine):
        repo = {"repository_topics": ["a", "b", "c"], "topics_count": 0}
        result = engine._calculate_fields(repo)
        assert result["topics_count"] == 3

    def test_issues_count(self, engine):
        repo = {"open_issues_count": 5, "closed_issues_count": 3, "issues_count": 0}
        result = engine._calculate_fields(repo)
        assert result["issues_count"] == 8

    def test_no_updates_when_already_set(self, engine):
        repo = {"languages": [{"name": "Python"}], "languages_count": 1,
                "repository_topics": ["a"], "topics_count": 1,
                "open_issues_count": 5, "closed_issues_count": 3, "issues_count": 8}
        result = engine._calculate_fields(repo)
        assert result == {}

    def test_empty_repo(self, engine):
        result = engine._calculate_fields({})
        assert result == {}


class TestGenerateUrls:
    def test_generates_urls(self, engine):
        repo = {"name_with_owner": "owner/repo"}
        result = engine._generate_urls(repo)
        assert result["clone_url"] == "https://github.com/owner/repo.git"
        assert result["ssh_url"] == "git@github.com:owner/repo.git"

    def test_no_name_with_owner(self, engine):
        result = engine._generate_urls({})
        assert result == {}

    def test_already_has_urls(self, engine):
        repo = {"name_with_owner": "o/r", "clone_url": "x", "ssh_url": "y"}
        result = engine._generate_urls(repo)
        assert result == {}


class TestEnrichOwnerInfo:
    def test_org_type_from_url(self, engine):
        repo = {"owner": {"url": "https://github.com/orgs/test"}}
        result = engine._enrich_owner_info(repo)
        assert result["owner"]["type"] == "Organization"

    def test_user_type_from_url(self, engine):
        repo = {"owner": {"url": "https://github.com/users/test"}}
        result = engine._enrich_owner_info(repo)
        assert result["owner"]["type"] == "User"

    def test_no_owner(self, engine):
        result = engine._enrich_owner_info({})
        assert result == {}

    def test_type_already_set(self, engine):
        repo = {"owner": {"type": "User", "url": "https://github.com/users/test"}}
        result = engine._enrich_owner_info(repo)
        assert result == {}


class TestFixSimpleFields:
    def test_node_id_from_id(self, engine):
        repo = {"id": "MDEwOlJlcG9z", "name_with_owner": "o/r"}
        result = engine._fix_simple_fields(repo)
        assert result["node_id"] == "MDEwOlJlcG9z"
        assert result["full_name"] == "o/r"

    def test_already_has_fields(self, engine):
        repo = {"id": "x", "node_id": "x", "name_with_owner": "o/r", "full_name": "o/r"}
        result = engine._fix_simple_fields(repo)
        assert result == {}


class TestParseCommitsFromData:
    def test_valid_commits(self, engine):
        data = {
            "defaultBranchRef": {
                "target": {
                    "history": {
                        "nodes": [
                            {"oid": "abc123", "message": "fix", "committedDate": "2024-01-01",
                             "author": {"user": {"login": "dev1"}}}
                        ]
                    }
                }
            }
        }
        result = engine._parse_commits_from_data(data)
        assert len(result) == 1
        assert result[0]["oid"] == "abc123"
        assert result[0]["author_login"] == "dev1"

    def test_no_branch(self, engine):
        assert engine._parse_commits_from_data({}) is None

    def test_empty_nodes(self, engine):
        data = {"defaultBranchRef": {"target": {"history": {"nodes": []}}}}
        assert engine._parse_commits_from_data(data) is None


class TestParseIssuesFromData:
    def test_valid_issues(self, engine):
        data = {"issues": {"nodes": [
            {"id": "1", "number": 42, "title": "Bug", "state": "OPEN",
             "createdAt": "2024-01-01", "closedAt": None}
        ]}}
        result = engine._parse_issues_from_data(data)
        assert len(result) == 1
        assert result[0]["number"] == 42

    def test_empty(self, engine):
        assert engine._parse_issues_from_data({"issues": {"nodes": []}}) is None


class TestParsePrsFromData:
    def test_valid_prs(self, engine):
        data = {"pullRequests": {"nodes": [
            {"id": "1", "number": 10, "title": "Feature", "state": "MERGED",
             "createdAt": "2024-01-01", "closedAt": "2024-01-02", "mergedAt": "2024-01-02"}
        ]}}
        result = engine._parse_prs_from_data(data)
        assert len(result) == 1
        assert result[0]["state"] == "MERGED"

    def test_empty(self, engine):
        assert engine._parse_prs_from_data({"pullRequests": {"nodes": []}}) is None


class TestParseAdditionalFieldsFromData:
    def test_code_of_conduct(self, engine):
        data = {"codeOfConduct": {"name": "Contributor Covenant", "url": "https://..."}}
        result = engine._parse_additional_fields_from_data(data, {})
        assert result["code_of_conduct"]["name"] == "Contributor Covenant"

    def test_funding_links(self, engine):
        data = {"fundingLinks": [{"platform": "GITHUB", "url": "https://..."}]}
        result = engine._parse_additional_fields_from_data(data, {"funding_links": []})
        assert len(result["funding_links"]) == 1

    def test_discussions(self, engine):
        data = {"discussionCategories": {"totalCount": 5}}
        result = engine._parse_additional_fields_from_data(data, {})
        assert result["discussions_count"] == 5

    def test_has_projects(self, engine):
        data = {"hasProjectsEnabled": True}
        result = engine._parse_additional_fields_from_data(data, {})
        assert result["has_projects_enabled"] is True

    def test_vuln_alerts(self, engine):
        data = {"vulnerabilityAlerts": {"totalCount": 3}}
        result = engine._parse_additional_fields_from_data(data, {})
        assert result["vulnerability_alerts_count"] == 3

    def test_security_policy(self, engine):
        data = {"isSecurityPolicyEnabled": True}
        result = engine._parse_additional_fields_from_data(data, {})
        assert result["is_security_policy_enabled"] is True

    def test_merged_prs(self, engine):
        data = {"mergedPullRequests": {"totalCount": 42}}
        result = engine._parse_additional_fields_from_data(data, {})
        assert result["merged_pull_requests_count"] == 42

    def test_no_overwrite_existing(self, engine):
        current = {"code_of_conduct": "existing", "has_projects_enabled": True}
        data = {"codeOfConduct": {"name": "new"}, "hasProjectsEnabled": False}
        result = engine._parse_additional_fields_from_data(data, current)
        assert "code_of_conduct" not in result


class TestExtractTotalCount:
    def test_from_link_header(self, engine):
        resp = MagicMock()
        resp.headers = {"Link": '<https://api.github.com/repos?page=5>; rel="last"'}
        assert engine._extract_total_count(resp) == 5

    def test_no_pagination(self, engine):
        resp = MagicMock()
        resp.headers = {}
        resp.json.return_value = [1, 2, 3]
        assert engine._extract_total_count(resp) == 3

    def test_non_list_response(self, engine):
        resp = MagicMock()
        resp.headers = {}
        resp.json.return_value = {"message": "ok"}
        assert engine._extract_total_count(resp) == 0


class TestIncrementFieldStat:
    def test_increment(self, engine):
        engine._increment_field_stat("test_field")
        assert engine.stats["fields_enriched"]["test_field"] == 1
        engine._increment_field_stat("test_field")
        assert engine.stats["fields_enriched"]["test_field"] == 2


class TestRetryWithBackoff:
    def test_retry_success_first_call(self, engine):
        func = MagicMock(return_value="ok")
        result = engine._retry_with_backoff(func)
        assert result == "ok"
        func.assert_called_once()
