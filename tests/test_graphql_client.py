"""
Tests for src.github.graphql_client
======================================
Unit tests for GitHubGraphQLClient. All HTTP requests are mocked.
"""
import pytest
from unittest.mock import patch, MagicMock

from src.github.graphql_client import GitHubGraphQLClient


class TestGitHubGraphQLClientInit:
    @patch("src.github.graphql_client.config")
    def test_init_with_explicit_token(self, mock_config):
        mock_config.GITHUB_API_URL = "https://api.github.com/graphql"
        client = GitHubGraphQLClient(token="ghp_test123")
        assert client.token == "ghp_test123"
        assert "Bearer ghp_test123" in client.headers["Authorization"]

    @patch("src.github.graphql_client.config")
    def test_init_with_config_token(self, mock_config):
        mock_config.GITHUB_TOKEN = "ghp_config_tok"
        mock_config.GITHUB_API_URL = "https://api.github.com/graphql"
        client = GitHubGraphQLClient()
        assert client.token == "ghp_config_tok"

    @patch("src.github.graphql_client.config")
    def test_init_raises_without_token(self, mock_config):
        mock_config.GITHUB_TOKEN = None
        mock_config.GITHUB_API_URL = "https://api.github.com/graphql"
        with pytest.raises(ValueError, match="GITHUB_TOKEN"):
            GitHubGraphQLClient()


class TestExecuteQuery:
    def _make_client(self):
        with patch("src.github.graphql_client.config") as mock_config:
            mock_config.GITHUB_TOKEN = "ghp_test"
            mock_config.GITHUB_API_URL = "https://api.github.com/graphql"
            return GitHubGraphQLClient()

    @patch("src.github.graphql_client.requests.post")
    def test_successful_query(self, mock_post):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"viewer": {"login": "testuser"}}}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = client.execute_query("{ viewer { login } }")
        assert result["data"]["viewer"]["login"] == "testuser"
        mock_post.assert_called_once()

    @patch("src.github.graphql_client.requests.post")
    def test_query_with_variables(self, mock_post):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": {"repository": {"name": "test"}}}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = client.execute_query("query($name: String!){ ... }", {"name": "test"})
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
        assert "variables" in str(call_kwargs)

    @patch("src.github.graphql_client.requests.post")
    def test_graphql_error_raises(self, mock_post):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "errors": [{"message": "Something broke", "type": "INTERNAL"}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with pytest.raises(Exception, match="GraphQL errors"):
            client.execute_query("{ broken }")

    @patch("src.github.graphql_client.requests.post")
    def test_forbidden_error_with_data_returns_partial(self, mock_post):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"organization": {"login": "test-org"}},
            "errors": [{"message": "SAML required", "type": "FORBIDDEN"}]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = client.execute_query("{ org }")
        assert "data" in result
        assert result["data"]["organization"]["login"] == "test-org"

    @patch("src.github.graphql_client.time.sleep")
    @patch("src.github.graphql_client.requests.post")
    def test_timeout_retries(self, mock_post, mock_sleep):
        import requests
        client = self._make_client()
        mock_post.side_effect = [
            requests.exceptions.Timeout("timeout"),
            MagicMock(
                json=MagicMock(return_value={"data": {"ok": True}}),
                raise_for_status=MagicMock()
            ),
        ]
        result = client.execute_query("{ test }")
        assert result["data"]["ok"] is True
        assert mock_post.call_count == 2

    @patch("src.github.graphql_client.requests.post")
    def test_connection_error_all_retries_exhausted(self, mock_post):
        import requests
        client = self._make_client()
        mock_post.side_effect = requests.exceptions.ConnectionError("refused")

        with patch("src.github.graphql_client.time.sleep"):
            with pytest.raises(requests.exceptions.ConnectionError):
                client.execute_query("{ test }")


class TestGetRateLimit:
    @patch("src.github.graphql_client.requests.post")
    def test_returns_rate_limit_info(self, mock_post):
        with patch("src.github.graphql_client.config") as mc:
            mc.GITHUB_TOKEN = "ghp_test"
            mc.GITHUB_API_URL = "https://api.github.com/graphql"
            client = GitHubGraphQLClient()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "rateLimit": {
                    "limit": 5000,
                    "remaining": 4990,
                    "resetAt": "2025-01-01T00:00:00Z",
                    "used": 10,
                    "cost": 1
                }
            }
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        rl = client.get_rate_limit()
        assert rl["remaining"] == 4990
        assert rl["limit"] == 5000
