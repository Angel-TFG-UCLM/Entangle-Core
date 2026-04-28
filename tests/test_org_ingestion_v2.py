"""Tests for OrganizationIngestionEngine - untested methods."""
import threading
import time
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone, timedelta

from src.github.organization_ingestion import OrganizationIngestionEngine
from src.models.organization import Organization


def _make_engine(**kwargs):
    """Create engine with mocked dependencies."""
    defaults = dict(
        github_token="ghp_fake",
        users_repository=MagicMock(),
        organizations_repository=MagicMock(),
        batch_size=5,
        config={},
        from_scratch=False,
        progress_callback=None,
        cancel_event=None,
    )
    defaults.update(kwargs)
    with patch.object(OrganizationIngestionEngine, '__init__', lambda self, **kw: None):
        engine = OrganizationIngestionEngine.__new__(OrganizationIngestionEngine)
    # manually set attrs
    for k, v in defaults.items():
        setattr(engine, k, v)
    engine.graphql_client = MagicMock()
    engine._stats_lock = threading.Lock()
    engine._rate_limit_lock = threading.Lock()
    engine._rate_limit_until = 0
    engine.stats = {
        "total_discovered": 0,
        "total_processed": 0,
        "total_inserted": 0,
        "total_updated": 0,
        "total_skipped": 0,
        "total_errors": 0,
        "deleted_before_ingestion": 0,
        "mode": "from_scratch" if defaults.get("from_scratch") else "incremental",
        "start_time": None,
        "end_time": None,
    }
    return engine


# ==================== _discover_organizations ====================

class TestDiscoverOrganizations:
    def test_discover_returns_dict(self):
        engine = _make_engine()
        agg_results = [
            {"login": "qiskit", "repos": [{"id": "1", "name": "qiskit/terra"}], "repo_count": 1},
            {"login": "cirq", "repos": [{"id": "2", "name": "cirq/cirq"}], "repo_count": 1},
        ]
        mock_coll = MagicMock()
        mock_coll.aggregate.return_value = agg_results
        engine.users_repository.collection.database.__getitem__ = MagicMock(return_value=mock_coll)
        result = engine._discover_organizations()
        assert "qiskit" in result
        assert "cirq" in result
        assert result["qiskit"]["repo_count"] == 1

    def test_discover_empty_results(self):
        engine = _make_engine()
        mock_coll = MagicMock()
        mock_coll.aggregate.return_value = []
        engine.users_repository.collection.database.__getitem__ = MagicMock(return_value=mock_coll)
        result = engine._discover_organizations()
        assert result == {}

    def test_discover_exception_returns_empty(self):
        engine = _make_engine()
        mock_coll = MagicMock()
        mock_coll.aggregate.side_effect = Exception("DB down")
        engine.users_repository.collection.database.__getitem__ = MagicMock(return_value=mock_coll)
        result = engine._discover_organizations()
        assert result == {}


# ==================== run ====================

class TestRun:
    def test_run_incremental_no_orgs(self):
        engine = _make_engine()
        engine._discover_organizations = MagicMock(return_value={})
        engine._finalize_stats = MagicMock(return_value={"duration_seconds": 0})
        result = engine.run()
        assert result["duration_seconds"] == 0
        engine._discover_organizations.assert_called_once()

    def test_run_incremental_with_orgs(self):
        engine = _make_engine()
        orgs = {"qiskit": {"repos": [], "repo_count": 1}}
        engine._discover_organizations = MagicMock(return_value=orgs)
        engine._process_batch = MagicMock()
        engine._finalize_stats = MagicMock(return_value=engine.stats)
        result = engine.run(force_update=False)
        engine._process_batch.assert_called_once_with(orgs, False)

    def test_run_from_scratch_calls_cleanup(self):
        engine = _make_engine(from_scratch=True)
        engine._cleanup_collection = MagicMock()
        engine._discover_organizations = MagicMock(return_value={})
        engine._finalize_stats = MagicMock(return_value=engine.stats)
        engine.run()
        engine._cleanup_collection.assert_called_once()

    def test_run_from_scratch_forces_update(self):
        engine = _make_engine(from_scratch=True)
        engine._cleanup_collection = MagicMock()
        orgs = {"org1": {"repos": [], "repo_count": 1}}
        engine._discover_organizations = MagicMock(return_value=orgs)
        engine._process_batch = MagicMock()
        engine._finalize_stats = MagicMock(return_value=engine.stats)
        engine.run(force_update=False)
        # from_scratch sets force_update=True internally
        engine._process_batch.assert_called_once_with(orgs, True)


