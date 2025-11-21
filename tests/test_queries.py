"""
Tests para las queries GraphQL.
"""
import pytest

from src.github.queries import (
    ORGANIZATION_QUERY,
    REPOSITORY_QUERY,
    USER_QUERY,
    SEARCH_REPOSITORIES_QUERY,
    RATE_LIMIT_QUERY
)


class TestGraphQLQueries:
    """Tests para las queries GraphQL."""
    
    def test_organization_query_is_valid(self):
        """Test de que la query de organización es válida."""
        assert "organization" in ORGANIZATION_QUERY
        assert "$login: String!" in ORGANIZATION_QUERY
        assert "repositories" in ORGANIZATION_QUERY
        assert "membersWithRole" in ORGANIZATION_QUERY
    
    def test_repository_query_is_valid(self):
        """Test de que la query de repositorio es válida."""
        assert "repository" in REPOSITORY_QUERY
        assert "$owner: String!" in REPOSITORY_QUERY
        assert "$name: String!" in REPOSITORY_QUERY
        assert "primaryLanguage" in REPOSITORY_QUERY
        assert "stargazerCount" in REPOSITORY_QUERY
        assert "collaborators" in REPOSITORY_QUERY
    
    def test_user_query_is_valid(self):
        """Test de que la query de usuario es válida."""
        assert "user" in USER_QUERY
        assert "$login: String!" in USER_QUERY
        assert "repositories" in USER_QUERY
        assert "organizations" in USER_QUERY
        assert "contributionsCollection" in USER_QUERY
    
    def test_search_repositories_query_is_valid(self):
        """Test de que la query de búsqueda es válida."""
        assert "search" in SEARCH_REPOSITORIES_QUERY
        assert "$query: String!" in SEARCH_REPOSITORIES_QUERY
        assert "$first: Int!" in SEARCH_REPOSITORIES_QUERY
        assert "REPOSITORY" in SEARCH_REPOSITORIES_QUERY
        assert "pageInfo" in SEARCH_REPOSITORIES_QUERY
    
    def test_rate_limit_query_is_valid(self):
        """Test de que la query de rate limit es válida."""
        assert "rateLimit" in RATE_LIMIT_QUERY
        assert "limit" in RATE_LIMIT_QUERY
        assert "remaining" in RATE_LIMIT_QUERY
        assert "resetAt" in RATE_LIMIT_QUERY
    
    def test_queries_have_required_fields(self):
        """Test de que las queries tienen los campos requeridos."""
        # Campos comunes que deben estar en las queries de entidades
        common_fields = ["id", "name", "url"]
        
        for field in common_fields:
            assert field in ORGANIZATION_QUERY
            assert field in REPOSITORY_QUERY
            assert field in USER_QUERY
    
    def test_queries_have_pagination(self):
        """Test de que las queries tienen paginación donde corresponde."""
        assert "pageInfo" in ORGANIZATION_QUERY
        assert "hasNextPage" in ORGANIZATION_QUERY
        assert "endCursor" in ORGANIZATION_QUERY
        
        assert "pageInfo" in SEARCH_REPOSITORIES_QUERY
        assert "hasNextPage" in SEARCH_REPOSITORIES_QUERY
        assert "endCursor" in SEARCH_REPOSITORIES_QUERY
    
    def test_queries_are_not_empty(self):
        """Test de que las queries no están vacías."""
        assert len(ORGANIZATION_QUERY.strip()) > 0
        assert len(REPOSITORY_QUERY.strip()) > 0
        assert len(USER_QUERY.strip()) > 0
        assert len(SEARCH_REPOSITORIES_QUERY.strip()) > 0
        assert len(RATE_LIMIT_QUERY.strip()) > 0
    
    def test_queries_are_properly_formatted(self):
        """Test de que las queries están correctamente formateadas."""
        # Verificar que tienen la estructura básica de GraphQL
        queries = [
            ORGANIZATION_QUERY,
            REPOSITORY_QUERY,
            USER_QUERY,
            SEARCH_REPOSITORIES_QUERY,
            RATE_LIMIT_QUERY
        ]
        
        for query in queries:
            assert query.strip().startswith("query") or query.strip().startswith("{")
            assert "{" in query
            assert "}" in query
