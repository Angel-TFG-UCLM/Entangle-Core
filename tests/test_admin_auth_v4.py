"""Tests for admin_routes auth, history, db-stats and helper functions."""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _mock_coll(**kw):
    c = MagicMock()
    c.find_one.return_value = kw.get("find_one", None)
    c.count_documents.return_value = kw.get("count", 0)
    c.delete_many.return_value = MagicMock(deleted_count=kw.get("deleted", 0))
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = list(kw.get("find_list", []))
    c.find.return_value = cursor
    c.insert_one.return_value = MagicMock(inserted_id="x")
    c.update_one.return_value = MagicMock(modified_count=1)
    return c


# ==================== has-password ====================

class TestHasPassword:
    @patch('src.api.admin_routes.db')
    def test_has_password_false(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll(count=0)
        resp = client.get("/api/v1/admin/has-password")
        assert resp.status_code == 200
        assert resp.json()["has_password"] is False

    @patch('src.api.admin_routes.db')
    def test_has_password_true(self, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_db.get_collection.return_value = _mock_coll(count=1)
        resp = client.get("/api/v1/admin/has-password")
        assert resp.status_code == 200
        assert resp.json()["has_password"] is True


# ==================== auth ====================

class TestAdminAuth:
    @patch('src.api.admin_routes._has_password_set', return_value=False)
    def test_auth_no_password_set(self, mock_has, client):
        resp = client.post("/api/v1/admin/auth", json={"password": "test"})
        assert resp.status_code == 403

    @patch('src.api.admin_routes._verify_password', return_value=False)
    @patch('src.api.admin_routes._has_password_set', return_value=True)
    def test_auth_wrong_password(self, mock_has, mock_verify, client):
        resp = client.post("/api/v1/admin/auth", json={"password": "wrong"})
        assert resp.status_code == 401

    @patch('src.api.admin_routes._verify_password', return_value=True)
    @patch('src.api.admin_routes._has_password_set', return_value=True)
    def test_auth_success(self, mock_has, mock_verify, client):
        resp = client.post("/api/v1/admin/auth", json={"password": "correct"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert "token" in data


# ==================== setup-password ====================

class TestSetupPassword:
    @patch('src.api.admin_routes._has_password_set', return_value=False)
    @patch('src.api.admin_routes._get_admin_collection')
    def test_setup_first_password(self, mock_col_fn, mock_has, client):
        mock_col_fn.return_value = _mock_coll()
        resp = client.post("/api/v1/admin/setup-password", json={"password": "newpass123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["is_new"] is True

    @patch('src.api.admin_routes._has_password_set', return_value=True)
    @patch('src.api.admin_routes._get_admin_collection')
    def test_change_password_missing_current(self, mock_col_fn, mock_has, client):
        mock_col_fn.return_value = _mock_coll()
        resp = client.post("/api/v1/admin/setup-password", json={"password": "newpass"})
        assert resp.status_code == 400

    @patch('src.api.admin_routes._verify_password', return_value=False)
    @patch('src.api.admin_routes._has_password_set', return_value=True)
    @patch('src.api.admin_routes._get_admin_collection')
    def test_change_password_wrong_current(self, mock_col_fn, mock_has, mock_verify, client):
        mock_col_fn.return_value = _mock_coll()
        resp = client.post("/api/v1/admin/setup-password", json={
            "password": "newpass", "current_password": "bad"
        })
        assert resp.status_code == 401

    @patch('src.api.admin_routes._verify_password', return_value=True)
    @patch('src.api.admin_routes._has_password_set', return_value=True)
    @patch('src.api.admin_routes._get_admin_collection')
    def test_change_password_success(self, mock_col_fn, mock_has, mock_verify, client):
        mock_col_fn.return_value = _mock_coll()
        resp = client.post("/api/v1/admin/setup-password", json={
            "password": "newpass", "current_password": "correct"
        })
        assert resp.status_code == 200
        assert resp.json()["is_new"] is False


# ==================== history ====================

class TestHistory:
    @patch('src.api.admin_routes._get_history_collection')
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_get_history(self, mock_admin, mock_hist_fn, client):
        mock_hist_fn.return_value = _mock_coll(find_list=[
            {"operation_id": "op1", "status": "completed"}
        ])
        resp = client.get("/api/v1/admin/history?token=fake")
        assert resp.status_code == 200
        data = resp.json()
        assert "operations" in data

    @patch('src.api.admin_routes._get_history_collection')
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_get_history_with_filter(self, mock_admin, mock_hist_fn, client):
        mock_hist_fn.return_value = _mock_coll(find_list=[])
        resp = client.get("/api/v1/admin/history?token=fake&operation_type=ingestion")
        assert resp.status_code == 200

    @patch('src.api.admin_routes._get_history_collection')
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_clear_history(self, mock_admin, mock_hist_fn, client):
        mock_hist_fn.return_value = _mock_coll(deleted=5)
        resp = client.delete("/api/v1/admin/history?token=fake")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == 5


# ==================== db-stats ====================

class TestDbStats:
    @patch('src.api.admin_routes.db')
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_db_stats(self, mock_admin, mock_db, client):
        mock_db.ensure_connection = MagicMock()
        mock_database = MagicMock()
        mock_col = MagicMock()
        mock_col.count_documents.return_value = 42
        mock_col.find_one.return_value = {"ingested_at": "2024-01-01"}
        mock_database.__getitem__ = MagicMock(return_value=mock_col)
        mock_database.get_collection.return_value = _mock_coll()
        mock_db.get_database.return_value = mock_database
        resp = client.get("/api/v1/admin/db-stats?token=fake")
        assert resp.status_code == 200
        data = resp.json()
        assert "collections" in data


# ==================== operations/active + status ====================

class TestOperationEndpoints:
    @patch('src.api.admin_routes.active_operations', {
        "op_1": {"operation_id": "op_1", "status": "running"},
        "op_2": {"operation_id": "op_2", "status": "completed"},
    })
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_active_operations(self, mock_admin, client):
        resp = client.get("/api/v1/admin/operations/active?token=fake")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    @patch('src.api.admin_routes.active_operations', {
        "op_1": {"operation_id": "op_1", "status": "completed"}
    })
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_get_operation_status_in_memory(self, mock_admin, client):
        resp = client.get("/api/v1/admin/operations/op_1?token=fake")
        assert resp.status_code == 200
        assert resp.json()["operation_id"] == "op_1"

    @patch('src.api.admin_routes._get_history_collection')
    @patch('src.api.admin_routes.active_operations', {})
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_get_operation_status_from_history(self, mock_admin, mock_hist_fn, client):
        mock_hist_fn.return_value = _mock_coll(find_one={"operation_id": "op_old", "status": "completed"})
        resp = client.get("/api/v1/admin/operations/op_old?token=fake")
        assert resp.status_code == 200

    @patch('src.api.admin_routes._get_history_collection')
    @patch('src.api.admin_routes.active_operations', {})
    @patch('src.api.admin_routes._require_admin', return_value=None)
    def test_get_operation_status_not_found(self, mock_admin, mock_hist_fn, client):
        mock_hist_fn.return_value = _mock_coll(find_one=None)
        resp = client.get("/api/v1/admin/operations/missing?token=fake")
        assert resp.status_code == 404


# ==================== _verify_password + _save_to_history helpers ====================

class TestHelpers:
    @patch('src.api.admin_routes._get_admin_collection')
    def test_verify_password_no_doc(self, mock_col_fn):
        from src.api.admin_routes import _verify_password
        mock_col_fn.return_value = _mock_coll(find_one=None)
        assert _verify_password("test") is False

    @patch('src.api.admin_routes._get_admin_collection')
    def test_verify_password_exception(self, mock_col_fn):
        from src.api.admin_routes import _verify_password
        mock_col_fn.side_effect = Exception("db error")
        assert _verify_password("test") is False

    def test_save_to_history(self):
        from src.api.admin_routes import _save_to_history
        with patch('src.api.admin_routes._get_history_collection') as mock_fn:
            mock_fn.return_value = _mock_coll()
            _save_to_history({
                "operation_id": "op1", "operation_type": "ingestion",
                "status": "completed", "started_at": "2024-01-01"
            })
            mock_fn.return_value.insert_one.assert_called_once()

    def test_update_progress(self):
        from src.api.admin_routes import _update_progress, active_operations
        active_operations["test_op"] = {
            "progress_message": "", "items_processed": 0,
            "items_total": 0, "progress": 0
        }
        _update_progress("test_op", "Processing...", 50, 100)
        assert active_operations["test_op"]["progress"] == 50.0
        assert active_operations["test_op"]["progress_message"] == "Processing..."
        del active_operations["test_op"]

    def test_update_progress_no_op(self):
        from src.api.admin_routes import _update_progress
        _update_progress("nonexistent", "msg")  # should not raise