# ==================== _process_batch ====================

class TestProcessBatch:
    def test_incremental_skips_existing(self):
        engine = _make_engine()
        engine._get_existing_orgs = MagicMock(return_value={"existorg": {"login": "existorg"}})
        engine._process_orgs_batched = MagicMock()
        orgs_data = {"existorg": {"repos": [], "repo_count": 1}}
        engine._process_batch(orgs_data, force_update=False)
        assert engine.stats["total_skipped"] == 1
        engine._process_orgs_batched.assert_not_called()

    def test_force_update_processes_existing(self):
        engine = _make_engine()
        engine._get_existing_orgs = MagicMock(return_value={"existorg": {"login": "existorg"}})
        engine._process_orgs_batched = MagicMock()
        orgs_data = {"existorg": {"repos": [], "repo_count": 1}}
        engine._process_batch(orgs_data, force_update=True)
        assert engine._process_orgs_batched.call_count == 1

    def test_new_orgs_are_processed(self):
        engine = _make_engine()
        engine._get_existing_orgs = MagicMock(return_value={})
        engine._process_orgs_batched = MagicMock()
        orgs_data = {"neworg": {"repos": [], "repo_count": 1}}
        engine._process_batch(orgs_data, force_update=False)
        engine._process_orgs_batched.assert_called_once()


# ==================== _process_org_data ====================

class TestProcessOrgData:
    def test_returns_dict_with_is_relevant(self):
        engine = _make_engine()
        org_data = {
            "id": "O_123", "login": "qiskit", "name": "Qiskit",
            "description": "Quantum SDK", "email": None, "url": "https://github.com/qiskit",
            "avatarUrl": "https://avatars.githubusercontent.com/u/12345",
            "websiteUrl": None, "twitterUsername": None, "location": None,
            "isVerified": True, "createdAt": "2017-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
            "repositories": {"totalCount": 50},
            "membersWithRole": {"totalCount": 100},
            "sponsorshipsAsMaintainer": {"totalCount": 0},
        }
        discovered = {"repos": [{"id": "1", "name": "qiskit/terra"}], "repo_count": 1}
        result = engine._process_org_data(org_data, "qiskit", discovered)
        assert result["is_relevant"] is True
        assert result["discovered_from_repos"] == discovered["repos"]
        assert result["login"] == "qiskit"


# ==================== _fetch_organization_basic ====================

