"""Tests for UserIngestionEngine untested methods."""
import threading
import time
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone, timedelta

from src.github.user_ingestion import UserIngestionEngine


def _make_engine(**kwargs):
    """Create engine with mocked dependencies."""
    with patch.object(UserIngestionEngine, '__init__', lambda self, **kw: None):
        engine = UserIngestionEngine.__new__(UserIngestionEngine)
    engine.github_client = MagicMock()
    engine.repos_repository = MagicMock()
    engine.users_repository = MagicMock()
    engine.batch_size = 5
    engine.from_scratch = kwargs.get("from_scratch", False)
    engine.progress_callback = kwargs.get("progress_callback")
    engine.cancel_event = kwargs.get("cancel_event")
    engine._stats_lock = threading.Lock()
    engine._rate_limit_lock = threading.Lock()
    engine._rate_limit_until = 0
    engine.GRAPHQL_BATCH_SIZE = 25
    engine.stats = {
        "total_discovered": 0, "users_inserted": 0, "users_existing": 0,
        "total_errors": 0, "mode": "incremental",
        "start_time": None, "end_time": None,
    }
    return engine


# ==================== _fetch_and_save_batch ====================

class TestFetchAndSaveBatch:
    def _user_graphql(self, login):
        return {
            "id": f"U_{login}", "login": login, "name": login.title(),
            "email": None, "bio": None, "company": None, "location": None,
            "url": f"https://github.com/{login}", "websiteUrl": None,
            "twitterUsername": None, "avatarUrl": f"https://img/{login}",
            "createdAt": "2020-01-01T00:00:00Z", "updatedAt": "2024-01-01T00:00:00Z",
            "followers": {"totalCount": 10}, "following": {"totalCount": 5},
            "repositories": {"totalCount": 20},
        }

    def test_batch_insert_new_users(self):
        engine = _make_engine()
        batch = [{"login": "alice", "id": "U_alice", "extracted_from": ["repo1"]}]
        engine.github_client.execute_query.return_value = {
            "data": {"user0": self._user_graphql("alice")}
        }
        coll = engine.users_repository.collection
        coll.insert_many.return_value = MagicMock()
        result = engine._fetch_and_save_batch(batch)
        assert result is True
        coll.insert_many.assert_called_once()

    def test_user_not_found(self):
        engine = _make_engine()
        batch = [{"login": "gone", "id": "U_gone", "extracted_from": []}]
        engine.github_client.execute_query.return_value = {"data": {"user0": None}}
        result = engine._fetch_and_save_batch(batch)
        assert result is True
        assert engine.stats["total_errors"] == 1

    def test_no_data_falls_back(self):
        engine = _make_engine()
        batch = [{"login": "a", "id": "U_a", "extracted_from": []}]
        engine.github_client.execute_query.return_value = {}
        engine._fetch_batch_individual_fallback = MagicMock(return_value=True)
        result = engine._fetch_and_save_batch(batch)
        engine._fetch_batch_individual_fallback.assert_called_once()

    def test_rate_limit_error(self):
        engine = _make_engine()
        batch = [{"login": "a", "id": "U_a", "extracted_from": []}]
        engine.github_client.execute_query.side_effect = Exception("403 forbidden")
        engine._wait_for_rate_limit_reset = MagicMock()
        result = engine._fetch_and_save_batch(batch)
        assert result is True
        engine._wait_for_rate_limit_reset.assert_called_once()

    def test_insert_many_error_fallback(self):
        engine = _make_engine()
        batch = [{"login": "alice", "id": "U_alice", "extracted_from": ["repo1"]}]
        engine.github_client.execute_query.return_value = {
            "data": {"user0": self._user_graphql("alice")}
        }
        coll = engine.users_repository.collection
        coll.insert_many.side_effect = Exception("dup key")
        coll.insert_one.return_value = MagicMock()
        result = engine._fetch_and_save_batch(batch)
        assert result is True
        coll.insert_one.assert_called()

    def test_cancel_event_stops(self):
        cancel_ev = threading.Event()
        cancel_ev.set()
        engine = _make_engine(cancel_event=cancel_ev)
        batch = [{"login": "a", "id": "U_a", "extracted_from": []}]
        engine.github_client.execute_query.return_value = {
            "data": {"user0": self._user_graphql("a")}
        }
        result = engine._fetch_and_save_batch(batch)
        assert result is True

    def test_generic_error_falls_back(self):
        engine = _make_engine()
        batch = [{"login": "a", "id": "U_a", "extracted_from": []}]
        engine.github_client.execute_query.side_effect = Exception("random error")
        engine._fetch_batch_individual_fallback = MagicMock(return_value=True)
        result = engine._fetch_and_save_batch(batch)
        engine._fetch_batch_individual_fallback.assert_called_once()


