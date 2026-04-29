"""
Tests for UserEnrichmentEngine pure-logic methods.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


@pytest.fixture
def user_engine():
    with patch('src.github.user_enrichment.GitHubGraphQLClient'):
        from src.github.user_enrichment import UserEnrichmentEngine
        engine = UserEnrichmentEngine(
            github_token="ghp_test",
            users_repository=MagicMock(),
            repos_repository=MagicMock(),
        )
        return engine


class TestBuildEnrichmentBatchQuery:
    def test_single_login(self, user_engine):
        query, variables = user_engine._build_enrichment_batch_query(["octocat"])
        assert "$login0: String!" in query
        assert "user0: user(login: $login0)" in query
        assert variables == {"login0": "octocat"}

    def test_multiple_logins(self, user_engine):
        logins = ["alice", "bob", "charlie"]
        query, variables = user_engine._build_enrichment_batch_query(logins)
        for i, login in enumerate(logins):
            assert f"$login{i}: String!" in query
            assert f"user{i}: user(login: $login{i})" in query
            assert variables[f"login{i}"] == login

    def test_empty_logins(self, user_engine):
        query, variables = user_engine._build_enrichment_batch_query([])
        assert variables == {}

    def test_query_has_fragment(self, user_engine):
        query, _ = user_engine._build_enrichment_batch_query(["test"])
        assert "UserEnrichmentFields" in query


class TestExtractBasicFields:
    def test_all_fields_present(self, user_engine):
        data = {
            "name": "Test User",
            "email": "test@example.com",
            "bio": "A bio",
            "company": "Acme Corp",
            "location": "NYC",
            "pronouns": "they/them",
            "avatarUrl": "https://example.com/avatar.png",
            "websiteUrl": "https://example.com",
            "twitterUsername": "testuser",
            "createdAt": "2020-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
        }
        updates = {}
        user_engine._extract_basic_fields(data, updates)
        assert updates["name"] == "Test User"
        assert updates["email"] == "test@example.com"
        assert updates["avatar_url"] == "https://example.com/avatar.png"
        assert updates["website_url"] == "https://example.com"
        assert updates["twitter_username"] == "testuser"
        assert updates["created_at"] == "2020-01-01T00:00:00Z"
        assert updates["updated_at"] == "2024-01-01T00:00:00Z"

    def test_missing_fields_not_set(self, user_engine):
        data = {"name": "Test"}
        updates = {}
        user_engine._extract_basic_fields(data, updates)
        assert "email" not in updates
        assert "avatar_url" not in updates

    def test_none_values_ignored(self, user_engine):
        data = {"name": None, "email": None}
        updates = {}
        user_engine._extract_basic_fields(data, updates)
        assert "name" not in updates
        assert "email" not in updates


class TestExtractCounts:
    def test_all_counts(self, user_engine):
        data = {
            "followers": {"totalCount": 100},
            "following": {"totalCount": 50},
            "repositories": {"totalCount": 30},
            "starredRepositories": {"totalCount": 200},
            "organizations": {"totalCount": 3},
            "gists": {"totalCount": 10},
            "packages": {"totalCount": 2},
            "sponsorshipsAsMaintainer": {"totalCount": 5},
            "sponsorshipsAsSponsor": {"totalCount": 1},
            "contributionsCollection": {
                "totalCommitContributions": 1500,
                "totalIssueContributions": 100,
                "totalPullRequestContributions": 200,
                "totalPullRequestReviewContributions": 50,
            },
        }
        updates = {}
        user_engine._extract_counts(data, updates)
        assert updates["followers_count"] == 100
        assert updates["following_count"] == 50
        assert updates["public_repos_count"] == 30
        assert updates["starred_repos_count"] == 200
        assert updates["organizations_count"] == 3
        assert updates["total_commit_contributions"] == 1500
        assert updates["total_pr_contributions"] == 200

    def test_missing_counts_default_zero(self, user_engine):
        data = {}
        updates = {}
        user_engine._extract_counts(data, updates)
        assert updates["followers_count"] == 0
        assert updates["public_repos_count"] == 0

    def test_no_contributions_collection(self, user_engine):
        data = {"followers": {"totalCount": 5}}
        updates = {}
        user_engine._extract_counts(data, updates)
        assert updates["followers_count"] == 5
        assert "total_commit_contributions" not in updates


class TestFinalizeStats:
    def test_finalize_returns_stats(self, user_engine):
        user_engine.stats = {
            "start_time": datetime(2025, 1, 1, 10, 0, 0),
            "end_time": None,
            "total_processed": 100,
            "total_enriched": 90,
            "total_errors": 10,
        }
        result = user_engine._finalize_stats()
        assert result["end_time"] is not None
        assert result["duration_seconds"] > 0
        assert result["total_processed"] == 100

    def test_finalize_no_start_time(self, user_engine):
        user_engine.stats = {
            "start_time": None,
            "end_time": None,
            "total_processed": 0,
            "total_enriched": 0,
            "total_errors": 0,
        }
        result = user_engine._finalize_stats()
        assert "duration_seconds" not in result


class TestCleanEmptyArrays:
    def test_cleans_arrays(self, user_engine):
        user = {"_id": "123", "field_a": [], "field_b": "value", "field_c": []}
        user_engine._clean_empty_arrays(user)
        user_engine.users_repository.collection.update_one.assert_called_once()
        call_args = user_engine.users_repository.collection.update_one.call_args
        assert call_args[0][0] == {"_id": "123"}
        set_fields = call_args[0][1]["$set"]
        assert set_fields["field_a"] is None
        assert set_fields["field_c"] is None

    def test_no_empty_arrays(self, user_engine):
        user = {"_id": "123", "field_a": [1, 2], "field_b": "value"}
        user_engine._clean_empty_arrays(user)
        user_engine.users_repository.collection.update_one.assert_not_called()
