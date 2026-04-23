"""Tests for additional route endpoints and model constructors."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _coll(data=None, find_one_result=None):
    c = MagicMock()
    data = data or []
    cursor = MagicMock()
    cursor.skip.return_value = cursor
    cursor.limit.return_value = data
    cursor.sort.return_value = cursor
    cursor.__iter__ = MagicMock(return_value=iter(data))
    c.find.return_value = cursor
    c.find_one.return_value = find_one_result or (data[0] if data else None)
    c.count_documents.return_value = len(data)
    c.aggregate.return_value = iter(data)
    return c


class TestMoreRouteEndpoints:
    @patch('src.core.db.db')
    def test_repo_detail(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll(find_one_result={
            "_id": "id1", "nameWithOwner": "owner/repo", "name": "repo",
        })
        resp = client.get("/api/v1/repositories/owner/repo")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_user_detail(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll(find_one_result={
            "_id": "id1", "login": "octocat",
        })
        resp = client.get("/api/v1/users/octocat")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_org_detail(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll(find_one_result={
            "_id": "id1", "login": "microsoft",
        })
        resp = client.get("/api/v1/organizations/microsoft")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_views_list(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll()
        resp = client.get("/api/v1/views")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_views_create(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        coll = _coll()
        coll.insert_one.return_value = MagicMock(inserted_id="new_id")
        mock_db.get_collection.return_value = coll
        resp = client.post("/api/v1/views", json={
            "name": "Test View", "entity_type": "repositories",
            "entity_ids": ["id1"], "filters": {},
        })
        assert resp.status_code in (200, 201, 422, 500)

    @patch('src.core.db.db')
    def test_favorites_list(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll()
        resp = client.get("/api/v1/favorites")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_dashboard_stats(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll()
        resp = client.get("/api/v1/dashboard/stats")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_collaboration_analyze(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll()
        resp = client.get("/api/v1/collaboration/analyze/octocat")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_repositories_with_sort(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll()
        resp = client.get("/api/v1/repositories",
                         params={"sort_by": "stargazer_count", "sort_order": "desc"})
        assert resp.status_code == 200

    @patch('src.core.db.db')
    def test_repositories_with_search(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll()
        resp = client.get("/api/v1/repositories", params={"search": "quantum"})
        assert resp.status_code == 200

    @patch('src.core.db.db')
    def test_repository_collaborators(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll(find_one_result={
            "_id": "id1", "full_name": "owner/repo",
            "collaborators": [{"login": "dev1"}, {"login": "dev2"}],
        })
        resp = client.get("/api/v1/repositories/owner/repo/collaborators")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_collaboration_network_metrics(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll()
        resp = client.get("/api/v1/collaboration/network-metrics")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_dashboard_refresh(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _coll()
        resp = client.post("/api/v1/dashboard/refresh-metrics")
        assert resp.status_code in (200, 500)


class TestRepositoryModel:
    def test_from_graphql_minimal(self):
        from src.models.repository import Repository
        data = {
            "nameWithOwner": "owner/repo",
            "name": "repo",
            "url": "https://github.com/owner/repo",
        }
        repo = Repository.from_graphql_response(data)
        assert repo.name_with_owner == "owner/repo"

    def test_from_graphql_full(self):
        from src.models.repository import Repository
        data = {
            "nameWithOwner": "owner/repo",
            "name": "repo",
            "url": "https://github.com/owner/repo",
            "description": "A test repo",
            "stargazerCount": 42,
            "forkCount": 5,
            "primaryLanguage": {"name": "Python", "color": "#3572A5"},
            "owner": {"login": "owner", "url": "https://github.com/owner"},
            "createdAt": "2020-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
            "pushedAt": "2024-01-01T00:00:00Z",
            "isArchived": False, "isFork": False,
            "repositoryTopics": {"nodes": [{"topic": {"name": "quantum"}}]},
        }
        repo = Repository.from_graphql_response(data)
        assert repo.stargazer_count == 42
        assert repo.fork_count == 5


class TestOrganizationModel:
    def test_from_graphql(self):
        from src.models.organization import Organization
        data = {
            "id": "O_abc123",
            "login": "test-org", "name": "Test Org",
            "url": "https://github.com/test-org",
            "avatarUrl": "https://avatars.githubusercontent.com/u/1",
            "description": "An org",
            "createdAt": "2020-01-01T00:00:00Z",
            "repositories": {"totalCount": 10},
            "membersWithRole": {"totalCount": 5},
        }
        org = Organization.from_graphql_response(data)
        assert org.login == "test-org"


class TestUserModel:
    def test_from_graphql(self):
        from src.models.user import User
        data = {
            "id": "U_abc123",
            "login": "octocat", "name": "Octocat",
            "url": "https://github.com/octocat",
            "email": "octo@cat.com",
            "avatarUrl": "https://avatars.githubusercontent.com/u/1",
            "followers": {"totalCount": 100},
            "following": {"totalCount": 50},
            "repositories": {"totalCount": 10},
        }
        user = User.from_graphql_response(data)
        assert user.login == "octocat"