# ==================== _fetch_and_save_users ====================

class TestFetchAndSaveUsers:
    def test_all_new_users(self):
        engine = _make_engine()
        engine._get_existing_user_ids = MagicMock(return_value=set())
        engine._fetch_and_save_batch_with_retry = MagicMock()
        users_dict = {"U_1": {"id": "U_1", "login": "alice", "extracted_from": ["r1"]}}
        engine._fetch_and_save_users(users_dict)
        engine._fetch_and_save_batch_with_retry.assert_called()

    def test_all_existing_users(self):
        engine = _make_engine()
        engine._get_existing_user_ids = MagicMock(return_value={"U_1"})
        engine._bulk_update_extracted_from = MagicMock()
        users_dict = {"U_1": {"id": "U_1", "login": "alice", "extracted_from": ["r1"]}}
        engine._fetch_and_save_users(users_dict)
        engine._bulk_update_extracted_from.assert_called_once()

    def test_mixed_new_and_existing(self):
        engine = _make_engine()
        engine._get_existing_user_ids = MagicMock(return_value={"U_1"})
        engine._bulk_update_extracted_from = MagicMock()
        engine._fetch_and_save_batch_with_retry = MagicMock()
        users_dict = {
            "U_1": {"id": "U_1", "login": "alice", "extracted_from": ["r1"]},
            "U_2": {"id": "U_2", "login": "bob", "extracted_from": ["r2"]},
        }
        engine._fetch_and_save_users(users_dict)
        engine._bulk_update_extracted_from.assert_called_once()
        engine._fetch_and_save_batch_with_retry.assert_called()

    def test_cancel_event_stops(self):
        cancel_ev = threading.Event()
        cancel_ev.set()
        engine = _make_engine(cancel_event=cancel_ev)
        engine._get_existing_user_ids = MagicMock(return_value=set())
        engine._fetch_and_save_batch_with_retry = MagicMock()
        users_dict = {"U_1": {"id": "U_1", "login": "alice", "extracted_from": ["r1"]}}
        engine._fetch_and_save_users(users_dict)

    def test_progress_callback(self):
        cb = MagicMock()
        engine = _make_engine(progress_callback=cb)
        engine._get_existing_user_ids = MagicMock(return_value=set())
        engine._fetch_and_save_batch_with_retry = MagicMock()
        users_dict = {"U_1": {"id": "U_1", "login": "alice", "extracted_from": ["r1"]}}
        engine._fetch_and_save_users(users_dict)
        cb.assert_called()


# ==================== _bulk_update_extracted_from ====================

class TestBulkUpdateExtractedFrom:
    def test_updates_users(self):
        engine = _make_engine()
        coll = engine.users_repository.collection
        coll.bulk_write.return_value = MagicMock(modified_count=2)
        existing = [
            {"id": "U_1", "login": "alice", "extracted_from": ["r1"]},
            {"id": "U_2", "login": "bob", "extracted_from": ["r2"]},
        ]
        engine._bulk_update_extracted_from(existing)
        coll.bulk_write.assert_called_once()

    def test_large_batch_chunks(self):
        engine = _make_engine()
        coll = engine.users_repository.collection
        coll.bulk_write.return_value = MagicMock(modified_count=100)
        existing = [{"id": f"U_{i}", "login": f"u{i}", "extracted_from": [f"r{i}"]} for i in range(600)]
        engine._bulk_update_extracted_from(existing)
        assert coll.bulk_write.call_count == 2  # 500 + 100


