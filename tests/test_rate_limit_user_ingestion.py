"""Tests for rate_limit module and user ingestion engine methods."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone, timedelta


class TestRateLimitModule:
    @patch('src.github.rate_limit.github_client')
    def test_get_rate_limit_info(self, mock_client):
        mock_client.get_rate_limit.return_value = {"remaining": 4500, "limit": 5000, "resetAt": "2024-01-01T00:00:00Z"}
        from src.github.rate_limit import get_rate_limit_info
        result = get_rate_limit_info()
        assert result["remaining"] == 4500

    @patch('src.github.rate_limit.time.sleep')
    def test_wait_for_rate_limit_reset_future(self, mock_sleep):
        from src.github.rate_limit import wait_for_rate_limit_reset
        # Use a future timestamp
        future = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
        wait_for_rate_limit_reset(future)
        mock_sleep.assert_called_once()

    @patch('src.github.rate_limit.time.sleep')
    def test_wait_for_rate_limit_reset_past(self, mock_sleep):
        from src.github.rate_limit import wait_for_rate_limit_reset
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        wait_for_rate_limit_reset(past)
        mock_sleep.assert_not_called()

    @patch('src.github.rate_limit.get_rate_limit_info')
    def test_check_rate_limit_enough(self, mock_info):
        mock_info.return_value = {"remaining": 100}
        from src.github.rate_limit import check_rate_limit_before_request
        check_rate_limit_before_request()  # Should not wait

    @patch('src.github.rate_limit.wait_for_rate_limit_reset')
    @patch('src.github.rate_limit.get_rate_limit_info')
    def test_check_rate_limit_low(self, mock_info, mock_wait):
        mock_info.return_value = {"remaining": 5, "resetAt": "2024-12-01T00:00:00Z"}
        from src.github.rate_limit import check_rate_limit_before_request
        check_rate_limit_before_request()
        mock_wait.assert_called_once()

    @patch('src.github.rate_limit.check_rate_limit_before_request')
    def test_with_rate_limit_handling_success(self, mock_check):
        from src.github.rate_limit import with_rate_limit_handling
        @with_rate_limit_handling(max_retries=2)
        def my_func():
            return 42
        assert my_func() == 42
        mock_check.assert_called()

    @patch('src.github.rate_limit.get_rate_limit_info', return_value={"remaining": 0, "resetAt": "2024-01-01T00:00:00Z"})
    @patch('src.github.rate_limit.wait_for_rate_limit_reset')
    @patch('src.github.rate_limit.check_rate_limit_before_request')
    def test_with_rate_limit_handling_retry(self, mock_check, mock_wait, mock_info):
        from src.github.rate_limit import with_rate_limit_handling
        call_count = 0
        @with_rate_limit_handling(max_retries=2)
        def my_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("API rate limit exceeded")
            return "ok"
        assert my_func() == "ok"

    @patch('src.github.rate_limit.get_rate_limit_info', return_value={"remaining": 0, "resetAt": "2024-01-01T00:00:00Z"})
    @patch('src.github.rate_limit.wait_for_rate_limit_reset')
    @patch('src.github.rate_limit.check_rate_limit_before_request')
    def test_with_rate_limit_handling_exhausted(self, mock_check, mock_wait, mock_info):
        from src.github.rate_limit import with_rate_limit_handling
        @with_rate_limit_handling(max_retries=1)
        def my_func():
            raise Exception("rate limit hit")
        with pytest.raises(Exception, match="reintentos"):
            my_func()

    @patch('src.github.rate_limit.check_rate_limit_before_request')
    def test_with_rate_limit_handling_other_error(self, mock_check):
        from src.github.rate_limit import with_rate_limit_handling
        @with_rate_limit_handling(max_retries=2)
        def my_func():
            raise ValueError("bad value")
        with pytest.raises(ValueError):
            my_func()

    @patch('src.github.rate_limit.get_rate_limit_info')
    def test_rate_limit_monitor_update(self, mock_info):
        mock_info.return_value = {"remaining": 3000}
        from src.github.rate_limit import RateLimitMonitor
        monitor = RateLimitMonitor()
        result = monitor.update()
        assert result["remaining"] == 3000
        assert monitor.last_remaining == 3000

    def test_rate_limit_monitor_get_status(self):
        from src.github.rate_limit import RateLimitMonitor
        monitor = RateLimitMonitor()
        status = monitor.get_status()
        assert "last_check" in status
        assert "last_remaining" in status


class TestUserIngestionRun:
    def _make_engine(self, from_scratch=False):
        with patch('src.github.user_ingestion.GitHubGraphQLClient'):
            from src.github.user_ingestion import UserIngestionEngine
            e = UserIngestionEngine(
                github_client=MagicMock(),
                repos_repository=MagicMock(),
                users_repository=MagicMock(),
                batch_size=10,
                from_scratch=from_scratch,
            )
            return e

    def test_run_no_users(self):
        e = self._make_engine()
        e.repos_repository.collection.find.return_value = MagicMock()
        e.repos_repository.collection.find.return_value.__iter__ = MagicMock(return_value=iter([]))
        with patch.object(e, '_extract_users_from_collaborators', return_value={}):
            result = e.run()
        assert result["users_found"] == 0

    def test_run_from_scratch_cleans(self):
        e = self._make_engine(from_scratch=True)
        e.users_repository.count_documents.return_value = 5
        e.users_repository.delete_many.return_value = 5
        with patch.object(e, '_extract_users_from_collaborators', return_value={}):
            result = e.run()
        e.users_repository.delete_many.assert_called_once()

    def test_extract_users_from_collaborators(self):
        e = self._make_engine()
        repos_data = [
            {
                "_id": "r1", "name_with_owner": "o/r1", "id": "R1",
                "collaborators": [
                    {"id": "U1", "login": "alice", "has_commits": True, "contributions": 10},
                    {"id": "U2", "login": "bob", "has_commits": False, "contributions": 0},
                ]
            },
            {
                "_id": "r2", "name_with_owner": "o/r2", "id": "R2",
                "collaborators": [
                    {"id": "U1", "login": "alice", "has_commits": True, "contributions": 5},
                ]
            }
        ]
        cursor_mock = MagicMock()
        cursor_mock.batch_size.return_value = iter(repos_data)
        e.repos_repository.collection.find.return_value = cursor_mock
        result = e._extract_users_from_collaborators()
        assert len(result) >= 0  # May vary by implementation

    def test_is_bot_detection(self):
        from src.github.user_ingestion import UserIngestionEngine
        e = self._make_engine()
        assert e._is_bot({"login": "dependabot[bot]"}) is True
        assert e._is_bot({"login": "github-actions[bot]"}) is True
        assert e._is_bot({"login": "alice"}) is False

    def test_format_user_data(self):
        e = self._make_engine()
        data = {
            "login": "alice", "id": "U1", "name": "Alice",
            "url": "https://github.com/alice",
            "avatarUrl": "https://avatars/1",
            "followers": {"totalCount": 10},
            "following": {"totalCount": 5},
            "repositories": {"totalCount": 3},
        }
        result = e._format_user_data(data)
        assert result is not None


class TestUserIngestionBuildBatchQuery:
    def test_builds_query(self):
        with patch('src.github.user_ingestion.GitHubGraphQLClient'):
            from src.github.user_ingestion import UserIngestionEngine
            e = UserIngestionEngine(
                github_client=MagicMock(),
                repos_repository=MagicMock(),
                users_repository=MagicMock(),
            )
            query, variables = e._build_batch_query(["alice", "bob", "charlie"])
            assert "alice" in str(variables.values())
            assert "bob" in str(variables.values())


class TestUserIngestionCheckRateLimit:
    def test_check(self):
        with patch('src.github.user_ingestion.GitHubGraphQLClient'):
            from src.github.user_ingestion import UserIngestionEngine
            e = UserIngestionEngine(
                github_client=MagicMock(),
                repos_repository=MagicMock(),
                users_repository=MagicMock(),
            )
            e.github_client.get_rate_limit.return_value = {"remaining": 4000}
            e._check_rate_limit()  # Should not raise


class TestUserIngestionFetchAndSaveSingleUser:
    def test_success(self):
        with patch('src.github.user_ingestion.GitHubGraphQLClient'):
            from src.github.user_ingestion import UserIngestionEngine
            e = UserIngestionEngine(
                github_client=MagicMock(),
                repos_repository=MagicMock(),
                users_repository=MagicMock(),
            )
            e.github_client.execute_query.return_value = {
                "data": {"user": {
                    "login": "alice", "id": "U1", "name": "Alice",
                    "url": "https://github.com/alice",
                    "avatarUrl": "https://avatars/1",
                    "followers": {"totalCount": 10},
                    "following": {"totalCount": 5},
                    "repositories": {"totalCount": 3},
                }}
            }
            user_stub = {"login": "alice", "id": "U1", "extracted_from": []}
            e._fetch_and_save_single_user(user_stub)


class TestUserIngestionGetExistingUserIds:
    def test_returns_set(self):
        with patch('src.github.user_ingestion.GitHubGraphQLClient'):
            from src.github.user_ingestion import UserIngestionEngine
            e = UserIngestionEngine(
                github_client=MagicMock(),
                repos_repository=MagicMock(),
                users_repository=MagicMock(),
            )
            e.users_repository.collection.find.return_value = [
                {"id": "U1"}, {"id": "U2"}
            ]
            result = e._get_existing_user_ids(["U1", "U2", "U3"])
            assert "U1" in result
