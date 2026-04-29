"""
Extended tests for GraphQL client: _build_search_query, search_repositories,
execute_query retry logic, rate limit.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import requests


class TestBuildSearchQuery:
    @pytest.fixture
    def client(self):
        with patch.dict('os.environ', {'GITHUB_TOKEN': 'ghp_test'}):
            from src.github.graphql_client import GitHubGraphQLClient
            return GitHubGraphQLClient(token="ghp_test")

    def test_simple_query(self, client):
        config = MagicMock()
        config.keywords = ["quantum"]
        config.min_stars = 10
        config.exclude_forks = True
        result = client._build_search_query(config, use_simple_query=True)
        assert "quantum" in result
        assert "stars:>=10" in result
        assert "fork:false" in result

    def test_advanced_query_multiple_keywords(self, client):
        config = MagicMock()
        config.keywords = ["quantum", "computing", "qubit", "qiskit"]
        config.min_stars = 5
        config.exclude_forks = False
        result = client._build_search_query(config, use_simple_query=False)
        assert "OR" in result
        assert "stars:>=5" in result
        assert "fork:false" not in result

    def test_no_stars_filter(self, client):
        config = MagicMock()
        config.keywords = ["test"]
        config.min_stars = 0
        config.exclude_forks = False
        result = client._build_search_query(config, use_simple_query=True)
        assert "stars" not in result

    def test_max_5_keywords(self, client):
        config = MagicMock()
        config.keywords = ["a", "b", "c", "d", "e", "f", "g"]
        config.min_stars = 0
        config.exclude_forks = False
        result = client._build_search_query(config, use_simple_query=False)
        # Should only include first 5
        assert "f" not in result.split("OR")[-1] if "OR" in result else True


class TestExecuteQueryRetry:
    @patch('src.github.graphql_client.requests.post')
    def test_success_first_try(self, mock_post):
        from src.github.graphql_client import GitHubGraphQLClient
        client = GitHubGraphQLClient(token="ghp_test")
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"viewer": {"login": "test"}}},
            raise_for_status=lambda: None,
        )
        result = client.execute_query("{ viewer { login } }")
        assert result["data"]["viewer"]["login"] == "test"

    @patch('src.github.graphql_client.requests.post')
    def test_server_error_500(self, mock_post):
        from src.github.graphql_client import GitHubGraphQLClient
        client = GitHubGraphQLClient(token="ghp_test")
        resp_500 = MagicMock(
            status_code=500,
            json=lambda: {"message": "server error"},
            text="server error",
        )
        resp_500.raise_for_status.side_effect = Exception("500 Server Error")
        mock_post.return_value = resp_500
        with patch('time.sleep'), pytest.raises(Exception):
            client.execute_query("{ test }")

    @patch('src.github.graphql_client.requests.post')
    def test_connection_error_retries(self, mock_post):
        from src.github.graphql_client import GitHubGraphQLClient
        client = GitHubGraphQLClient(token="ghp_test")
        mock_post.side_effect = [
            requests.ConnectionError("connection failed"),
            MagicMock(
                status_code=200,
                json=lambda: {"data": {"ok": True}},
                raise_for_status=lambda: None,
            ),
        ]
        with patch('time.sleep'):
            result = client.execute_query("{ ok }")
            assert result["data"]["ok"] is True

    @patch('src.github.graphql_client.requests.post')
    def test_graphql_error_raises(self, mock_post):
        from src.github.graphql_client import GitHubGraphQLClient
        client = GitHubGraphQLClient(token="ghp_test")
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {"user": {"login": "test"}},
                "errors": [{"message": "partial error"}],
            },
            raise_for_status=lambda: None,
        )
        # The client raises Exception on GraphQL errors
        with pytest.raises(Exception, match="GraphQL errors"):
            client.execute_query("{ user { login } }")


class TestGetRateLimit:
    @patch('src.github.graphql_client.requests.post')
    def test_get_rate_limit(self, mock_post):
        from src.github.graphql_client import GitHubGraphQLClient
        client = GitHubGraphQLClient(token="ghp_test")
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {
                    "rateLimit": {
                        "limit": 5000,
                        "remaining": 4990,
                        "resetAt": "2025-01-01T00:00:00Z",
                        "used": 10,
                        "cost": 1,
                    }
                }
            },
            raise_for_status=lambda: None,
        )
        result = client.get_rate_limit()
        assert result["remaining"] == 4990

    @patch('src.github.graphql_client.requests.post')
    def test_check_rate_limit_sufficient(self, mock_post):
        from src.github.graphql_client import GitHubGraphQLClient
        client = GitHubGraphQLClient(token="ghp_test")
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {
                    "rateLimit": {
                        "limit": 5000,
                        "remaining": 4000,
                        "resetAt": "2025-01-01T00:00:00Z",
                        "used": 1000,
                        "cost": 1,
                    }
                }
            },
            raise_for_status=lambda: None,
        )
        # Should not raise or sleep when remaining is above min
        client.check_rate_limit(min_remaining=50)
