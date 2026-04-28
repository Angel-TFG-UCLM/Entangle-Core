"""
Tests for src.api.admin_routes
===============================
Tests for admin endpoints: authentication, operations, history.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import bcrypt
from src.api.main import app
from src.api.admin_routes import (
    active_operations,
    operation_logs,
    admin_authenticate,
)


@pytest.fixture
def client():
    return TestClient(app)


def _mock_admin_collection(has_password=False, password="admin123"):
    """Create a mock admin_config collection."""
    coll = MagicMock()
    if has_password:
        salt = bcrypt.gensalt(rounds=4)
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        coll.find_one.return_value = {
            "type": "admin_password",
            "password_hash": hashed.decode('utf-8'),
        }
        coll.count_documents.return_value = 1
    else:
        coll.find_one.return_value = None
        coll.count_documents.return_value = 0
    coll.update_one.return_value = MagicMock(modified_count=1)
    coll.delete_many.return_value = MagicMock(deleted_count=0)
    return coll


class TestCheckHasPassword:

    @patch('src.api.admin_routes._get_admin_collection')
    def test_no_password(self, mock_get_coll, client):
        mock_get_coll.return_value = _mock_admin_collection(has_password=False)
        response = client.get("/api/v1/admin/has-password")
        assert response.status_code == 200
        assert response.json()["has_password"] is False

    @patch('src.api.admin_routes._get_admin_collection')
    def test_has_password(self, mock_get_coll, client):
        mock_get_coll.return_value = _mock_admin_collection(has_password=True)
        response = client.get("/api/v1/admin/has-password")
        assert response.status_code == 200
        assert response.json()["has_password"] is True


class TestAdminAuth:

    @patch('src.api.admin_routes._get_admin_collection')
    def test_auth_success(self, mock_get_coll, client):
        mock_get_coll.return_value = _mock_admin_collection(has_password=True, password="secret123")
        response = client.post("/api/v1/admin/auth", json={"password": "secret123"})
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert "token" in data

    @patch('src.api.admin_routes._get_admin_collection')
    def test_auth_wrong_password(self, mock_get_coll, client):
        mock_get_coll.return_value = _mock_admin_collection(has_password=True, password="secret123")
        response = client.post("/api/v1/admin/auth", json={"password": "wrong"})
        assert response.status_code == 401

    @patch('src.api.admin_routes._get_admin_collection')
    def test_auth_no_password_set(self, mock_get_coll, client):
        mock_get_coll.return_value = _mock_admin_collection(has_password=False)
        response = client.post("/api/v1/admin/auth", json={"password": "anything"})
        assert response.status_code == 403


class TestSetupPassword:

    @patch('src.api.admin_routes._get_admin_collection')
    def test_setup_new_password(self, mock_get_coll, client):
        coll = _mock_admin_collection(has_password=False)
        mock_get_coll.return_value = coll
        response = client.post("/api/v1/admin/setup-password", json={"password": "newpass123"})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["is_new"] is True

    @patch('src.api.admin_routes._get_admin_collection')
    def test_change_password_requires_current(self, mock_get_coll, client):
        coll = _mock_admin_collection(has_password=True, password="oldpass")
        mock_get_coll.return_value = coll
        response = client.post("/api/v1/admin/setup-password", json={"password": "newpass"})
        assert response.status_code == 400

    @patch('src.api.admin_routes._get_admin_collection')
    def test_change_password_wrong_current(self, mock_get_coll, client):
        coll = _mock_admin_collection(has_password=True, password="oldpass")
        mock_get_coll.return_value = coll
        response = client.post("/api/v1/admin/setup-password", json={
            "password": "newpass",
            "current_password": "wrong"
        })
        assert response.status_code == 401

    @patch('src.api.admin_routes._get_admin_collection')
    def test_change_password_correct_current(self, mock_get_coll, client):
        coll = _mock_admin_collection(has_password=True, password="oldpass")
        mock_get_coll.return_value = coll
        response = client.post("/api/v1/admin/setup-password", json={
            "password": "newpass",
            "current_password": "oldpass"
        })
        assert response.status_code == 200
        assert response.json()["success"] is True


class TestProtectedEndpoints:
    """Endpoints that require admin token."""

    def _get_token(self, client, mock_get_coll_fn):
        """Helper: authenticate and return a valid token."""
        coll = _mock_admin_collection(has_password=True, password="admin123")
        mock_get_coll_fn.return_value = coll
        resp = client.post("/api/v1/admin/auth", json={"password": "admin123"})
        return resp.json()["token"]

    @patch('src.api.admin_routes._get_admin_collection')
    def test_get_active_operations(self, mock_get_coll, client):
        token = self._get_token(client, mock_get_coll)
        response = client.get(f"/api/v1/admin/operations/active?token={token}")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "operations" in data

    @patch('src.api.admin_routes._get_admin_collection')
    def test_get_active_operations_no_token(self, mock_get_coll, client):
        mock_get_coll.return_value = _mock_admin_collection()
        response = client.get("/api/v1/admin/operations/active?token=invalid")
        assert response.status_code == 401

    @patch('src.api.admin_routes._get_admin_collection')
    def test_get_operation_status_not_found(self, mock_get_coll, client):
        token = self._get_token(client, mock_get_coll)
        response = client.get(f"/api/v1/admin/operations/nonexistent?token={token}")
        assert response.status_code == 404

    @patch('src.api.admin_routes._get_admin_collection')
    def test_get_operation_logs_not_found(self, mock_get_coll, client):
        token = self._get_token(client, mock_get_coll)
        response = client.get(f"/api/v1/admin/operations/nonexistent/logs?token={token}")
        assert response.status_code == 200
        data = response.json()
        assert data["logs"] == []
        assert data["total"] == 0

    @patch('src.core.db.db')
    @patch('src.api.admin_routes._get_admin_collection')
    def test_get_history(self, mock_get_coll, mock_db_instance, client):
        token = self._get_token(client, mock_get_coll)
        coll = MagicMock()
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = []
        coll.find.return_value = cursor
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.get(f"/api/v1/admin/history?token={token}")
        assert response.status_code == 200

    @patch('src.core.db.db')
    @patch('src.api.admin_routes._get_admin_collection')
    def test_clear_history(self, mock_get_coll, mock_db_instance, client):
        token = self._get_token(client, mock_get_coll)
        coll = MagicMock()
        coll.delete_many.return_value = MagicMock(deleted_count=5)
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.delete(f"/api/v1/admin/history?token={token}")
        assert response.status_code == 200

    @patch('src.core.db.db')
    @patch('src.api.admin_routes._get_admin_collection')
    def test_get_db_stats(self, mock_get_coll, mock_db_instance, client):
        token = self._get_token(client, mock_get_coll)
        coll = MagicMock()
        coll.count_documents.return_value = 100
        mock_db_instance.get_collection.return_value = coll
        mock_db_instance.ensure_connection = MagicMock()

        response = client.get(f"/api/v1/admin/db-stats?token={token}")
        assert response.status_code == 200
