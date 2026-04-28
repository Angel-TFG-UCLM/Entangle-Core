"""Tests for entity detail, search, and children endpoints to push past 60%."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _mock_coll(docs=None, find_one_result=None):
    c = MagicMock()
    docs = docs or []
    c.find_one.return_value = find_one_result
    c.count_documents.return_value = len(docs)
    cursor = MagicMock()
    cursor.limit.return_value = iter(docs)
    cursor.sort.return_value = cursor
    cursor.batch_size.return_value = cursor
    c.find.return_value = cursor
    c.aggregate.return_value = iter(docs)
    return c


# ===================== /search/entity/{entity_id} (entity detail) =====================

class TestEntityDetail:
    @patch('src.core.db.db')
    def test_user_entity_detail(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        user_doc = {"_id": "abc123", "login": "alice", "name": "Alice"}
        users_col = _mock_coll(find_one_result=user_doc)
        repos_col = _mock_coll(docs=[])
        repos_col.count_documents.return_value = 0
        collections = {"users": users_col, "repositories": repos_col}
        mock_db.get_collection.side_effect = lambda name: collections.get(name, _mock_coll())
        resp = client.get("/api/v1/search/entity/user_alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["_entity_type"] == "user"

    @patch('src.core.db.db')
    def test_repo_entity_detail(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        repo_doc = {"_id": "def456", "full_name": "org/repo", "name": "repo"}
        col = _mock_coll(find_one_result=repo_doc)
        mock_db.get_collection.return_value = col
        resp = client.get("/api/v1/search/entity/repo_org/repo")
        assert resp.status_code == 200
        data = resp.json()
        assert data["_entity_type"] == "repository"

    @patch('src.core.db.db')
    def test_org_entity_detail(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        org_doc = {"_id": "ghi789", "login": "myorg", "name": "My Org"}
        col = _mock_coll(find_one_result=org_doc)
        mock_db.get_collection.return_value = col
        resp = client.get("/api/v1/search/entity/org_myorg")
        assert resp.status_code == 200
        data = resp.json()
        assert data["_entity_type"] == "organization"

    @patch('src.core.db.db')
    def test_entity_detail_user_not_found(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        col = _mock_coll(find_one_result=None)
        mock_db.get_collection.return_value = col
        resp = client.get("/api/v1/search/entity/user_nobody")
        assert resp.status_code == 404

    @patch('src.core.db.db')
    def test_entity_detail_repo_not_found(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        col = _mock_coll(find_one_result=None)
        mock_db.get_collection.return_value = col
        resp = client.get("/api/v1/search/entity/repo_org/missing")
        assert resp.status_code == 404

    @patch('src.core.db.db')
    def test_entity_detail_invalid_id(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        resp = client.get("/api/v1/search/entity/unknown_id")
        assert resp.status_code == 400


# ===================== /search/entities (global search) =====================

class TestSearchEntitiesFull:
    @patch('src.core.db.db')
    def test_search_finds_users(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        user_col = _mock_coll(docs=[
            {"login": "quser", "name": "Quantum User", "avatar_url": "", "bio": "researcher"}
        ])
        repo_col = _mock_coll(docs=[])
        org_col = _mock_coll(docs=[])
        call_count = [0]
        def side_effect(name):
            if name == "users":
                return user_col
            elif name == "repositories":
                return repo_col
            elif name == "organizations":
                return org_col
            return _mock_coll()
        mock_db.get_collection.side_effect = side_effect
        resp = client.get("/api/v1/search/entities", params={"q": "quantum", "limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "quantum"
        assert data["count"] >= 1

    @patch('src.core.db.db')
    def test_search_finds_repos(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        users = _mock_coll(docs=[])
        repos = _mock_coll(docs=[
            {"full_name": "org/quantum-lib", "name": "quantum-lib",
             "description": "A quantum library", "stargazer_count": 100,
             "primary_language": {"name": "Python"}}
        ])
        orgs = _mock_coll(docs=[])
        def side_effect(name):
            return {"users": users, "repositories": repos, "organizations": orgs}.get(name, _mock_coll())
        mock_db.get_collection.side_effect = side_effect
        resp = client.get("/api/v1/search/entities", params={"q": "quantum"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1

    @patch('src.core.db.db')
    def test_search_finds_orgs(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        users = _mock_coll(docs=[])
        repos = _mock_coll(docs=[])
        orgs = _mock_coll(docs=[
            {"login": "quantum-org", "name": "Quantum Org",
             "description": "Quantum computing org", "avatar_url": ""}
        ])
        def side_effect(name):
            return {"users": users, "repositories": repos, "organizations": orgs}.get(name, _mock_coll())
        mock_db.get_collection.side_effect = side_effect
        resp = client.get("/api/v1/search/entities", params={"q": "quantum"})
        assert resp.status_code == 200


# ===================== /favorites/{entity_id}/children =====================

class TestChildrenEndpoint:
    @patch('src.api.routes._children_cache', {})
    @patch('src.core.db.db')
    def test_org_children(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        org_col = _mock_coll(find_one_result={"login": "myorg", "name": "My Org"})
        repos_col = _mock_coll(docs=[
            {"full_name": "myorg/repo1", "name": "repo1", "stargazer_count": 10,
             "primary_language": {"name": "Python"}, "description": "A repo"},
        ])
        def side_effect(name):
            return {"organizations": org_col, "repositories": repos_col}.get(name, _mock_coll())
        mock_db.get_collection.side_effect = side_effect
        resp = client.get("/api/v1/favorites/org_myorg/children")
        assert resp.status_code == 200
        data = resp.json()
        assert "children" in data

    @patch('src.api.routes._children_cache', {})
    @patch('src.core.db.db')
    def test_repo_children_with_collabs(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        repo_doc = {
            "full_name": "org/repo1", "collaborators": [
                {"login": "alice", "contributions": 50},
                {"login": "bob", "contributions": 10},
            ]
        }
        repos_col = _mock_coll(find_one_result=repo_doc)
        # For bridge user check: mock find returning repos with collabs
        repos_col.find.return_value = iter([
            {"collaborators": [{"login": "alice"}, {"login": "bob"}]},
            {"collaborators": [{"login": "alice"}]},
        ])
        users_col = _mock_coll(docs=[])
        users_col.find.return_value = iter([
            {"login": "alice", "name": "Alice", "avatar_url": ""},
            {"login": "bob", "name": "Bob", "avatar_url": ""},
        ])
        def side_effect(name):
            return {"repositories": repos_col, "users": users_col}.get(name, _mock_coll())
        mock_db.get_collection.side_effect = side_effect
        resp = client.get("/api/v1/favorites/repo_org/repo1/children")
        assert resp.status_code == 200
        data = resp.json()
        assert "children" in data

    @patch('src.api.routes._children_cache', {})
    @patch('src.core.db.db')
    def test_unknown_entity_children(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        resp = client.get("/api/v1/favorites/xyz_unknown/children")
        assert resp.status_code == 200
        data = resp.json()
        assert data["children"] == []

    @patch('src.api.routes._children_cache', {"cached_id": {"parent_id": "cached_id", "children": [{"id": "c1"}]}})
    @patch('src.core.db.db')
    def test_children_from_cache(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        resp = client.get("/api/v1/favorites/cached_id/children")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["children"]) == 1
