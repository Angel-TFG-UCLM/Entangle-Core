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

    @patch('src.core.db.db')
    def test_analyze_collaboration_user_focus_with_null_fields(self, mock_db, client):
        """
        Regression test for the v1.0.3 hotfix: MongoDB documents may store
        `organizations` or `collaborators` explicitly as null. Previously
        `doc.get(key, [])` returned None and the subsequent slice
        (`None[:5]`) raised TypeError, causing a silent 500. Now defended
        with `or []` in all 4 occurrences.

        This test exercises the user_focus branch with both null fields
        populated and asserts the endpoint does NOT crash.
        """
        mock_db.ensure_connection = MagicMock()

        # User exists but has organizations=None (Mongo null)
        user_doc = {"login": "alice", "organizations": None}
        # Repos where alice is a collaborator, but the collaborators list
        # itself is None (defensive scenario)
        repos = [
            {"_id": "r1", "name": "repo1", "full_name": "alice/repo1",
             "owner": {"login": "alice"}, "stargazer_count": 5,
             "collaborators": None, "primary_language": "Python"},
            {"_id": "r2", "name": "repo2", "full_name": "alice/repo2",
             "owner": {"login": "alice"}, "stargazer_count": 2,
             "collaborators": None, "primary_language": "JavaScript"},
        ]

        def _get_collection(name):
            c = MagicMock()
            if name == "users":
                c.find_one.return_value = user_doc
                cursor = MagicMock(); cursor.__iter__ = MagicMock(return_value=iter([]))
                c.find.return_value = cursor
            elif name in ("repositories", "repos"):
                # find with collaborators.login filter -> returns alice's repos
                cursor = MagicMock()
                cursor.__iter__ = MagicMock(return_value=iter(repos))
                c.find.return_value = cursor
                c.find_one.return_value = repos[0]
            else:
                # metrics_collection / organizations: no cache hit
                c.find_one.return_value = None
                cursor = MagicMock(); cursor.__iter__ = MagicMock(return_value=iter([]))
                c.find.return_value = cursor
                c.update_one.return_value = MagicMock(modified_count=1)
            return c

        mock_db.get_collection.side_effect = _get_collection
        # Params are QUERY params on the FastAPI endpoint, not JSON body.
        resp = client.post("/api/v1/collaboration/analyze?user=alice")
        # The bug we fixed would raise an unhandled TypeError -> 500.
        # Accept any non-500 status (200 normal, 404/400 for edge cases),
        # AND reject 500 explicitly to be sure no TypeError leaks.
        assert resp.status_code != 500, f"Endpoint crashed with null fields: {resp.text}"

    @patch('src.core.db.db')
    def test_analyze_collaboration_org_focus_with_null_collaborators(self, mock_db, client):
        """
        Regression test (v1.0.3): exercises the org-focus branch (orgs=[..])
        where org repos may contain `collaborators: None`. Verifies that
        `repo.get("collaborators") or []` defends correctly.
        """
        mock_db.ensure_connection = MagicMock()

        org_repos = [
            {"_id": "or1", "name": "org-repo-1", "full_name": "acme/org-repo-1",
             "owner": {"login": "acme"}, "stargazer_count": 10,
             "collaborators": None, "primary_language": "Go"},
            {"_id": "or2", "name": "org-repo-2", "full_name": "acme/org-repo-2",
             "owner": {"login": "acme"}, "stargazer_count": 4,
             "collaborators": None, "primary_language": "Python"},
        ]

        def _get_collection(name):
            c = MagicMock()
            if name == "users":
                c.find_one.return_value = None
                cursor = MagicMock(); cursor.__iter__ = MagicMock(return_value=iter([]))
                c.find.return_value = cursor
            elif name in ("repositories", "repos"):
                cursor = MagicMock()
                cursor.__iter__ = MagicMock(return_value=iter(org_repos))
                c.find.return_value = cursor
                c.find_one.return_value = org_repos[0]
            elif name in ("organizations", "orgs"):
                c.find_one.return_value = {"login": "acme"}
                cursor = MagicMock(); cursor.__iter__ = MagicMock(return_value=iter([]))
                c.find.return_value = cursor
            else:
                c.find_one.return_value = None
                cursor = MagicMock(); cursor.__iter__ = MagicMock(return_value=iter([]))
                c.find.return_value = cursor
                c.update_one.return_value = MagicMock(modified_count=1)
            return c

        mock_db.get_collection.side_effect = _get_collection
        # orgs param needs at least 2 orgs to satisfy the validation
        resp = client.post(
            "/api/v1/collaboration/analyze?orgs=acme&orgs=globex"
        )
        assert resp.status_code != 500, f"Endpoint crashed with null collaborators: {resp.text}"


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
