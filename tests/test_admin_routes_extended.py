"""
Extended tests for admin_routes: password, operations, history, db stats.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from fastapi.testclient import TestClient
import logging


@pytest.fixture
def client():
    from src.api.main import app
    return TestClient(app)


class TestAdminAuthentication:
    @patch('src.api.admin_routes._get_admin_collection')
    def test_check_no_password_set(self, mock_coll, client):
        col = MagicMock()
        col.count_documents.return_value = 0
        mock_coll.return_value = col
        resp = client.get("/api/v1/admin/has-password")
        assert resp.status_code == 200

    @patch('src.api.admin_routes._get_admin_collection')
    def test_check_password_set(self, mock_coll, client):
        col = MagicMock()
        col.count_documents.return_value = 1
        mock_coll.return_value = col
        resp = client.get("/api/v1/admin/has-password")
        assert resp.status_code == 200
        data = resp.json()
        assert "has_password" in data

    @patch('src.api.admin_routes._get_admin_collection')
    def test_setup_password(self, mock_coll, client):
        col = MagicMock()
        col.count_documents.return_value = 0
        mock_coll.return_value = col
        resp = client.post(
            "/api/v1/admin/setup-password",
            json={"password": "TestPass123!", "confirm_password": "TestPass123!"},
        )
        # Should succeed or return specific error
        assert resp.status_code in (200, 400, 409)

    @patch('src.api.admin_routes._get_admin_collection')
    @patch('src.api.admin_routes.bcrypt')
    def test_authenticate_wrong_password(self, mock_bcrypt, mock_coll, client):
        col = MagicMock()
        col.find_one.return_value = {
            "type": "admin_password",
            "password_hash": b"$2b$12$fakehash",
        }
        mock_coll.return_value = col
        mock_bcrypt.checkpw.return_value = False
        resp = client.post(
            "/api/v1/admin/auth",
            json={"password": "wrong"},
        )
        assert resp.status_code in (401, 403)


class TestOperationLogs:
    @patch('src.api.admin_routes._validate_admin_token')
    def test_get_logs_unknown_operation(self, mock_validate, client):
        mock_validate.return_value = True
        resp = client.get(
            "/api/v1/admin/operations/nonexistent-id/logs",
            params={"token": "valid-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["logs"] == []
        assert data["total"] == 0

    @patch('src.api.admin_routes._validate_admin_token')
    def test_get_logs_with_since(self, mock_validate, client):
        mock_validate.return_value = True
        resp = client.get(
            "/api/v1/admin/operations/some-id/logs",
            params={"token": "valid-token", "since": 0},
        )
        assert resp.status_code == 200


class TestActiveOperations:
    @patch('src.api.admin_routes._validate_admin_token')
    def test_list_active_empty(self, mock_validate, client):
        mock_validate.return_value = True
        resp = client.get(
            "/api/v1/admin/operations/active",
            params={"token": "valid-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "operations" in data

    @patch('src.api.admin_routes._validate_admin_token')
    def test_cancel_not_found(self, mock_validate, client):
        mock_validate.return_value = True
        resp = client.post(
            "/api/v1/admin/operations/nonexistent/cancel",
            params={"token": "valid-token"},
        )
        assert resp.status_code == 404


class TestOperationHistory:
    @patch('src.api.admin_routes._validate_admin_token')
    @patch('src.api.admin_routes._get_history_collection')
    def test_get_history(self, mock_hist_coll, mock_validate, client):
        mock_validate.return_value = True
        mock_coll = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = []
        mock_coll.find.return_value = mock_cursor
        mock_hist_coll.return_value = mock_coll
        resp = client.get(
            "/api/v1/admin/history",
            params={"token": "valid-token"},
        )
        assert resp.status_code == 200

    @patch('src.api.admin_routes._validate_admin_token')
    @patch('src.api.admin_routes._get_history_collection')
    def test_clear_history(self, mock_hist_coll, mock_validate, client):
        mock_validate.return_value = True
        mock_coll = MagicMock()
        mock_coll.delete_many.return_value = MagicMock(deleted_count=5)
        mock_hist_coll.return_value = mock_coll
        resp = client.delete(
            "/api/v1/admin/history",
            params={"token": "valid-token"},
        )
        assert resp.status_code == 200


class TestDbStats:
    @patch('src.api.admin_routes._validate_admin_token')
    @patch('src.api.admin_routes.db')
    def test_get_db_stats(self, mock_db, mock_validate, client):
        mock_validate.return_value = True
        mock_collection = MagicMock()
        mock_collection.count_documents.return_value = 100
        mock_collection.estimated_document_count.return_value = 100
        mock_db.get_collection.return_value = mock_collection
        resp = client.get(
            "/api/v1/admin/db-stats",
            params={"token": "valid-token"},
        )
        assert resp.status_code == 200


class TestOperationLogHandler:
    def test_emit_captures_log(self):
        from src.api.admin_routes import OperationLogHandler, operation_logs, _thread_local
        handler = OperationLogHandler()
        operation_logs["test-op"] = []
        _thread_local.operation_id = "test-op"

        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="Test message", args=(), exc_info=None,
        )
        handler.emit(record)
        assert len(operation_logs["test-op"]) == 1
        assert operation_logs["test-op"][0]["msg"] == "Test message"

        # Cleanup
        del operation_logs["test-op"]
        _thread_local.operation_id = None

    def test_emit_no_operation(self):
        from src.api.admin_routes import OperationLogHandler, _thread_local
        handler = OperationLogHandler()
        _thread_local.operation_id = None

        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="Test message", args=(), exc_info=None,
        )
        # Should not raise
        handler.emit(record)
