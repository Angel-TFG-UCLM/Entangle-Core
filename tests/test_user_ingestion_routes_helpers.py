"""Tests for user_ingestion.py methods and routes.py helper functions."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def user_engine():
    with patch('src.github.user_ingestion.GitHubGraphQLClient') as mock_cls:
        mock_gql = MagicMock()
        mock_gql.get_rate_limit.return_value = {"remaining": 4900}
        mock_cls.return_value = mock_gql
        from src.github.user_ingestion import UserIngestionEngine
        e = UserIngestionEngine(
            github_client=mock_gql,
            repos_repository=MagicMock(),
            users_repository=MagicMock(),
            batch_size=10,
        )
        return e


class TestFormatUserData:
    def test_basic_format(self, user_engine):
        data = {
            "id": "MDQ6VXNlcjE=", "login": "octocat", "name": "Octocat",
            "email": "octo@cat.com", "bio": "I code", "company": "GitHub",
            "location": "SF", "url": "https://github.com/octocat",
            "websiteUrl": "https://octocat.com", "twitterUsername": "octocat",
            "avatarUrl": "https://avatars...", "createdAt": "2020-01-01",
            "updatedAt": "2024-01-01",
            "followers": {"totalCount": 100}, "following": {"totalCount": 50},
            "repositories": {"totalCount": 30},
        }
        result = user_engine._format_user_data(data)
        assert result["login"] == "octocat"
        assert result["followers_count"] == 100
        assert result["following_count"] == 50
        assert result["public_repos_count"] == 30
        assert result["is_enriched"] is False
        assert result["public_gists_count"] is None

    def test_empty_data(self, user_engine):
        result = user_engine._format_user_data({})
        assert result["login"] is None
        assert result["followers_count"] == 0
        assert result["is_enriched"] is False

    def test_partial_data(self, user_engine):
        data = {"login": "test", "followers": {}, "repositories": {}}
        result = user_engine._format_user_data(data)
        assert result["login"] == "test"
        assert result["followers_count"] == 0


class TestUserIngestionIsBotExtended:
    def test_github_actions(self, user_engine):
        assert user_engine._is_bot({"login": "github-actions[bot]"}) is True

    def test_dependabot(self, user_engine):
        assert user_engine._is_bot({"login": "dependabot"}) is True

    def test_normal_user(self, user_engine):
        assert user_engine._is_bot({"login": "octocat"}) is False


class TestUserEngineCleanup:
    def test_cleanup_calls_delete(self, user_engine):
        user_engine.users_repository.count_documents.return_value = 5
        user_engine.users_repository.delete_many.return_value = 5
        user_engine._cleanup_collection()
        user_engine.users_repository.delete_many.assert_called_once()


class TestAreeSiblingOrgs:
    def test_same_name(self):
        from src.api.routes import _are_sibling_orgs
        assert _are_sibling_orgs("Qiskit", "qiskit") is True

    def test_sibling_prefix(self):
        from src.api.routes import _are_sibling_orgs
        assert _are_sibling_orgs("Qiskit", "qiskit-community") is True

    def test_different_orgs(self):
        from src.api.routes import _are_sibling_orgs
        assert _are_sibling_orgs("Microsoft", "Google") is False

    def test_empty_inputs(self):
        from src.api.routes import _are_sibling_orgs
        assert _are_sibling_orgs("", "test") is False
        assert _are_sibling_orgs(None, "test") is False

    def test_short_names(self):
        from src.api.routes import _are_sibling_orgs
        assert _are_sibling_orgs("ab", "ab-test") is False

    def test_prefix_ratio_too_high(self):
        from src.api.routes import _are_sibling_orgs
        assert _are_sibling_orgs("intel", "intelligentquantumcomputing") is False


class TestAdminHelpers:
    @patch('src.api.admin_routes.db')
    def test_verify_password_no_doc(self, mock_db):
        mock_db.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = None
        mock_db.get_collection.return_value = coll
        from src.api.admin_routes import _verify_password
        assert _verify_password("test") is False

    @patch('src.api.admin_routes.db')
    def test_has_password_true(self, mock_db):
        mock_db.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.count_documents.return_value = 1
        mock_db.get_collection.return_value = coll
        from src.api.admin_routes import _has_password_set
        assert _has_password_set() is True

    @patch('src.api.admin_routes.db')
    def test_has_password_false(self, mock_db):
        mock_db.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.count_documents.return_value = 0
        mock_db.get_collection.return_value = coll
        from src.api.admin_routes import _has_password_set
        assert _has_password_set() is False

    def test_validate_token_no_tokens(self):
        from src.api.admin_routes import _validate_admin_token
        result = _validate_admin_token("fake-token")
        assert result is False

    @patch('src.api.admin_routes.db')
    def test_verify_password_exception(self, mock_db):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.side_effect = Exception("DB error")
        from src.api.admin_routes import _verify_password
        assert _verify_password("test") is False

    @patch('src.api.admin_routes.db')
    def test_has_password_exception(self, mock_db):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.side_effect = Exception("DB error")
        from src.api.admin_routes import _has_password_set
        assert _has_password_set() is False
