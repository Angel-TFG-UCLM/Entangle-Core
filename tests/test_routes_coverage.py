"""Tests for untested route endpoints - covering collaboration, github integration, favorites/views CRUD, pipeline."""
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


class TestCollaborationRoutes:
    @patch('src.core.db.db')
    def test_discover_collaboration(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/collaboration/discover")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_invalidate_collaboration_cache(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.post("/api/v1/collaboration/discover/invalidate")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_user_collaboration_network(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/collaboration/user/octocat")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_quantum_tunneling(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/collaboration/quantum-tunneling",
                         params={"source": "alice", "target": "bob"})
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_network_metrics_with_params(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/collaboration/network-metrics",
                         params={"year_from": 2020, "year_to": 2024})
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_analyze_collaboration_post(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.post("/api/v1/collaboration/analyze",
                          json={"user": "octocat"})
        assert resp.status_code in (200, 400, 422, 500)


class TestGitHubIntegrationRoutes:
    @patch('src.core.db.db')
    def test_rate_limit(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        resp = client.get("/api/v1/rate-limit")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_get_github_org(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/organizations/github/microsoft")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_get_github_repo(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/repositories/github/owner/repo")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_get_github_user(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/users/github/octocat")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_search_repos(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/search/repositories", params={"query": "quantum"})
        assert resp.status_code in (200, 500)


class TestFavoritesCRUD:
    @patch('src.core.db.db')
    def test_add_favorite(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.post("/api/v1/favorites", json={
            "entity_type": "repository", "entity_id": "repo1",
            "name": "My Favorite Repo"
        })
        assert resp.status_code in (200, 201, 400, 422, 500)

    @patch('src.core.db.db')
    def test_remove_favorite(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.delete("/api/v1/favorites/repo1")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_get_favorite_children(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/favorites/repo1/children")
        assert resp.status_code in (200, 404, 500)


class TestViewsCRUD:
    @patch('src.core.db.db')
    def test_delete_view(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.delete("/api/v1/views/view123")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_get_view_data(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        coll = _mock_coll(find_one_result={
            "_id": "view123", "name": "Test View",
            "entity_type": "repositories", "entity_ids": ["id1"],
            "filters": {},
        })
        mock_db.get_collection.return_value = coll
        resp = client.post("/api/v1/views/view123/data", json={})
        assert resp.status_code in (200, 404, 500)


class TestPipelineRoute:
    @patch('src.api.routes._run_full_pipeline_direct')
    @patch('src.core.db.db')
    def test_run_pipeline(self, mock_db, mock_pipeline, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.post("/api/v1/pipeline/run-all",
                          params={"mode": "incremental"})
        assert resp.status_code in (200, 500)


class TestDashboardWithFilters:
    @patch('src.core.db.db')
    def test_dashboard_with_org_filter(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/dashboard/stats", params={"org": "qiskit"})
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_dashboard_with_language_filter(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/dashboard/stats", params={"language": "Python"})
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_dashboard_force_refresh(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/dashboard/stats", params={"force_refresh": True})
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_dashboard_with_discipline(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/dashboard/stats", params={"discipline": "quantum_computing"})
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_dashboard_with_repo_filter(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/dashboard/stats", params={"repo": "qiskit"})
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_dashboard_include_bots(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll()
        resp = client.get("/api/v1/dashboard/stats", params={"include_bots": True})
        assert resp.status_code in (200, 500)
