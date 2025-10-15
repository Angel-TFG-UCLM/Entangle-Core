"""
Tests para el cliente GraphQL de GitHub.
"""
import pytest
from unittest.mock import Mock, patch

from src.github.graphql_client import GitHubGraphQLClient
from src.core.config import config


class TestGitHubGraphQLClient:
    """Tests para GitHubGraphQLClient."""
    
    def test_client_initialization(self):
        """Test de inicialización del cliente."""
        client = GitHubGraphQLClient()
        assert client.token == config.GITHUB_TOKEN
        assert client.api_url == config.GITHUB_API_URL
        assert "Authorization" in client.headers
    
    def test_client_custom_token(self):
        """Test de inicialización con token personalizado."""
        custom_token = "custom_token_123"
        client = GitHubGraphQLClient(token=custom_token)
        assert client.token == custom_token
    
    @patch('src.github.graphql_client.requests.post')
    def test_execute_query_success(self, mock_post):
        """Test de ejecución exitosa de query."""
        # Mock de respuesta exitosa
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "viewer": {
                    "login": "test_user"
                }
            }
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        client = GitHubGraphQLClient()
        query = "query { viewer { login } }"
        result = client.execute_query(query)
        
        assert "data" in result
        assert result["data"]["viewer"]["login"] == "test_user"
        mock_post.assert_called_once()
    
    @patch('src.github.graphql_client.requests.post')
    def test_execute_query_with_variables(self, mock_post):
        """Test de ejecución de query con variables."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": {}}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        client = GitHubGraphQLClient()
        query = "query($login: String!) { user(login: $login) { id } }"
        variables = {"login": "octocat"}
        
        client.execute_query(query, variables)
        
        # Verificar que se llamó con variables
        call_args = mock_post.call_args
        assert call_args[1]['json']['variables'] == variables
    
    @patch('src.github.graphql_client.requests.post')
    def test_execute_query_with_errors(self, mock_post):
        """Test de manejo de errores en la respuesta."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "errors": [
                {"message": "Something went wrong"}
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        client = GitHubGraphQLClient()
        query = "query { invalid }"
        
        with pytest.raises(Exception) as exc_info:
            client.execute_query(query)
        
        assert "GraphQL errors" in str(exc_info.value)
    
    @patch('src.github.graphql_client.requests.post')
    def test_get_rate_limit(self, mock_post):
        """Test de obtención de rate limit."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "rateLimit": {
                    "limit": 5000,
                    "remaining": 4999,
                    "resetAt": "2024-01-01T00:00:00Z",
                    "used": 1
                }
            }
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        client = GitHubGraphQLClient()
        rate_limit = client.get_rate_limit()
        
        assert rate_limit["limit"] == 5000
        assert rate_limit["remaining"] == 4999
        assert "resetAt" in rate_limit
