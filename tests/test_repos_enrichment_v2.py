"""Tests for EnrichmentEngine untested methods - repos enrichment coverage."""
import threading
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

from src.github.repositories_enrichment import EnrichmentEngine


def _make_engine(**kwargs):
    """Create engine with mocked dependencies."""
    with patch.object(EnrichmentEngine, '__init__', lambda self, **kw: None):
        engine = EnrichmentEngine.__new__(EnrichmentEngine)
    engine.github_token = "ghp_fake"
    engine.repos_repository = MagicMock()
    engine.config = kwargs.get("config", {})
    engine.batch_size = 5
    engine.progress_callback = kwargs.get("progress_callback")
    engine.cancel_event = kwargs.get("cancel_event")
    engine.graphql_client = MagicMock()
    engine.session = MagicMock()
    engine._stats_lock = threading.Lock()
    engine._rate_limit_lock = threading.Lock()
    engine._rate_limit_until = 0
    engine.max_retries = 3
    engine.base_backoff = 0.01
    engine.rate_limit_threshold = 100
    engine.last_rate_limit_check = None
    engine.current_rate_limit = None
    engine.stats = {
        "total_processed": 0, "total_enriched": 0, "total_errors": 0,
        "total_retries": 0, "total_rate_limit_waits": 0,
        "fields_enriched": {}, "start_time": None, "end_time": None,
    }
    return engine


# ==================== _fetch_repo_graphql_combined ====================

class TestFetchRepoGraphqlCombined:
    def test_success(self):
        engine = _make_engine()
        engine.REPO_ENRICHMENT_SUPER_QUERY = "query { ... }"
        engine.graphql_client.execute_query.return_value = {
            "data": {"repository": {"id": "R_1", "name": "test"}}
        }
        result = engine._fetch_repo_graphql_combined("owner/repo")
        assert result == {"id": "R_1", "name": "test"}

    def test_error_response(self):
        engine = _make_engine()
        engine.REPO_ENRICHMENT_SUPER_QUERY = "query { ... }"
        engine.graphql_client.execute_query.return_value = {
            "errors": [{"message": "not found"}]
        }
        result = engine._fetch_repo_graphql_combined("owner/repo")
        assert result is None

    def test_exception(self):
        engine = _make_engine()
        engine.REPO_ENRICHMENT_SUPER_QUERY = "query { ... }"
        engine.graphql_client.execute_query.side_effect = Exception("boom")
        result = engine._fetch_repo_graphql_combined("owner/repo")
        assert result is None


# ==================== _fetch_owner_type_rest ====================

class TestFetchOwnerTypeRest:
    def test_returns_organization(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"type": "Organization"}
        engine.session.get.return_value = resp
        result = engine._fetch_owner_type_rest("qiskit/terra")
        assert result == "Organization"

    def test_returns_user(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"type": "User"}
        engine.session.get.return_value = resp
        assert engine._fetch_owner_type_rest("bob/repo") == "User"

    def test_error_returns_none(self):
        engine = _make_engine()
        resp = MagicMock(status_code=404)
        engine.session.get.return_value = resp
        assert engine._fetch_owner_type_rest("x/y") is None

    def test_exception_returns_none(self):
        engine = _make_engine()
        engine.session.get.side_effect = Exception("net")
        assert engine._fetch_owner_type_rest("x/y") is None


# ==================== _fetch_license_info_rest ====================

class TestFetchLicenseInfoRest:
    def test_returns_license(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "license": {"key": "mit", "name": "MIT", "spdx_id": "MIT", "url": "https://..."}
        }
        engine.session.get.return_value = resp
        result = engine._fetch_license_info_rest("owner/repo")
        assert result["key"] == "mit"
        assert result["spdx_id"] == "MIT"

    def test_no_license(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"license": None}
        engine.session.get.return_value = resp
        assert engine._fetch_license_info_rest("owner/repo") is None

    def test_error_code(self):
        engine = _make_engine()
        resp = MagicMock(status_code=403)
        engine.session.get.return_value = resp
        assert engine._fetch_license_info_rest("owner/repo") is None