class TestFetchOrganizationBasic:
    def test_success(self):
        engine = _make_engine()
        org_resp = {"id": "O_1", "login": "org1", "avatarUrl": "http://img"}
        engine.graphql_client.execute_query.return_value = {
            "data": {"organization": org_resp}
        }
        result = engine._fetch_organization_basic("org1")
        assert result == org_resp

    def test_not_found_error(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = {
            "errors": [{"type": "NOT_FOUND", "message": "not found"}]
        }
        result = engine._fetch_organization_basic("gone")
        assert result is None

    def test_other_error(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = {
            "errors": [{"type": "INTERNAL", "message": "server error"}]
        }
        result = engine._fetch_organization_basic("bad")
        assert result is None

    def test_exception(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.side_effect = Exception("network")
        result = engine._fetch_organization_basic("timeout")
        assert result is None

    def test_no_data(self):
        engine = _make_engine()
        engine.graphql_client.execute_query.return_value = {"data": {"organization": None}}
        result = engine._fetch_organization_basic("empty")
        assert result is None


# ==================== _fetch_and_save_organization ====================

class TestFetchAndSaveOrganization:
    def _org_data(self):
        return {
            "id": "O_1", "login": "org1", "name": "Org One",
            "description": None, "email": None,
            "url": "https://github.com/org1",
            "avatarUrl": "https://img/1",
            "websiteUrl": None, "twitterUsername": None,
            "location": None, "isVerified": False,
            "createdAt": "2020-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
            "repositories": {"totalCount": 10},
            "membersWithRole": {"totalCount": 5},
            "sponsorshipsAsMaintainer": {"totalCount": 0},
        }

    def test_insert_new_org(self):
        engine = _make_engine()
        coll = engine.organizations_repository.collection
        coll.find_one.return_value = None
        coll.insert_one.return_value = MagicMock(inserted_id="new")
        engine._fetch_organization_basic = MagicMock(return_value=self._org_data())
        result = engine._fetch_and_save_organization("org1")
        assert result is True
        assert engine.stats["total_inserted"] == 1

    def test_skip_existing_no_force(self):
        engine = _make_engine()
        coll = engine.organizations_repository.collection
        coll.find_one.return_value = {"login": "org1"}
        result = engine._fetch_and_save_organization("org1", force_update=False)
        assert result is True
        assert engine.stats["total_skipped"] == 1

    def test_update_existing_with_force(self):
        engine = _make_engine()
        coll = engine.organizations_repository.collection
        coll.find_one.return_value = {"login": "org1", "quantum_focus_score": 0.8}
        coll.update_one.return_value = MagicMock(modified_count=1)
        engine._fetch_organization_basic = MagicMock(return_value=self._org_data())
        result = engine._fetch_and_save_organization("org1", force_update=True)
        assert result is True
        assert engine.stats["total_updated"] == 1

    def test_fetch_fails_returns_false(self):
        engine = _make_engine()
        coll = engine.organizations_repository.collection
        coll.find_one.return_value = None
        engine._fetch_organization_basic = MagicMock(return_value=None)
        result = engine._fetch_and_save_organization("org1")
        assert result is False
        assert engine.stats["total_errors"] == 1

    def test_exception_returns_false(self):
        engine = _make_engine()
        coll = engine.organizations_repository.collection
        coll.find_one.side_effect = Exception("db down")
        result = engine._fetch_and_save_organization("org1")
        assert result is False
        assert engine.stats["total_errors"] == 1


# ==================== _fetch_and_save_batch ====================

class TestFetchAndSaveBatch:
    def _org_graphql(self, login):
        return {
            "id": f"O_{login}", "login": login, "name": login.title(),
            "description": None, "email": None,
            "url": f"https://github.com/{login}",
            "avatarUrl": f"https://img/{login}",
            "websiteUrl": None, "twitterUsername": None,
            "location": None, "isVerified": False,
            "createdAt": "2020-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
            "repositories": {"totalCount": 10},
            "membersWithRole": {"totalCount": 5},
            "sponsorshipsAsMaintainer": {"totalCount": 0},
        }

    def test_batch_insert_new(self):
        engine = _make_engine()
        batch = [("orgA", {"repos": [], "repo_count": 1})]
        engine.graphql_client.execute_query.return_value = {
            "data": {"org0": self._org_graphql("orgA")}
        }
        coll = engine.organizations_repository.collection
        coll.insert_many.return_value = MagicMock()
        result = engine._fetch_and_save_batch(batch, {}, force_update=False)
        assert result is True
        assert engine.stats["total_processed"] == 1
        coll.insert_many.assert_called_once()

    def test_batch_update_existing(self):
        engine = _make_engine()
        batch = [("orgA", {"repos": [], "repo_count": 1})]
        engine.graphql_client.execute_query.return_value = {
            "data": {"org0": self._org_graphql("orgA")}
        }
        existing_map = {"orgA": {"login": "orgA", "quantum_focus_score": 0.5}}
        coll = engine.organizations_repository.collection
        coll.bulk_write.return_value = MagicMock()
        result = engine._fetch_and_save_batch(batch, existing_map, force_update=True)
        assert result is True
        assert engine.stats["total_updated"] == 1

    def test_batch_no_data_fallback(self):
        engine = _make_engine()
        batch = [("orgA", {"repos": [], "repo_count": 1})]
        engine.graphql_client.execute_query.return_value = {}
        engine._fetch_batch_individual_fallback = MagicMock(return_value=True)
        result = engine._fetch_and_save_batch(batch, {}, False)
        engine._fetch_batch_individual_fallback.assert_called_once()

    def test_batch_rate_limit_error(self):
        engine = _make_engine()
        batch = [("orgA", {"repos": [], "repo_count": 1})]
        engine.graphql_client.execute_query.side_effect = Exception("RATE_LIMIT exceeded")
        engine._wait_for_rate_limit_reset = MagicMock()
        result = engine._fetch_and_save_batch(batch, {}, False)
        assert result is True  # signals retry
        engine._wait_for_rate_limit_reset.assert_called_once()

    def test_batch_missing_org_increments_errors(self):
        engine = _make_engine()
        batch = [("orgA", {"repos": [], "repo_count": 1})]
        engine.graphql_client.execute_query.return_value = {"data": {"org0": None}}
        result = engine._fetch_and_save_batch(batch, {}, False)
        assert result is True
        assert engine.stats["total_errors"] == 1

    def test_batch_cancel_event(self):
        cancel_ev = threading.Event()
        cancel_ev.set()
        engine = _make_engine(cancel_event=cancel_ev)
        batch = [("orgA", {"repos": [], "repo_count": 1})]
        engine.graphql_client.execute_query.return_value = {
            "data": {"org0": self._org_graphql("orgA")}
        }
        result = engine._fetch_and_save_batch(batch, {}, False)
        assert result is True
        # should skip processing due to cancel
        assert engine.stats["total_processed"] == 0


# ==================== _fetch_batch_individual_fallback ====================

class TestFallback:
    def test_fallback_calls_individual(self):
        engine = _make_engine()
        engine._fetch_and_save_organization = MagicMock()
        batch = [("org1", {"repos": [{"id": "1"}]}), ("org2", {"repos": []})]
        result = engine._fetch_batch_individual_fallback(batch, {}, False)
        assert result is True
        assert engine._fetch_and_save_organization.call_count == 2

    def test_fallback_rate_limit_retries(self):
        engine = _make_engine()
        engine._wait_for_rate_limit_reset = MagicMock()
        engine._fetch_and_save_organization = MagicMock(
            side_effect=[Exception("RATE_LIMIT"), None]
        )
        batch = [("org1", {"repos": []})]
        engine._fetch_batch_individual_fallback(batch, {}, False)
        engine._wait_for_rate_limit_reset.assert_called_once()

    def test_fallback_other_error_increments_stats(self):
        engine = _make_engine()
        engine._fetch_and_save_organization = MagicMock(
            side_effect=Exception("random error")
        )
        batch = [("org1", {"repos": []})]
        engine._fetch_batch_individual_fallback(batch, {}, False)
        assert engine.stats["total_errors"] == 1


# ==================== _check_rate_limit ====================

class TestCheckRateLimit:
    def test_plenty_of_remaining(self):
        engine = _make_engine()
        engine.graphql_client.get_rate_limit.return_value = {"remaining": 4000}
        engine._check_rate_limit()  # should not wait or error

    def test_low_remaining_waits(self):
        engine = _make_engine()
        engine.graphql_client.get_rate_limit.return_value = {"remaining": 50}
        engine._wait_for_rate_limit_reset = MagicMock()
        engine._check_rate_limit()
        engine._wait_for_rate_limit_reset.assert_called_once()

    def test_medium_remaining_logs(self):
        engine = _make_engine()
        engine.graphql_client.get_rate_limit.return_value = {"remaining": 300}
        engine._check_rate_limit()  # just logs, no wait

    def test_exception_silent(self):
        engine = _make_engine()
        engine.graphql_client.get_rate_limit.side_effect = Exception("timeout")
        engine._check_rate_limit()  # should not raise

    @patch('time.time', return_value=100)
    def test_active_rate_limit_sleeps(self, mock_time):
        engine = _make_engine()
        engine._rate_limit_until = 105  # 5s in the future
        with patch('time.sleep') as mock_sleep:
            engine._check_rate_limit()
            mock_sleep.assert_called_once()


# ==================== _wait_for_rate_limit_reset ====================

class TestWaitForRateLimitReset:
    @patch('time.sleep')
    @patch('time.time', return_value=1000)
    def test_first_thread_sets_wait(self, mock_time, mock_sleep):
        engine = _make_engine()
        reset_at = datetime.now(timezone.utc) + timedelta(seconds=30)
        engine.graphql_client.get_rate_limit.return_value = {
            "remaining": 0, "reset_at": reset_at
        }
        engine._wait_for_rate_limit_reset()
        mock_sleep.assert_called_once()
        assert engine._rate_limit_until > 0

    @patch('time.sleep')
    @patch('time.time', return_value=1000)
    def test_already_waiting(self, mock_time, mock_sleep):
        engine = _make_engine()
        engine._rate_limit_until = 1050  # another thread set this
        engine._wait_for_rate_limit_reset()
        mock_sleep.assert_called_once()

    @patch('time.sleep')
    @patch('time.time', return_value=1000)
    def test_no_reset_at_uses_rest(self, mock_time, mock_sleep):
        engine = _make_engine()
        engine.graphql_client.get_rate_limit.return_value = {"remaining": 0}
        engine.graphql_client._get_rate_limit_rest.return_value = {
            "resources": {"graphql": {"reset": 1060}}
        }
        engine._wait_for_rate_limit_reset()
        mock_sleep.assert_called_once()

    @patch('time.sleep')
    @patch('time.time', return_value=1000)
    def test_all_fail_uses_default_120(self, mock_time, mock_sleep):
        engine = _make_engine()
        engine.graphql_client.get_rate_limit.side_effect = Exception("fail")
        engine._wait_for_rate_limit_reset()
        assert engine._rate_limit_until == 1120  # 1000 + 120


# ==================== _process_orgs_batched ====================

class TestProcessOrgsBatched:
    def test_batching_and_execution(self):
        engine = _make_engine(config={"max_concurrent_batches": 1})
        engine.GRAPHQL_BATCH_SIZE = 2
        engine._fetch_and_save_batch_with_retry = MagicMock()
        org_list = [("org1", {}), ("org2", {}), ("org3", {})]
        engine._process_orgs_batched(org_list, {}, force_update=False)
        # 3 orgs / batch_size 2 = 2 batches
        assert engine._fetch_and_save_batch_with_retry.call_count == 2

    def test_cancel_event_stops_processing(self):
        cancel_ev = threading.Event()
        cancel_ev.set()
        engine = _make_engine(cancel_event=cancel_ev, config={"max_concurrent_batches": 1})
        engine.GRAPHQL_BATCH_SIZE = 2
        engine._fetch_and_save_batch_with_retry = MagicMock()
        org_list = [("org1", {}), ("org2", {}), ("org3", {}), ("org4", {})]
        engine._process_orgs_batched(org_list, {}, force_update=False)
        # may have called some batches but should have stopped early

    def test_progress_callback_called(self):
        cb = MagicMock()
        engine = _make_engine(progress_callback=cb, config={"max_concurrent_batches": 1})
        engine.GRAPHQL_BATCH_SIZE = 5
        engine._fetch_and_save_batch_with_retry = MagicMock()
        org_list = [("org1", {})]
        engine._process_orgs_batched(org_list, {}, force_update=False)
        cb.assert_called()


# ==================== _fetch_and_save_batch_with_retry ====================

class TestFetchAndSaveBatchWithRetry:
    def test_success_first_try(self):
        engine = _make_engine()
        engine._fetch_and_save_batch = MagicMock(return_value=True)
        engine._check_rate_limit = MagicMock()
        batch = [("org1", {})]
        engine._fetch_and_save_batch_with_retry(batch, {}, False, 1, 1)
        engine._fetch_and_save_batch.assert_called_once()

    def test_retry_on_failure(self):
        engine = _make_engine()
        engine._fetch_and_save_batch = MagicMock(side_effect=[False, True])
        engine._wait_for_rate_limit_reset = MagicMock()
        engine._check_rate_limit = MagicMock()
        batch = [("org1", {})]
        engine._fetch_and_save_batch_with_retry(batch, {}, False, 1, 1)
        assert engine._fetch_and_save_batch.call_count == 2

    @patch('time.sleep')
    @patch('time.time', return_value=100)
    def test_waits_for_active_rate_limit(self, mock_time, mock_sleep):
        engine = _make_engine()
        engine._rate_limit_until = 110
        engine._fetch_and_save_batch = MagicMock(return_value=True)
        engine._check_rate_limit = MagicMock()
        engine._fetch_and_save_batch_with_retry([("org1", {})], {}, False, 1, 1)
        mock_sleep.assert_called_once()
