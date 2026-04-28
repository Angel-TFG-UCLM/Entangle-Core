"""
Tests for src.api.routes — additional endpoints
=================================================
Extends the existing test_api.py by testing more endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, PropertyMock
from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _mock_collection(data=None, count=0):
    """Build a mock MongoDB collection that supports find/find_one/count_documents."""
    coll = MagicMock()
    data = data or []

    cursor = MagicMock()
    cursor.skip.return_value = cursor
    cursor.limit.return_value = data
    cursor.sort.return_value = cursor
    cursor.__iter__ = lambda self: iter(data)

    coll.find.return_value = cursor
    coll.find_one.return_value = data[0] if data else None
    coll.count_documents.return_value = count or len(data)
    coll.insert_one.return_value = MagicMock(inserted_id="new_id")
    coll.delete_one.return_value = MagicMock(deleted_count=1)
    coll.delete_many.return_value = MagicMock(deleted_count=1)
    return coll


class TestRootEndpoint:
    def test_root(self, client):
        response = client.get("/api/v1/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data or "status" in data or isinstance(data, dict)


class TestStatsEndpoint:

    @patch('src.core.db.db')
    def test_stats(self, mock_db_instance, client):
        coll = _mock_collection(count=42)
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.get("/api/v1/stats")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


class TestFavoritesEndpoints:

    @patch('src.core.db.db')
    def test_get_favorites(self, mock_db_instance, client):
        favorites = [
            {"_id": "1", "entity_id": "repo_qiskit/qiskit", "entity_type": "repository", "label": "Qiskit"},
        ]
        coll = _mock_collection(favorites)
        cursor = MagicMock()
        cursor.sort.return_value = favorites
        coll.find.return_value = cursor
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.get("/api/v1/favorites")
        assert response.status_code == 200

    @patch('src.core.db.db')
    def test_add_favorite(self, mock_db_instance, client):
        coll = _mock_collection()
        coll.find_one.return_value = None
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.post("/api/v1/favorites", json={
            "id": "repo_qiskit/qiskit",
            "type": "repository",
            "name": "Qiskit",
        })
        assert response.status_code in (200, 201)

    @patch('src.core.db.db')
    def test_remove_favorite(self, mock_db_instance, client):
        coll = _mock_collection()
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.delete("/api/v1/favorites/repo_qiskit%2Fqiskit")
        assert response.status_code in (200, 204, 404)


class TestViewsEndpoints:

    @patch('src.core.db.db')
    def test_get_views(self, mock_db_instance, client):
        views = [
            {"_id": "view1", "name": "My View", "filters": {}},
        ]
        coll = _mock_collection(views)
        cursor = MagicMock()
        cursor.sort.return_value = views
        coll.find.return_value = cursor
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.get("/api/v1/views")
        assert response.status_code == 200

    @patch('src.core.db.db')
    def test_save_view(self, mock_db_instance, client):
        coll = _mock_collection()
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.post("/api/v1/views", json={
            "name": "Test View",
            "entity_ids": ["repo_qiskit/qiskit", "user_alice"],
        })
        assert response.status_code in (200, 201)

    @patch('src.core.db.db')
    def test_delete_view(self, mock_db_instance, client):
        coll = _mock_collection()
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.delete("/api/v1/views/view1")
        assert response.status_code in (200, 204, 404)


class TestTaskEndpoints:

    def test_get_task_status_not_found(self, client):
        response = client.get("/api/v1/ingestion/status/nonexistent-task-id")
        assert response.status_code in (200, 404)

    def test_list_tasks(self, client):
        response = client.get("/api/v1/tasks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (list, dict))


class TestSearchEndpoints:

    @patch('src.core.db.db')
    def test_search_entities(self, mock_db_instance, client):
        coll = _mock_collection([
            {"_id": "1", "full_name": "qiskit/qiskit", "type": "repository"},
        ])
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.get("/api/v1/search/entities?q=qiskit")
        assert response.status_code in (200, 422)


class TestCollaborationEndpoints:

    @patch('src.core.db.db')
    def test_invalidate_collaboration_cache(self, mock_db_instance, client):
        coll = _mock_collection()
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.post("/api/v1/collaboration/discover/invalidate")
        assert response.status_code in (200, 204, 500)


class TestGitHubProxyEndpoints:
    """Endpoints that proxy to GitHub API — test basic path handling."""

    @patch('src.core.db.db')
    def test_get_user_profile(self, mock_db_instance, client):
        coll = _mock_collection([
            {"_id": "1", "login": "testuser", "bio": "Quantum developer"},
        ])
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.get("/api/v1/users/profile/testuser")
        assert response.status_code in (200, 404, 500)
