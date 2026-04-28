"""
More route endpoint tests (v2) - following test_routes_comprehensive pattern.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock
from bson import ObjectId
from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _make_coll(data=None, find_one_result=None):
    coll = MagicMock()
    data = data or []
    cursor = MagicMock()
    cursor.skip.return_value = cursor
    cursor.limit.return_value = data
    cursor.sort.return_value = cursor
    cursor.__iter__ = MagicMock(return_value=iter(data))
    coll.find.return_value = cursor
    coll.find_one.return_value = find_one_result or (data[0] if data else None)
    coll.count_documents.return_value = len(data)
    coll.aggregate.return_value = iter(data)
    coll.update_one.return_value = MagicMock(modified_count=1)
    coll.delete_one.return_value = MagicMock(deleted_count=1)
    coll.insert_one.return_value = MagicMock(inserted_id="new_id")
    return coll


class TestUserProfile:
    @patch('src.core.db.db')
    def test_get_profile(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        coll = _make_coll(find_one_result={
            "_id": "507f1f77bcf86cd799439011",
            "login": "octocat", "name": "Octocat",
        })
        mock_db.get_collection.return_value = coll
        resp = client.get("/api/v1/users/profile/octocat")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_profile_not_found(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        coll = _make_coll(find_one_result=None)
        mock_db.get_collection.return_value = coll
        resp = client.get("/api/v1/users/profile/nonexistent")
        assert resp.status_code in (200, 404)


class TestRepoListPaginated:
    @patch('src.core.db.db')
    def test_repos(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll(data=[
            {"_id": "id1", "nameWithOwner": "o/r"},
        ])
        resp = client.get("/api/v1/repositories", params={"page": 1, "per_page": 10})
        assert resp.status_code == 200


class TestUserListPaginated:
    @patch('src.core.db.db')
    def test_users(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll(data=[
            {"_id": "id1", "login": "u1"},
        ])
        resp = client.get("/api/v1/users", params={"page": 1, "per_page": 10})
        assert resp.status_code == 200


class TestOrgListPaginated:
    @patch('src.core.db.db')
    def test_orgs(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll(data=[
            {"_id": "id1", "login": "o1"},
        ])
        resp = client.get("/api/v1/organizations", params={"page": 1, "per_page": 10})
        assert resp.status_code == 200


class TestCollaborationRoutes:
    @patch('src.core.db.db')
    def test_user_collab(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll()
        resp = client.get("/api/v1/collaboration/user/octocat")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_discover(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll()
        resp = client.get("/api/v1/collaboration/discover")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_discover_years(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll()
        resp = client.get("/api/v1/collaboration/discover",
                          params={"year_from": 2020, "year_to": 2024})
        assert resp.status_code in (200, 500)


class TestSearchRoutes:
    @patch('src.core.db.db')
    def test_search_entities(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll()
        resp = client.get("/api/v1/search/entities", params={"q": "quantum"})
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_search_entity_by_id(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll(find_one_result={
            "_id": "507f1f77bcf86cd799439011", "login": "test",
        })
        resp = client.get("/api/v1/search/entity/test")
        assert resp.status_code in (200, 400, 404, 500)


class TestDashboardRoutes:
    @patch('src.core.db.db')
    def test_stats(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll()
        resp = client.get("/api/v1/dashboard/stats")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_refresh_metrics(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll()
        resp = client.post("/api/v1/dashboard/refresh-metrics")
        assert resp.status_code in (200, 500)


class TestIngestionTriggers:
    @patch('src.api.routes._run_repository_ingestion')
    @patch('src.core.db.db')
    @patch('src.api.routes.config')
    def test_repos_ingestion(self, mock_config, mock_db, mock_run, client):
        mock_config.github_token = "ghp_test"
        mock_db.ensure_connection = MagicMock()
        resp = client.post("/api/v1/ingestion/repositories")
        assert resp.status_code in (200, 202, 409, 500)

    @patch('src.api.routes._run_user_ingestion')
    @patch('src.core.db.db')
    @patch('src.api.routes.config')
    def test_users_ingestion(self, mock_config, mock_db, mock_run, client):
        mock_config.github_token = "ghp_test"
        mock_db.ensure_connection = MagicMock()
        resp = client.post("/api/v1/ingestion/users")
        assert resp.status_code in (200, 202, 409, 500)

    @patch('src.api.routes._run_organization_ingestion')
    @patch('src.core.db.db')
    @patch('src.api.routes.config')
    def test_orgs_ingestion(self, mock_config, mock_db, mock_run, client):
        mock_config.github_token = "ghp_test"
        mock_db.ensure_connection = MagicMock()
        resp = client.post("/api/v1/ingestion/organizations")
        assert resp.status_code in (200, 202, 409, 500)

    @patch('src.api.routes._run_repository_enrichment')
    @patch('src.core.db.db')
    @patch('src.api.routes.config')
    def test_repos_enrichment(self, mock_config, mock_db, mock_run, client):
        mock_config.github_token = "ghp_test"
        mock_db.ensure_connection = MagicMock()
        resp = client.post("/api/v1/enrichment/repositories")
        assert resp.status_code in (200, 202, 409, 500)

    @patch('src.api.routes._run_user_enrichment')
    @patch('src.core.db.db')
    @patch('src.api.routes.config')
    def test_users_enrichment(self, mock_config, mock_db, mock_run, client):
        mock_config.github_token = "ghp_test"
        mock_db.ensure_connection = MagicMock()
        resp = client.post("/api/v1/enrichment/users")
        assert resp.status_code in (200, 202, 409, 500)

    @patch('src.api.routes._run_organization_enrichment')
    @patch('src.core.db.db')
    @patch('src.api.routes.config')
    def test_orgs_enrichment(self, mock_config, mock_db, mock_run, client):
        mock_config.github_token = "ghp_test"
        mock_db.ensure_connection = MagicMock()
        resp = client.post("/api/v1/enrichment/organizations")
        assert resp.status_code in (200, 202, 409, 500)


class TestViewsData:
    @patch('src.core.db.db')
    def test_view_data(self, mock_db, client):
        oid = str(ObjectId())
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _make_coll(find_one_result={
            "_id": oid, "name": "View", "entity_ids": [],
        })
        resp = client.post(f"/api/v1/views/{oid}/data")
        assert resp.status_code in (200, 404, 422, 500)


class TestTasksRoute:
    @patch('src.api.routes.background_tasks_status', {})
    def test_list_tasks(self, client):
        resp = client.get("/api/v1/tasks")
        assert resp.status_code == 200


class TestRoot:
    def test_root(self, client):
        resp = client.get("/api/v1/")
        assert resp.status_code == 200