# ==================== _fetch_additional_fields_rest ====================

class TestFetchAdditionalFieldsRest:
    def test_gets_subscribers_and_network(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "subscribers_count": 50, "network_count": 30,
            "has_projects": True, "has_discussions": True,
        }
        engine.session.get.return_value = resp
        current = {"subscribers_count": 0, "network_count": 0}
        result = engine._fetch_additional_fields_rest("o/r", current)
        assert result["subscribers_count"] == 50
        assert result["network_count"] == 30
        assert result["has_projects_enabled"] is True

    def test_fork_with_parent(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "parent": {"node_id": "P_1", "full_name": "orig/repo"},
            "subscribers_count": 0, "network_count": 0,
        }
        engine.session.get.return_value = resp
        current = {"is_fork": True, "subscribers_count": 0, "network_count": 0}
        result = engine._fetch_additional_fields_rest("o/r", current)
        assert result["parent_id"] == "P_1"

    def test_403_returns_empty(self):
        engine = _make_engine()
        resp = MagicMock(status_code=403)
        resp.text = "rate limit"
        engine.session.get.return_value = resp
        result = engine._fetch_additional_fields_rest("o/r", {})
        assert result == {}

    def test_security_analysis(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "subscribers_count": 0, "network_count": 0,
            "security_and_analysis": {"advanced_security": {"status": "enabled"}},
        }
        engine.session.get.return_value = resp
        result = engine._fetch_additional_fields_rest("o/r", {})
        assert result["is_security_policy_enabled"] is True


# ==================== _fetch_additional_fields_graphql ====================

