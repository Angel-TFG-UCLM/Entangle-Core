"""
Tests for UserIngestionEngine (_is_bot, _build_batch_query) and
OrganizationIngestionEngine pure-logic methods.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestUserIngestionIsBot:
    @pytest.fixture
    def engine(self):
        from src.github.user_ingestion import UserIngestionEngine
        return UserIngestionEngine(
            github_client=MagicMock(),
            repos_repository=MagicMock(),
            users_repository=MagicMock(),
        )

    def test_bot_type(self, engine):
        assert engine._is_bot({"login": "mybot", "type": "Bot"}) is True

    def test_bot_suffix(self, engine):
        assert engine._is_bot({"login": "dependabot[bot]", "type": "User"}) is True

    def test_dependabot_pattern(self, engine):
        assert engine._is_bot({"login": "dependabot-preview", "type": "User"}) is True

    def test_renovate_pattern(self, engine):
        assert engine._is_bot({"login": "renovate", "type": "User"}) is True

    def test_github_actions(self, engine):
        assert engine._is_bot({"login": "github-actions", "type": "User"}) is True

    def test_snyk_bot(self, engine):
        assert engine._is_bot({"login": "snyk-bot", "type": "User"}) is True

    def test_normal_user(self, engine):
        assert engine._is_bot({"login": "johndoe", "type": "User"}) is False

    def test_empty_login(self, engine):
        assert engine._is_bot({"login": "", "type": ""}) is False

    def test_auto_prefix(self, engine):
        assert engine._is_bot({"login": "auto-merger", "type": "User"}) is True

    def test_codecov(self, engine):
        assert engine._is_bot({"login": "codecov-commenter", "type": "User"}) is True

    def test_case_insensitive(self, engine):
        assert engine._is_bot({"login": "DependaBot", "type": "User"}) is True


class TestUserIngestionBuildBatchQuery:
    @pytest.fixture
    def engine(self):
        from src.github.user_ingestion import UserIngestionEngine
        return UserIngestionEngine(
            github_client=MagicMock(),
            repos_repository=MagicMock(),
            users_repository=MagicMock(),
        )

    def test_single_login(self, engine):
        query, variables = engine._build_batch_query(["octocat"])
        assert "$login0: String!" in query
        assert "user0: user(login: $login0)" in query
        assert variables["login0"] == "octocat"
        assert "UserBasicFields" in query

    def test_multiple_logins(self, engine):
        logins = ["alice", "bob", "charlie"]
        query, variables = engine._build_batch_query(logins)
        for i, login in enumerate(logins):
            assert f"user{i}" in query
            assert variables[f"login{i}"] == login
        assert len(variables) == 3

    def test_empty_list(self, engine):
        query, variables = engine._build_batch_query([])
        assert variables == {}

    def test_fragment_includes_fields(self, engine):
        query, _ = engine._build_batch_query(["test"])
        assert "login" in query
        assert "name" in query
        assert "email" in query
        assert "followers" in query


class TestOrgIngestionInit:
    @patch('src.github.organization_ingestion.GitHubGraphQLClient')
    def test_stats_initialized(self, mock_gql):
        from src.github.organization_ingestion import OrganizationIngestionEngine
        engine = OrganizationIngestionEngine(
            github_token="ghp_test",
            users_repository=MagicMock(),
            organizations_repository=MagicMock(),
        )
        assert engine.stats["total_discovered"] == 0
        assert engine.stats["total_inserted"] == 0
        assert engine.stats["total_errors"] == 0

    @patch('src.github.organization_ingestion.GitHubGraphQLClient')
    def test_from_scratch_flag(self, mock_gql):
        from src.github.organization_ingestion import OrganizationIngestionEngine
        engine = OrganizationIngestionEngine(
            github_token="ghp_test",
            users_repository=MagicMock(),
            organizations_repository=MagicMock(),
            from_scratch=True,
        )
        assert engine.from_scratch is True
