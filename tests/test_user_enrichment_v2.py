"""Tests for UserEnrichmentEngine - extract, process, calculate methods."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime


def _make_engine(**kw):
    with patch('src.github.user_enrichment.GitHubGraphQLClient'):
        from src.github.user_enrichment import UserEnrichmentEngine
        e = UserEnrichmentEngine(
            github_token="tok",
            users_repository=MagicMock(),
            repos_repository=MagicMock(),
            **kw
        )
        return e


class TestExtractBasicFields:
    def test_extracts_name_email(self):
        e = _make_engine()
        u = {}
        e._extract_basic_fields({"name": "Alice", "email": "a@b.com", "bio": "dev"}, u)
        assert u["name"] == "Alice"
        assert u["email"] == "a@b.com"
        assert u["bio"] == "dev"

    def test_converts_camelcase(self):
        e = _make_engine()
        u = {}
        e._extract_basic_fields({"avatarUrl": "http://img", "websiteUrl": "http://web", "twitterUsername": "tw"}, u)
        assert u["avatar_url"] == "http://img"
        assert u["website_url"] == "http://web"
        assert u["twitter_username"] == "tw"

    def test_skips_none(self):
        e = _make_engine()
        u = {}
        e._extract_basic_fields({"name": None, "email": "x@y"}, u)
        assert "name" not in u
        assert u["email"] == "x@y"


class TestExtractCounts:
    def test_all_counts(self):
        e = _make_engine()
        u = {}
        data = {
            "followers": {"totalCount": 100},
            "following": {"totalCount": 50},
            "repositories": {"totalCount": 30},
            "starredRepositories": {"totalCount": 200},
            "organizations": {"totalCount": 3},
            "gists": {"totalCount": 5},
            "packages": {"totalCount": 2},
            "sponsorshipsAsMaintainer": {"totalCount": 1},
            "sponsorshipsAsSponsor": {"totalCount": 0},
            "contributionsCollection": {
                "totalCommitContributions": 500,
                "totalIssueContributions": 20,
                "totalPullRequestContributions": 80,
                "totalPullRequestReviewContributions": 40,
            },
        }
        e._extract_counts(data, u)
        assert u["followers_count"] == 100
        assert u["following_count"] == 50
        assert u["public_repos_count"] == 30
        assert u["total_commit_contributions"] == 500
        assert u["total_pr_contributions"] == 80

    def test_missing_defaults_zero(self):
        e = _make_engine()
        u = {}
        e._extract_counts({}, u)
        assert u["followers_count"] == 0
        assert u["following_count"] == 0


class TestExtractOrganizations:
    def test_extracts_orgs(self):
        e = _make_engine()
        u = {}
        data = {"organizations": {"nodes": [
            {"id": "O1", "login": "qiskit", "name": "Qiskit", "avatarUrl": "http://a", "url": "http://u", "description": "Quantum SDK"}
        ]}}
        e._extract_organizations(data, u)
        assert len(u["organizations"]) == 1
        assert u["organizations"][0]["login"] == "qiskit"

    def test_empty_orgs(self):
        e = _make_engine()
        u = {}
        e._extract_organizations({"organizations": {"nodes": []}}, u)
        assert "organizations" not in u


class TestExtractPinnedRepos:
    def test_extracts_pinned(self):
        e = _make_engine()
        u = {}
        data = {"pinnedItems": {"nodes": [
            {"id": "R1", "name": "repo1", "nameWithOwner": "user/repo1", "description": "A repo",
             "url": "http://r", "stargazerCount": 10, "forkCount": 2,
             "primaryLanguage": {"name": "Python"}, "isPrivate": False, "isFork": False,
             "isArchived": False, "createdAt": "2020-01-01", "updatedAt": "2024-01-01"}
        ]}}
        e._extract_pinned_repos(data, u)
        assert len(u["pinned_repositories"]) == 1
        assert u["pinned_repositories"][0]["primary_language"] == "Python"


class TestExtractTopLanguages:
    def test_calculates_top(self):
        e = _make_engine()
        u = {}
        data = {"repositories": {"nodes": [
            {"primaryLanguage": {"name": "Python"}},
            {"primaryLanguage": {"name": "Python"}},
            {"primaryLanguage": {"name": "Rust"}},
            {"primaryLanguage": None},
        ]}}
        e._extract_top_languages(data, u)
        assert u["top_languages"][0] == "Python"

    def test_empty_repos(self):
        e = _make_engine()
        u = {}
        e._extract_top_languages({"repositories": {"nodes": []}}, u)
        assert "top_languages" not in u


class TestExtractSocialAccounts:
    def test_extracts(self):
        e = _make_engine()
        u = {}
        data = {"socialAccounts": {"nodes": [
            {"provider": "TWITTER", "displayName": "@dev", "url": "http://t"}
        ]}}
        e._extract_social_accounts(data, u)
        assert len(u["social_accounts"]) == 1

    def test_empty(self):
        e = _make_engine()
        u = {}
        e._extract_social_accounts({"socialAccounts": {"nodes": []}}, u)
        assert "social_accounts" not in u


class TestExtractStatus:
    def test_with_status(self):
        e = _make_engine()
        u = {}
        e._extract_status({"status": {"emoji": ":rocket:", "message": "coding"}}, u)
        assert u["status_emoji"] == ":rocket:"

    def test_no_status(self):
        e = _make_engine()
        u = {}
        e._extract_status({"status": None}, u)
        assert "status_emoji" not in u


class TestExtractFlags:
    def test_extracts_flags(self):
        e = _make_engine()
        u = {}
        e._extract_flags({"isHireable": True, "isGitHubStar": False, "isDeveloperProgramMember": True}, u)
        assert u["is_hireable"] is True
        assert u["is_git_hub_star"] is False

    def test_skips_none(self):
        e = _make_engine()
        u = {}
        e._extract_flags({"isHireable": None}, u)
        assert "is_hireable" not in u


class TestBuildEnrichmentBatchQuery:
    def test_builds_query(self):
        e = _make_engine()
        query, variables = e._build_enrichment_batch_query(["alice", "bob"])
        assert "user0" in query
        assert "user1" in query
        assert variables["login0"] == "alice"
        assert variables["login1"] == "bob"


class TestCalculateSocialMetrics:
    def test_with_following(self):
        e = _make_engine()
        m = e._calculate_social_metrics({}, {"followers_count": 100, "following_count": 20})
        assert m["follower_following_ratio"] == 5.0

    def test_zero_following(self):
        e = _make_engine()
        m = e._calculate_social_metrics({}, {"followers_count": 50, "following_count": 0})
        assert m["follower_following_ratio"] == 50

    def test_with_quantum_repos(self):
        e = _make_engine()
        repos = [
            {"role": "owner", "stars": 100, "contributions": 50},
            {"role": "collaborator", "stars": 30, "contributions": 10},
        ]
        m = e._calculate_social_metrics({}, {"followers_count": 0, "following_count": 0, "quantum_repositories": repos})
        assert "stars_per_repo" in m


class TestCalculateQuantumExpertise:
    def test_no_repos(self):
        e = _make_engine()
        assert e._calculate_quantum_expertise({}, {}) is None

    def test_with_repos_and_orgs(self):
        e = _make_engine()
        updates = {
            "quantum_repositories": [
                {"role": "owner", "stars": 50, "contributions": 100},
                {"role": "collaborator", "stars": 10, "contributions": 20},
            ],
            "organizations": [
                {"name": "Qiskit Community", "description": "quantum SDK"},
            ],
        }
        score = e._calculate_quantum_expertise({}, updates)
        assert score is not None
        assert score > 0
        assert score <= 100

    def test_capped_at_100(self):
        e = _make_engine()
        updates = {
            "quantum_repositories": [{"role": "owner", "stars": 9999, "contributions": 9999}] * 20,
            "organizations": [{"name": "quantum org", "description": "quantum"} for _ in range(10)],
        }
        score = e._calculate_quantum_expertise({}, updates)
        assert score == 100.0


class TestFinalizeStats:
    def test_finalize(self):
        e = _make_engine()
        e.stats["start_time"] = datetime(2024, 1, 1, 0, 0, 0)
        e.stats["total_processed"] = 10
        e.stats["total_enriched"] = 8
        result = e._finalize_stats()
        assert result["end_time"] is not None
        assert "duration_seconds" in result


class TestCleanEmptyArrays:
    def test_cleans(self):
        e = _make_engine()
        user = {"_id": "u1", "organizations": [], "repos": [], "name": "Alice"}
        e._clean_empty_arrays(user)
        e.users_repository.collection.update_one.assert_called_once()

    def test_no_empty(self):
        e = _make_engine()
        user = {"_id": "u1", "name": "Bob"}
        e._clean_empty_arrays(user)
        e.users_repository.collection.update_one.assert_not_called()


class TestFetchUserData:
    def test_success(self):
        e = _make_engine()
        e.graphql_client.execute_query.return_value = {
            "data": {"user": {"login": "alice", "name": "Alice"}}
        }
        result = e._fetch_user_data("alice")
        assert result["login"] == "alice"

    def test_error_response(self):
        e = _make_engine()
        e.graphql_client.execute_query.return_value = {"errors": [{"message": "not found"}]}
        assert e._fetch_user_data("ghost") is None

    def test_exception(self):
        e = _make_engine()
        e.graphql_client.execute_query.side_effect = Exception("network")
        assert e._fetch_user_data("fail") is None


class TestEnrichSingleUser:
    def test_no_login(self):
        e = _make_engine()
        assert e._enrich_single_user({"_id": "x"}) is False
        assert e.stats["total_errors"] == 1

    def test_no_graphql_data(self):
        e = _make_engine()
        e.graphql_client.execute_query.return_value = {"errors": [{"message": "err"}]}
        assert e._enrich_single_user({"_id": "x", "login": "ghost"}) is False


class TestFindQuantumRepos:
    def test_finds_repos(self):
        e = _make_engine()
        e.repos_repository.collection.find.return_value = [
            {"id": "R1", "name": "qiskit-terra", "name_with_owner": "qiskit/terra",
             "owner": {"login": "alice"}, "stargazer_count": 50, "primary_language": "Python"}
        ]
        user = {"login": "alice", "extracted_from": [{"repo_id": "R1", "contributions": 30}]}
        result = e._find_quantum_repositories("alice", user)
        assert result is not None
        assert result[0]["role"] == "owner"
        assert result[0]["contributions"] == 30

    def test_no_repos(self):
        e = _make_engine()
        e.repos_repository.collection.find.return_value = []
        result = e._find_quantum_repositories("alice", {"login": "alice"})
        assert result is None


class TestProcessEnrichmentData:
    def test_success(self):
        e = _make_engine()
        e.repos_repository.collection.find.return_value = []
        graphql_data = {
            "name": "Alice", "email": "a@b.com",
            "followers": {"totalCount": 10}, "following": {"totalCount": 5},
            "repositories": {"totalCount": 3, "nodes": []},
            "starredRepositories": {"totalCount": 1},
            "organizations": {"totalCount": 0, "nodes": []},
            "gists": {"totalCount": 0}, "packages": {"totalCount": 0},
            "sponsorshipsAsMaintainer": {"totalCount": 0},
            "sponsorshipsAsSponsor": {"totalCount": 0},
            "contributionsCollection": {},
        }
        user = {"_id": "u1", "login": "alice"}
        result = e._process_enrichment_data(user, graphql_data)
        assert result is True
        e.users_repository.collection.update_one.assert_called_once()