class TestFetchAdditionalFieldsGraphql:
    def test_full_data(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = {
            "data": {"repository": {
                "codeOfConduct": {"name": "Contributor Covenant", "url": "https://..."},
                "fundingLinks": [{"platform": "GITHUB", "url": "https://fund"}],
                "discussionCategories": {"totalCount": 5},
                "hasProjectsEnabled": True,
                "vulnerabilityAlerts": {"totalCount": 2},
                "isSecurityPolicyEnabled": True,
                "mergedPullRequests": {"totalCount": 100},
            }}
        }
        current = {}
        result = engine._fetch_additional_fields_graphql("owner/repo", current)
        assert "code_of_conduct" in result
        assert result["discussions_count"] == 5
        assert result["merged_pull_requests_count"] == 100

    def test_empty_repo_data(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = {
            "data": {"repository": None}
        }
        result = engine._fetch_additional_fields_graphql("owner/repo", {})
        assert result == {}

    def test_exception(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.side_effect = Exception("fail")
        result = engine._fetch_additional_fields_graphql("owner/repo", {})
        assert result == {}

    def test_existing_fields_not_overwritten(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = {
            "data": {"repository": {
                "codeOfConduct": {"name": "CC", "url": "u"},
                "fundingLinks": [],
                "discussionCategories": {"totalCount": 0},
                "hasProjectsEnabled": False,
                "vulnerabilityAlerts": {"totalCount": 0},
                "isSecurityPolicyEnabled": False,
                "mergedPullRequests": {"totalCount": 0},
            }}
        }
        current = {"code_of_conduct": {"name": "old"}, "discussions_count": 10}
        result = engine._fetch_additional_fields_graphql("owner/repo", current)
        assert "code_of_conduct" not in result  # not overwritten
        assert "discussions_count" not in result


# ==================== _fetch_merged_prs_count_rest ====================

class TestFetchMergedPrsCountRest:
    def test_success(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"total_count": 42}
        engine.session.get.return_value = resp
        assert engine._fetch_merged_prs_count_rest("o/r") == 42

    def test_error(self):
        engine = _make_engine()
        resp = MagicMock(status_code=500)
        engine.session.get.return_value = resp
        assert engine._fetch_merged_prs_count_rest("o/r") == 0

    def test_exception(self):
        engine = _make_engine()
        engine.session.get.side_effect = Exception("net")
        assert engine._fetch_merged_prs_count_rest("o/r") == 0


# ==================== _fetch_contributors_rest ====================

class TestFetchContributorsRest:
    def test_single_page(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = [
            {"login": "alice", "node_id": "U_1", "avatar_url": "url", "type": "User", "contributions": 10},
        ]
        resp.headers = {"Link": ""}
        engine.session.get.return_value = resp
        result = engine._fetch_contributors_rest("o/r")
        assert len(result) == 1
        assert result[0]["login"] == "alice"

    def test_multi_page(self):
        engine = _make_engine()
        page1 = MagicMock(status_code=200)
        page1.json.return_value = [{"login": "a", "node_id": "1", "contributions": 5, "type": "User", "avatar_url": "u"}]
        page1.headers = {"Link": '<url?page=2>; rel="next"'}
        page2 = MagicMock(status_code=200)
        page2.json.return_value = [{"login": "b", "node_id": "2", "contributions": 3, "type": "User", "avatar_url": "u"}]
        page2.headers = {"Link": ""}
        engine.session.get.side_effect = [page1, page2]
        result = engine._fetch_contributors_rest("o/r")
        assert len(result) == 2

    def test_max_contributors_limit(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = [
            {"login": f"u{i}", "node_id": f"N{i}", "contributions": i, "type": "User", "avatar_url": "u"}
            for i in range(5)
        ]
        resp.headers = {"Link": '<url?page=2>; rel="next"'}
        engine.session.get.return_value = resp
        result = engine._fetch_contributors_rest("o/r", max_contributors=3)
        assert len(result) == 3

    def test_403_returns_empty(self):
        engine = _make_engine()
        resp = MagicMock(status_code=403)
        resp.text = "rate limit"
        engine.session.get.return_value = resp
        result = engine._fetch_contributors_rest("o/r")
        assert result == []

    def test_empty_repo(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = []
        resp.headers = {}
        engine.session.get.return_value = resp
        result = engine._fetch_contributors_rest("o/r")
        assert result == []


# ==================== _fetch_mentionable_users_graphql ====================

class TestFetchMentionableUsersGraphql:
    def _graphql_page(self, users, has_next=False, cursor="cur"):
        return {
            "data": {"repository": {"mentionableUsers": {
                "totalCount": len(users) + (10 if has_next else 0),
                "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                "nodes": [{"id": f"U_{u}", "login": u, "avatarUrl": "img", "name": u, "email": None} for u in users],
            }}}
        }

    def test_single_page(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = self._graphql_page(["alice", "bob"])
        result = engine._fetch_mentionable_users_graphql("o/r")
        assert len(result) == 2

    def test_multi_page(self):
        engine = _make_engine()
        # Call 1: initial (gets totalCount), Call 2: loop iter 1 (after=None),
        # Call 3: loop iter 2 (after=c1)
        engine.graphql_client.execute_query.side_effect = [
            self._graphql_page(["a"], has_next=True, cursor="c1"),
            self._graphql_page(["a"], has_next=True, cursor="c1"),
            self._graphql_page(["b"], has_next=False),
        ]
        result = engine._fetch_mentionable_users_graphql("o/r")
        assert len(result) == 2

    def test_max_users_limit(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = self._graphql_page(["a", "b", "c"])
        result = engine._fetch_mentionable_users_graphql("o/r", max_users=2)
        assert len(result) == 2

    def test_empty_result(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = None
        result = engine._fetch_mentionable_users_graphql("o/r")
        assert result == []

    def test_exception(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.side_effect = Exception("fail")
        result = engine._fetch_mentionable_users_graphql("o/r")
        assert result == []


# ==================== _fetch_collaborators_combined ====================

class TestFetchCollaboratorsCombined:
    def test_combines_contributors_and_mentionable(self):
        engine = _make_engine()
        engine._fetch_contributors_rest = MagicMock(return_value=[
            {"login": "alice", "id": "1", "avatar_url": "u", "type": "User", "contributions": 10},
        ])
        engine._fetch_mentionable_users_graphql = MagicMock(return_value=[
            {"login": "bob", "id": "2", "avatar_url": "u", "type": "User"},
        ])
        result = engine._fetch_collaborators_combined("o/r")
        assert result["count"] == 2
        logins = [c["login"] for c in result["collaborators"]]
        assert "alice" in logins
        assert "bob" in logins

    def test_deduplicates(self):
        engine = _make_engine()
        engine._fetch_contributors_rest = MagicMock(return_value=[
            {"login": "alice", "id": "1", "avatar_url": "u", "type": "User", "contributions": 10},
        ])
        engine._fetch_mentionable_users_graphql = MagicMock(return_value=[
            {"login": "alice", "id": "1", "avatar_url": "u", "type": "User"},
        ])
        result = engine._fetch_collaborators_combined("o/r")
        assert result["count"] == 1

    def test_exception_returns_none(self):
        engine = _make_engine()
        engine._fetch_contributors_rest = MagicMock(side_effect=Exception("fail"))
        result = engine._fetch_collaborators_combined("o/r")
        assert result is None


# ==================== _fetch_repo_info_combined ====================

class TestFetchRepoInfoCombined:
    def test_full_data(self):
        engine = _make_engine()
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            "owner": {"type": "Organization"},
            "license": {"key": "mit", "name": "MIT", "spdx_id": "MIT", "url": "u"},
            "subscribers_count": 20, "network_count": 10,
            "has_projects": True, "has_discussions": True,
        }
        engine.session.get.return_value = resp
        current = {"subscribers_count": 0, "network_count": 0}
        result = engine._fetch_repo_info_combined("o/r", current)
        assert result["owner_type"] == "Organization"
        assert result["license_info"]["key"] == "mit"
        assert result["additional_fields"]["subscribers_count"] == 20

    def test_404_returns_partial(self):
        engine = _make_engine()
        resp = MagicMock(status_code=404)
        engine.session.get.return_value = resp
        result = engine._fetch_repo_info_combined("o/r", {})
        assert result.get("owner_type") is None

    def test_403_raises(self):
        engine = _make_engine()
        import requests as req
        resp = MagicMock(status_code=403)
        resp.text = "rate limit"
        engine.session.get.return_value = resp
        result = engine._fetch_repo_info_combined("o/r", {})
        # Should catch and return partial result
        assert isinstance(result, dict)


# ==================== _enrich_repository (main orchestrator) ====================

class TestEnrichRepository:
    def test_skip_no_name_with_owner(self):
        engine = _make_engine()
        engine._enrich_repository({"id": "1"})
        engine.repos_repository.collection.update_one.assert_not_called()

    def test_skip_recently_enriched(self):
        engine = _make_engine()
        repo = {
            "id": "1", "name_with_owner": "o/r",
            "enrichment_status": {
                "last_enriched": datetime.now().isoformat(),
                "is_complete": True,
            },
        }
        engine._enrich_repository(repo)
        engine.repos_repository.collection.update_one.assert_not_called()

    def test_full_enrichment_flow(self):
        engine = _make_engine()
        engine._retry_with_backoff = MagicMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
        engine._calculate_fields = MagicMock(return_value={"age_days": 100})
        engine._generate_urls = MagicMock(return_value={"api_url": "u"})
        engine._enrich_owner_info = MagicMock(return_value={})
        engine._fix_simple_fields = MagicMock(return_value={})
        engine._fetch_readme_rest = MagicMock(return_value="# README")
        engine._fetch_releases_rest = MagicMock(return_value={"releases": [], "count": 0, "latest": None})
        engine._fetch_branches_count_rest = MagicMock(return_value=5)
        engine._fetch_tags_count_rest = MagicMock(return_value=3)
        engine._fetch_pull_request_counts_rest = MagicMock(return_value={"open_pr": 2})
        engine._fetch_repo_info_combined = MagicMock(return_value={"owner_type": "User", "additional_fields": {}})
        engine._fetch_repo_graphql_combined = MagicMock(return_value=None)
        engine._fetch_collaborators_combined = MagicMock(return_value={"collaborators": [], "count": 0})
        engine._increment_field_stat = MagicMock()

        repo = {"id": "1", "name_with_owner": "o/r"}
        engine._enrich_repository(repo)
        engine.repos_repository.collection.update_one.assert_called_once()

    def test_enrichment_with_graphql_prefetch(self):
        engine = _make_engine()
        engine._retry_with_backoff = MagicMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))
        engine._calculate_fields = MagicMock(return_value={})
        engine._generate_urls = MagicMock(return_value={})
        engine._enrich_owner_info = MagicMock(return_value={})
        engine._fix_simple_fields = MagicMock(return_value={})
        engine._fetch_readme_rest = MagicMock(return_value=None)
        engine._fetch_releases_rest = MagicMock(return_value=None)
        engine._fetch_branches_count_rest = MagicMock(return_value=0)
        engine._fetch_tags_count_rest = MagicMock(return_value=0)
        engine._fetch_pull_request_counts_rest = MagicMock(return_value=None)
        engine._fetch_repo_info_combined = MagicMock(return_value={})
        graphql_data = {"key": "value"}
        engine._fetch_repo_graphql_combined = MagicMock(return_value=graphql_data)
        engine._parse_commits_from_data = MagicMock(return_value=[{"committed_date": "2024-01-01"}])
        engine._parse_issues_from_data = MagicMock(return_value=[])
        engine._parse_prs_from_data = MagicMock(return_value=[])
        engine._parse_additional_fields_from_data = MagicMock(return_value={"extra": 1})
        engine._fetch_collaborators_combined = MagicMock(return_value=None)
        engine._increment_field_stat = MagicMock()

        repo = {"id": "1", "name_with_owner": "o/r"}
        engine._enrich_repository(repo)
        engine._parse_commits_from_data.assert_called_once_with(graphql_data)
        engine.repos_repository.collection.update_one.assert_called_once()


# ==================== _fetch_recent_commits_graphql ====================

class TestFetchRecentCommitsGraphql:
    def test_success(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = {
            "data": {"repository": {"defaultBranchRef": {"target": {"history": {"nodes": [
                {"oid": "abc", "message": "fix", "committedDate": "2024-01-01",
                 "author": {"name": "Alice", "email": "a@a.com", "user": {"login": "alice"}}}
            ]}}}}}
        }
        result = engine._fetch_recent_commits_graphql("o/r")
        assert len(result) == 1

    def test_no_data(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = {"data": {"repository": None}}
        result = engine._fetch_recent_commits_graphql("o/r")
        assert result is None

    def test_exception(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.side_effect = Exception("net")
        result = engine._fetch_recent_commits_graphql("o/r")
        assert result is None


# ==================== _fetch_recent_issues_graphql ====================

class TestFetchRecentIssuesGraphql:
    def test_success(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = {
            "data": {"repository": {"issues": {"nodes": [
                {"number": 1, "title": "bug", "state": "OPEN", "createdAt": "2024-01-01",
                 "author": {"login": "alice"}, "labels": {"nodes": [{"name": "bug"}]}}
            ]}}}
        }
        result = engine._fetch_recent_issues_graphql("o/r")
        assert len(result) == 1

    def test_exception(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.side_effect = Exception("err")
        result = engine._fetch_recent_issues_graphql("o/r")
        assert result is None


# ==================== _fetch_recent_pull_requests_graphql ====================

class TestFetchRecentPRsGraphql:
    def test_success(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = {
            "data": {"repository": {"pullRequests": {"nodes": [
                {"number": 1, "title": "feat", "state": "MERGED", "createdAt": "2024-01-01",
                 "mergedAt": "2024-01-02", "author": {"login": "alice"}}
            ]}}}
        }
        result = engine._fetch_recent_pull_requests_graphql("o/r")
        assert len(result) == 1

    def test_exception(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.side_effect = Exception("err")
        result = engine._fetch_recent_pull_requests_graphql("o/r")
        assert result is None
