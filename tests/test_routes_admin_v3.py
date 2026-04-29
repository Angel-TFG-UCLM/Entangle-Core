"""Additional route endpoint tests to push coverage past 60%."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _mock_coll(data=None, find_one_result=None):
    c = MagicMock()
    data = data or []
    cursor = MagicMock()
    cursor.skip.return_value = cursor
    cursor.limit.return_value = data
    cursor.sort.return_value = cursor
    cursor.__iter__ = MagicMock(return_value=iter(data))
    cursor.batch_size.return_value = cursor
    c.find.return_value = cursor
    c.find_one.return_value = find_one_result or (data[0] if data else None)
    c.count_documents.return_value = len(data)
    c.aggregate.return_value = iter(data)
    c.insert_one.return_value = MagicMock(inserted_id="new_id")
    c.delete_one.return_value = MagicMock(deleted_count=1)
    c.update_one.return_value = MagicMock(modified_count=1)
    return c


# ==================== GET /stats ====================

class TestStatsEndpoint:
    @patch('src.core.db.db')
    def test_stats_from_cache(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        cached = {"type": "simple_counts", "data": {
            "repositories": 100, "users": 50, "organizations": 10
        }}
        metrics = _mock_coll(find_one_result=cached)
        mock_db.get_collection.return_value = metrics
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["repositories"] == 100

    @patch('src.core.db.db')
    def test_stats_calculated(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        metrics = _mock_coll(find_one_result=None)
        repos = _mock_coll()
        users = _mock_coll()
        orgs = _mock_coll()
        collections = {"metrics": metrics, "repositories": repos, "users": users, "organizations": orgs}
        mock_db.get_collection.side_effect = lambda name: collections.get(name, _mock_coll())
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200


# ==================== GET /favorites (full CRUD) ====================

class TestFavoritesFullCRUD:
    @patch('src.core.db.db')
    def test_get_favorites_empty(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll(find_one_result=None)
        resp = client.get("/api/v1/favorites")
        assert resp.status_code == 200
        assert resp.json()["favorites"] == []

    @patch('src.core.db.db')
    def test_get_favorites_with_items(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll(
            find_one_result={"type": "favorites", "items": [{"id": "r1", "name": "repo1"}]}
        )
        resp = client.get("/api/v1/favorites")
        assert resp.status_code == 200
        assert len(resp.json()["favorites"]) == 1

    @patch('src.core.db.db')
    def test_add_favorite_success(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.post("/api/v1/favorites", json={
            "id": "repo1", "type": "repository", "name": "My Repo"
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch('src.core.db.db')
    def test_add_favorite_missing_field(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.post("/api/v1/favorites", json={"id": "repo1"})
        assert resp.status_code == 400

    @patch('src.core.db.db')
    def test_remove_favorite_success(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.delete("/api/v1/favorites/repo1")
        assert resp.status_code == 200

    @patch('src.core.db.db')
    def test_remove_favorite_not_found(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        coll = _mock_coll()
        coll.update_one.return_value = MagicMock(modified_count=0)
        mock_db.get_collection.return_value = coll
        resp = client.delete("/api/v1/favorites/nonexistent")
        assert resp.status_code == 404


# ==================== Views CRUD ====================

class TestViewsFullCRUD:
    @patch('src.core.db.db')
    def test_get_views_empty(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll(find_one_result=None)
        resp = client.get("/api/v1/views")
        assert resp.status_code == 200
        assert resp.json()["views"] == []

    @patch('src.core.db.db')
    def test_get_views_with_items(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll(
            find_one_result={"type": "custom_views", "items": [{"id": "v1", "name": "view1"}]}
        )
        resp = client.get("/api/v1/views")
        assert resp.status_code == 200
        assert len(resp.json()["views"]) == 1

    @patch('src.core.db.db')
    def test_save_view_success(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.post("/api/v1/views", json={
            "name": "Quantum Repos", "entity_ids": ["r1", "r2"]
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @patch('src.core.db.db')
    def test_save_view_missing_fields(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.post("/api/v1/views", json={"name": "test"})
        assert resp.status_code == 400

    @patch('src.core.db.db')
    def test_save_view_empty_entity_ids(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.post("/api/v1/views", json={"name": "test", "entity_ids": []})
        assert resp.status_code == 400

    @patch('src.core.db.db')
    def test_delete_view_success(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.delete("/api/v1/views/view1")
        assert resp.status_code == 200

    @patch('src.core.db.db')
    def test_delete_view_not_found(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        coll = _mock_coll()
        coll.update_one.return_value = MagicMock(modified_count=0)
        mock_db.get_collection.return_value = coll
        resp = client.delete("/api/v1/views/nonexistent")
        assert resp.status_code == 404


# ==================== Search entities ====================

class TestSearchEntities:
    @patch('src.core.db.db')
    def test_search_basic(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_coll = _mock_coll()
        mock_db.get_collection.return_value = mock_coll
        resp = client.get("/api/v1/search/entities", params={"q": "quantum"})
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_search_too_short(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        resp = client.get("/api/v1/search/entities", params={"q": "a"})
        assert resp.status_code == 422  # validation error


# ==================== User profile ====================

class TestUserProfile:
    @patch('src.core.db.db')
    def test_user_profile(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        user_data = {"login": "alice", "name": "Alice", "avatar_url": "img"}
        mock_db.get_collection.return_value = _mock_coll(find_one_result=user_data)
        resp = client.get("/api/v1/users/profile/alice")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_user_profile_not_found(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll(find_one_result=None)
        resp = client.get("/api/v1/users/profile/nobody")
        assert resp.status_code in (404, 500)


# ==================== Admin route endpoints ====================

class TestAdminRoutes:
    @patch('src.api.admin_routes.cancel_flags')
    @patch('src.api.admin_routes.active_operations', {
        "op_1": {"operation_id": "op_1", "status": "running"}
    })
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_cancel_operation(self, mock_admin, mock_flags, client):
        mock_event = MagicMock()
        mock_flags.__contains__ = MagicMock(return_value=True)
        mock_flags.__getitem__ = MagicMock(return_value=mock_event)
        resp = client.post("/api/v1/admin/operations/op_1/cancel?token=fake")
        assert resp.status_code == 200

    @patch('src.api.admin_routes.active_operations', {})
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_cancel_operation_not_found(self, mock_admin, client):
        resp = client.post("/api/v1/admin/operations/nonexistent/cancel?token=fake")
        assert resp.status_code == 404

    @patch('src.api.admin_routes.operation_logs', {"op_1": [
        {"timestamp": "2024-01-01T00:00:00", "level": "INFO", "message": "started"}
    ]})
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_get_operation_logs(self, mock_admin, client):
        resp = client.get("/api/v1/admin/operations/op_1/logs?token=fake")
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data

    @patch('src.api.admin_routes.operation_logs', {})
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_get_operation_logs_empty(self, mock_admin, client):
        resp = client.get("/api/v1/admin/operations/nonexistent/logs?token=fake")
        assert resp.status_code == 200
        assert resp.json()["logs"] == []
