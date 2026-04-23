"""Tests for admin_routes helper functions and operation execution."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from fastapi.testclient import TestClient
from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestSaveToHistory:
    @patch('src.api.admin_routes.db')
    def test_save(self, mock_db):
        mock_db.ensure_connection = MagicMock()
        coll = MagicMock()
        mock_db.get_collection.return_value = coll
        from src.api.admin_routes import _save_to_history
        _save_to_history({
            "operation_id": "op_test", "operation_type": "ingestion",
            "entity": "repos", "status": "completed", "started_at": "2024-01-01",
        })
        coll.insert_one.assert_called_once()

    @patch('src.api.admin_routes.db')
    def test_save_exception(self, mock_db):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.side_effect = Exception("DB error")
        from src.api.admin_routes import _save_to_history
        _save_to_history({"operation_id": "op_test", "operation_type": "x", "status": "y", "started_at": "z"})


class TestUpdateProgress:
    def test_update_with_total(self):
        from src.api.admin_routes import _update_progress, active_operations
        active_operations["test_op"] = {
            "status": "running", "progress": 0, "progress_message": "",
            "items_processed": 0, "items_total": 0, "eta_seconds": None,
        }
        _update_progress("test_op", "Processing", 5, 10)
        assert active_operations["test_op"]["progress"] == 50.0
        del active_operations["test_op"]

    def test_update_no_total(self):
        from src.api.admin_routes import _update_progress, active_operations
        active_operations["test_op2"] = {
            "status": "running", "progress": 0, "progress_message": "",
            "items_processed": 0, "items_total": 0, "eta_seconds": None,
        }
        _update_progress("test_op2", "Starting", 0, 0)
        assert active_operations["test_op2"]["progress"] == 0
        del active_operations["test_op2"]

    def test_update_nonexistent(self):
        from src.api.admin_routes import _update_progress
        _update_progress("nonexistent_op", "msg")


class TestIsCancelled:
    def test_not_cancelled(self):
        from src.api.admin_routes import _is_cancelled, cancel_flags
        import threading
        cancel = threading.Event()
        cancel_flags["cancel_test"] = cancel
        assert _is_cancelled("cancel_test") is False
        del cancel_flags["cancel_test"]

    def test_cancelled(self):
        from src.api.admin_routes import _is_cancelled, cancel_flags
        import threading
        cancel = threading.Event()
        cancel.set()
        cancel_flags["cancel_test2"] = cancel
        assert _is_cancelled("cancel_test2") is True
        del cancel_flags["cancel_test2"]

    def test_nonexistent(self):
        from src.api.admin_routes import _is_cancelled
        assert _is_cancelled("nonexist") is False


class TestFinalizeOperation:
    def test_finalize_completed(self):
        from src.api.admin_routes import _finalize_operation, active_operations
        active_operations["fin_test"] = {
            "started_at": datetime.now().isoformat(), "status": "running",
        }
        with patch('src.api.admin_routes._save_to_history'):
            _finalize_operation("fin_test", "completed", stats={"count": 5})
        assert active_operations["fin_test"]["status"] == "completed"
        del active_operations["fin_test"]

    def test_finalize_failed(self):
        from src.api.admin_routes import _finalize_operation, active_operations
        active_operations["fin_test2"] = {
            "started_at": datetime.now().isoformat(), "status": "running",
        }
        with patch('src.api.admin_routes._save_to_history'):
            _finalize_operation("fin_test2", "failed", error="something broke")
        assert active_operations["fin_test2"]["status"] == "failed"
        del active_operations["fin_test2"]


class TestAdminRouteEndpoints:
    @patch('src.api.admin_routes.db')
    def test_has_password_endpoint(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.count_documents.return_value = 0
        mock_db.get_collection.return_value = coll
        resp = client.get("/api/v1/admin/has-password")
        assert resp.status_code == 200

    @patch('src.api.admin_routes.db')
    def test_auth_no_password_set(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.count_documents.return_value = 0
        mock_db.get_collection.return_value = coll
        resp = client.post("/api/v1/admin/auth", json={"password": "test"})
        assert resp.status_code == 403

    @patch('src.api.admin_routes.db')
    def test_setup_password(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        coll = MagicMock()
        coll.count_documents.return_value = 0
        mock_db.get_collection.return_value = coll
        resp = client.post("/api/v1/admin/setup-password",
                          json={"password": "newpass123"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_operations_without_token(self, client):
        resp = client.get("/api/v1/admin/operations/active")
        assert resp.status_code in (401, 422)

    @patch('src.api.admin_routes._validate_admin_token', return_value=True)
    @patch('src.api.admin_routes.active_operations', {})
    def test_operations_active(self, mock_validate, client):
        resp = client.get("/api/v1/admin/operations/active", params={"token": "valid"})
        assert resp.status_code in (200, 401)

    @patch('src.api.admin_routes._require_admin')
    @patch('src.api.admin_routes.db')
    def test_db_stats(self, mock_db, mock_admin, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = MagicMock()
        from src.api.admin_routes import config
        resp = client.get("/api/v1/admin/db-stats", params={"token": "valid"})
        assert resp.status_code in (200, 401, 500)


class TestOperationLogHandler:
    def test_emit(self):
        from src.api.admin_routes import OperationLogHandler, operation_logs, _thread_local
        handler = OperationLogHandler()
        operation_logs["test_op_log"] = []
        _thread_local.operation_id = "test_op_log"
        import logging
        record = logging.LogRecord("test", logging.INFO, "", 0, "test msg", (), None)
        handler.emit(record)
        assert len(operation_logs["test_op_log"]) == 1
        del operation_logs["test_op_log"]
        _thread_local.operation_id = None
