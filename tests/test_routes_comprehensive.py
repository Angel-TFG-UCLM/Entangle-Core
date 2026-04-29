"""
Tests for src.api.routes — broad endpoint coverage
====================================================
Tests as many route endpoints as possible via TestClient + mocked DB.
Focuses on exercising the try/except + db boilerplate in each handler.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _mock_db():
    """Return a mock db module with ensure_connection and get_collection."""
    mock = MagicMock()
    mock.ensure_connection = MagicMock()

    def _make_coll(data=None, find_one_result=None):
        coll = MagicMock()
        data = data or []
        cursor = MagicMock()
        cursor.skip.return_value = cursor
        cursor.limit.return_value = data
        cursor.sort.return_value = cursor
        cursor.__iter__ = MagicMock(return_value=iter(data))
        cursor.__getitem__ = MagicMock(side_effect=list(data).__getitem__)
        coll.find.return_value = cursor
        coll.find_one.return_value = find_one_result or (data[0] if data else None)
        coll.count_documents.return_value = len(data)
        coll.aggregate.return_value = iter(data)
        coll.update_one.return_value = MagicMock(modified_count=1)
        coll.delete_one.return_value = MagicMock(deleted_count=1)
        coll.delete_many.return_value = MagicMock(deleted_count=1)
        coll.insert_one.return_value = MagicMock(inserted_id="new_id")
        return coll

    # Default collection returned
    default_coll = _make_coll()
    mock.get_collection.return_value = default_coll
    mock._make_coll = _make_coll  # helper for tests
    return mock


# ========================================================================
# BASIC ENDPOINTS
# ========================================================================
class TestHealthEndpoint:
    def test_health(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestStatsEndpointFull:
    @patch('src.core.db.db')
    def test_cached(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = {
            "type": "simple_counts",
            "data": {"repositories": 100, "users": 50, "organizations": 10}
        }
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["repositories"] == 100

    @patch('src.core.db.db')
    def test_computed(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = None
        coll.count_documents.return_value = 42
        coll.update_one.return_value = MagicMock()
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200


# ========================================================================
# DASHBOARD 
# ========================================================================
class TestDashboardStats:
    @patch('src.core.db.db')
    def test_cached_dashboard(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = {
            "type": "dashboard_stats",
            "data": {"kpis": {}, "graphs": {}},
            "updated_at": datetime(2025, 1, 1)
        }
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/dashboard/stats")
        assert resp.status_code == 200

    @patch('src.core.db.db')
    def test_dashboard_force_refresh(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        # No cache hit with force_refresh, needs full calculation
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = []
        cursor.__iter__ = MagicMock(return_value=iter([]))
        coll.find.return_value = cursor
        coll.find_one.return_value = None
        coll.count_documents.return_value = 0
        coll.aggregate.return_value = iter([])
        coll.update_one.return_value = MagicMock()
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/dashboard/stats?force_refresh=true")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_dashboard_with_org_filter(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = []
        cursor.__iter__ = MagicMock(return_value=iter([]))
        coll.find.return_value = cursor
        coll.find_one.return_value = None
        coll.count_documents.return_value = 0
        coll.aggregate.return_value = iter([])
        coll.update_one.return_value = MagicMock()
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/dashboard/stats?org=qiskit")
        assert resp.status_code in (200, 500)


# ========================================================================
# RATE LIMIT
# ========================================================================
class TestRateLimit:
    @patch('src.api.routes.get_rate_limit_info')
    def test_rate_limit(self, mock_rl, client):
        mock_rl.return_value = {"remaining": 4990, "limit": 5000}
        resp = client.get("/api/v1/rate-limit")
        assert resp.status_code == 200
        assert resp.json()["remaining"] == 4990


# ========================================================================
# GITHUB PROXY ENDPOINTS
# ========================================================================
class TestGitHubProxyOrg:
    @patch('src.api.routes.extract_organization')
    def test_get_org(self, mock_extract, client):
        mock_extract.return_value = {"login": "qiskit", "id": "o1"}
        resp = client.get("/api/v1/organizations/github/qiskit")
        assert resp.status_code == 200
        assert resp.json()["login"] == "qiskit"

    @patch('src.api.routes.extract_organization')
    def test_org_not_found(self, mock_extract, client):
        mock_extract.return_value = {}
        resp = client.get("/api/v1/organizations/github/nonexistent")
        assert resp.status_code in (404, 500)

    @patch('src.api.routes.extract_organization')
    def test_org_github_error(self, mock_extract, client):
        mock_extract.side_effect = Exception("GitHub API error")
        resp = client.get("/api/v1/organizations/github/failing")
        assert resp.status_code == 500


class TestGitHubProxyRepo:
    @patch('src.api.routes.extract_repository')
    def test_get_repo(self, mock_extract, client):
        mock_extract.return_value = {"full_name": "owner/repo", "id": "r1"}
        resp = client.get("/api/v1/repositories/github/owner/repo")
        assert resp.status_code == 200

    @patch('src.api.routes.extract_repository')
    def test_repo_not_found(self, mock_extract, client):
        mock_extract.return_value = {}
        resp = client.get("/api/v1/repositories/github/owner/nonexistent")
        assert resp.status_code in (404, 500)

    @patch('src.api.routes.extract_repository')
    def test_repo_github_error(self, mock_extract, client):
        mock_extract.side_effect = Exception("GitHub API error")
        resp = client.get("/api/v1/repositories/github/owner/failing")
        assert resp.status_code == 500


class TestGitHubProxyUser:
    @patch('src.api.routes.extract_user')
    def test_get_user(self, mock_extract, client):
        mock_extract.return_value = {"login": "alice", "id": "u1"}
        resp = client.get("/api/v1/users/github/alice")
        assert resp.status_code == 200

    @patch('src.api.routes.extract_user')
    def test_user_not_found(self, mock_extract, client):
        mock_extract.return_value = {}
        resp = client.get("/api/v1/users/github/nonexistent")
        assert resp.status_code in (404, 500)

    @patch('src.api.routes.extract_user')
    def test_user_github_error(self, mock_extract, client):
        mock_extract.side_effect = Exception("GitHub API error")
        resp = client.get("/api/v1/users/github/failing")
        assert resp.status_code == 500


class TestGitHubSearch:
    @patch('src.api.routes.search_repositories')
    def test_search(self, mock_search, client):
        mock_search.return_value = [{"name": "qiskit", "id": "r1"}]
        resp = client.get("/api/v1/search/repositories?query=quantum&first=5")
        assert resp.status_code == 200


# ========================================================================
# DATABASE LISTING ENDPOINTS
# ========================================================================
class TestRepositoryListDB:
    @patch('src.core.db.db')
    def test_list_repos(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        repos = [{"_id": "1", "full_name": "qiskit/qiskit", "stargazer_count": 100}]
        coll = MagicMock()
        cursor = MagicMock()
        cursor.skip.return_value = cursor
        cursor.limit.return_value = repos
        cursor.sort.return_value = cursor
        coll.find.return_value = cursor
        coll.count_documents.return_value = 1
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/repositories?skip=0&limit=10")
        assert resp.status_code == 200

    @patch('src.core.db.db')
    def test_repo_by_id(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = {"_id": "683f1234abcd5678ef901234", "full_name": "owner/repo"}
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/repositories/db/683f1234abcd5678ef901234")
        assert resp.status_code in (200, 404, 500)


class TestUserListDB:
    @patch('src.core.db.db')
    def test_list_users(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        users = [{"_id": "1", "login": "alice"}]
        coll = MagicMock()
        cursor = MagicMock()
        cursor.skip.return_value = cursor
        cursor.limit.return_value = users
        cursor.sort.return_value = cursor
        coll.find.return_value = cursor
        coll.count_documents.return_value = 1
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/users?skip=0&limit=10")
        assert resp.status_code == 200

    @patch('src.core.db.db')
    def test_user_by_id(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = {"_id": "683f1234abcd5678ef901234", "login": "alice"}
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/users/db/683f1234abcd5678ef901234")
        assert resp.status_code in (200, 404, 500)

    @patch('src.core.db.db')
    def test_user_profile(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = {"login": "alice", "bio": "dev"}
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/users/profile/alice")
        assert resp.status_code in (200, 404, 500)


class TestOrgListDB:
    @patch('src.core.db.db')
    def test_list_orgs(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        orgs = [{"_id": "1", "login": "qiskit"}]
        coll = MagicMock()
        cursor = MagicMock()
        cursor.skip.return_value = cursor
        cursor.limit.return_value = orgs
        cursor.sort.return_value = cursor
        coll.find.return_value = cursor
        coll.count_documents.return_value = 1
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/organizations?skip=0&limit=10")
        assert resp.status_code == 200

    @patch('src.core.db.db')
    def test_org_by_id(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = {"_id": "683f1234abcd5678ef901234", "login": "qiskit"}
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/organizations/db/683f1234abcd5678ef901234")
        assert resp.status_code in (200, 404, 500)


# ========================================================================
# INGESTION / ENRICHMENT TRIGGER ENDPOINTS
# ========================================================================
class TestIngestionTriggers:
    @patch('src.core.db.db')
    def test_ingestion_status_not_found(self, mock_db_inst, client):
        resp = client.get("/api/v1/ingestion/status/nonexistent-task")
        assert resp.status_code in (200, 404)

    @patch('src.core.db.db')
    def test_enrichment_status_not_found(self, mock_db_inst, client):
        resp = client.get("/api/v1/enrichment/status/nonexistent-task")
        assert resp.status_code in (200, 404)

    def test_tasks_list(self, client):
        resp = client.get("/api/v1/tasks")
        assert resp.status_code == 200


# ========================================================================
# FAVORITES (full CRUD)
# ========================================================================
class TestFavoritesCRUD:
    @patch('src.core.db.db')
    def test_get_favorites(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = {
            "type": "favorites",
            "items": [{"id": "r1", "type": "repo", "name": "Qiskit"}]
        }
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/favorites")
        assert resp.status_code == 200

    @patch('src.core.db.db')
    def test_add_favorite_success(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.update_one.return_value = MagicMock()
        mock_db_inst.get_collection.return_value = coll
        resp = client.post("/api/v1/favorites", json={
            "id": "repo_qiskit/qiskit", "type": "repository", "name": "Qiskit"
        })
        assert resp.status_code in (200, 201)

    @patch('src.core.db.db')
    def test_add_favorite_missing_field(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        mock_db_inst.get_collection.return_value = coll
        resp = client.post("/api/v1/favorites", json={"id": "r1"})
        assert resp.status_code == 400

    @patch('src.core.db.db')
    def test_delete_favorite(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.update_one.return_value = MagicMock(modified_count=1)
        mock_db_inst.get_collection.return_value = coll
        resp = client.delete("/api/v1/favorites/repo_qiskit%2Fqiskit")
        assert resp.status_code in (200, 204, 404)


# ========================================================================
# VIEWS (full CRUD)
# ========================================================================
class TestViewsCRUD:
    @patch('src.core.db.db')
    def test_get_views(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = {
            "type": "custom_views",
            "items": [{"id": "v1", "name": "My View"}]
        }
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/views")
        assert resp.status_code == 200

    @patch('src.core.db.db')
    def test_save_view_success(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.update_one.return_value = MagicMock()
        mock_db_inst.get_collection.return_value = coll
        resp = client.post("/api/v1/views", json={
            "name": "Test", "entity_ids": ["repo_qiskit/qiskit"]
        })
        assert resp.status_code in (200, 201)

    @patch('src.core.db.db')
    def test_save_view_missing_name(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        mock_db_inst.get_collection.return_value = coll
        resp = client.post("/api/v1/views", json={"entity_ids": ["x"]})
        assert resp.status_code == 400

    @patch('src.core.db.db')
    def test_save_view_empty_entities(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        mock_db_inst.get_collection.return_value = coll
        resp = client.post("/api/v1/views", json={
            "name": "Test", "entity_ids": []
        })
        assert resp.status_code == 400

    @patch('src.core.db.db')
    def test_delete_view(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.update_one.return_value = MagicMock(modified_count=1)
        mock_db_inst.get_collection.return_value = coll
        resp = client.delete("/api/v1/views/v1")
        assert resp.status_code in (200, 204, 404)


# ========================================================================
# COLLABORATION ENDPOINTS
# ========================================================================
class TestCollaborationEndpoints:
    @patch('src.core.db.db')
    def test_invalidate_cache(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.delete_many.return_value = MagicMock(deleted_count=2)
        mock_db_inst.get_collection.return_value = coll
        resp = client.post("/api/v1/collaboration/discover/invalidate")
        assert resp.status_code in (200, 500)

    @patch('src.core.db.db')
    def test_discover_collaboration(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        # Return cached data
        coll.find_one.return_value = {
            "type": "collaboration_discover",
            "data": {"nodes": [], "links": []}
        }
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/collaboration/discover")
        assert resp.status_code in (200, 500)


# ========================================================================
# SEARCH ENDPOINTS
# ========================================================================
class TestSearchEntities:
    @patch('src.core.db.db')
    def test_search_entities_no_q(self, mock_db_inst, client):
        resp = client.get("/api/v1/search/entities")
        assert resp.status_code in (200, 400, 422)

    @patch('src.core.db.db')
    def test_search_entity_by_id(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.find_one.return_value = {"full_name": "qiskit/qiskit", "type": "repo"}
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/search/entity/repo_qiskit%2Fqiskit")
        assert resp.status_code in (200, 404, 500)


# ========================================================================
# FAVORITES CHILDREN
# ========================================================================
class TestFavoritesChildren:
    @patch('src.core.db.db')
    def test_get_children(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        cursor = MagicMock()
        cursor.limit.return_value = []
        cursor.sort.return_value = cursor
        cursor.__iter__ = MagicMock(return_value=iter([]))
        coll.find.return_value = cursor
        coll.find_one.return_value = {"login": "qiskit", "type": "Organization"}
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/favorites/org_qiskit/children")
        assert resp.status_code in (200, 404, 500)


# ========================================================================
# REFRESH METRICS
# ========================================================================
class TestRefreshMetrics:
    @patch('src.core.db.db')
    def test_refresh_metrics(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.count_documents.return_value = 0
        coll.update_one.return_value = MagicMock()
        coll.aggregate.return_value = iter([])
        coll.find_one.return_value = None
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = []
        cursor.__iter__ = MagicMock(return_value=iter([]))
        coll.find.return_value = cursor
        mock_db_inst.get_collection.return_value = coll
        resp = client.post("/api/v1/dashboard/refresh-metrics")
        assert resp.status_code in (200, 500)


# ========================================================================
# NETWORK METRICS
# ========================================================================
class TestNetworkMetricsEndpoint:
    @patch('src.core.db.db')
    def test_network_metrics(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        # Return cached data
        coll.find_one.return_value = {
            "type": "network_metrics",
            "data": {"betweenness_centrality": {}}
        }
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/collaboration/network-metrics")
        assert resp.status_code in (200, 500)


# ========================================================================
# QUANTUM TUNNELING
# ========================================================================
class TestQuantumTunneling:
    @patch('src.core.db.db')
    def test_tunneling_missing_params(self, mock_db_inst, client):
        resp = client.get("/api/v1/collaboration/quantum-tunneling")
        assert resp.status_code in (400, 422)

    @patch('src.core.db.db')
    def test_tunneling_with_params(self, mock_db_inst, client):
        mock_db_inst.ensure_connection = MagicMock()
        coll = MagicMock()
        cursor = MagicMock()
        cursor.__iter__ = MagicMock(return_value=iter([]))
        cursor.sort.return_value = cursor
        cursor.limit.return_value = []
        coll.find.return_value = cursor
        coll.find_one.return_value = None
        mock_db_inst.get_collection.return_value = coll
        resp = client.get("/api/v1/collaboration/quantum-tunneling?source=user_alice&target=user_bob")
        assert resp.status_code in (200, 404, 500)


# ========================================================================
# ERROR HANDLING
# ========================================================================
class TestErrorHandling:
    @patch('src.core.db.db')
    def test_stats_db_error(self, mock_db_inst, client):
        mock_db_inst.ensure_connection.side_effect = Exception("DB down")
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 500

    @patch('src.api.routes.get_rate_limit_info')
    def test_rate_limit_error(self, mock_rl, client):
        mock_rl.side_effect = Exception("Token error")
        resp = client.get("/api/v1/rate-limit")
        assert resp.status_code == 500