# ==================== _fetch_batch_individual_fallback ====================

class TestFetchBatchIndividualFallback:
    def test_processes_all_users(self):
        engine = _make_engine()
        engine._fetch_and_save_single_user = MagicMock()
        batch = [{"login": "a"}, {"login": "b"}]
        result = engine._fetch_batch_individual_fallback(batch)
        assert result is True
        assert engine._fetch_and_save_single_user.call_count == 2

    def test_rate_limit_retries(self):
        engine = _make_engine()
        engine._wait_for_rate_limit_reset = MagicMock()
        engine._fetch_and_save_single_user = MagicMock(
            side_effect=[Exception("RATE_LIMIT"), None]
        )
        batch = [{"login": "a"}]
        engine._fetch_batch_individual_fallback(batch)
        engine._wait_for_rate_limit_reset.assert_called_once()

    def test_other_error_increments_stats(self):
        engine = _make_engine()
        engine._fetch_and_save_single_user = MagicMock(side_effect=Exception("random"))
        batch = [{"login": "a"}]
        engine._fetch_batch_individual_fallback(batch)
        assert engine.stats["total_errors"] == 1


# ==================== _fetch_and_save_batch_with_retry ====================

class TestFetchAndSaveBatchWithRetry:
    def test_success(self):
        engine = _make_engine()
        engine._fetch_and_save_batch = MagicMock(return_value=True)
        engine._fetch_and_save_batch_with_retry([{"login": "a"}], 1, 1)

    def test_retry_on_failure(self):
        engine = _make_engine()
        engine._fetch_and_save_batch = MagicMock(side_effect=[False, True])
        engine._wait_for_rate_limit_reset = MagicMock()
        engine._fetch_and_save_batch_with_retry([{"login": "a"}], 1, 1)
        assert engine._fetch_and_save_batch.call_count == 2

    @patch('time.sleep')
    @patch('time.time', return_value=100)
    def test_waits_for_active_rate_limit(self, mock_time, mock_sleep):
        engine = _make_engine()
        engine._rate_limit_until = 110
        engine._fetch_and_save_batch = MagicMock(return_value=True)
        engine._fetch_and_save_batch_with_retry([{"login": "a"}], 1, 1)
        mock_sleep.assert_called_once()


# ==================== _wait_for_rate_limit_reset ====================

class TestWaitForRateLimitReset:
    @patch('time.sleep')
    @patch('time.time', return_value=1000)
    def test_with_reset_at(self, mock_time, mock_sleep):
        engine = _make_engine()
        reset_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        engine.github_client.get_rate_limit.return_value = {
            "remaining": 0, "reset_at": reset_at
        }
        engine._wait_for_rate_limit_reset()
        mock_sleep.assert_called_once()
        assert engine._rate_limit_until > 0

    @patch('time.sleep')
    @patch('time.time', return_value=1000)
    def test_rest_fallback(self, mock_time, mock_sleep):
        engine = _make_engine()
        engine.github_client.get_rate_limit.return_value = {"remaining": 0}
        engine.github_client._get_rate_limit_rest.return_value = {
            "resources": {"graphql": {"reset": 1060}}
        }
        engine._wait_for_rate_limit_reset()
        mock_sleep.assert_called_once()

    @patch('time.sleep')
    @patch('time.time', return_value=1000)
    def test_exception_uses_default(self, mock_time, mock_sleep):
        engine = _make_engine()
        engine.github_client.get_rate_limit.side_effect = Exception("fail")
        engine._wait_for_rate_limit_reset()
        mock_sleep.assert_called_once()
