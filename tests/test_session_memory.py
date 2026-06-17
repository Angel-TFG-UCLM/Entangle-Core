"""Tests for session memory (chat_sessions collection)."""
import pytest
from unittest.mock import MagicMock, patch

from src.core import session_memory


@pytest.fixture
def mock_collection(monkeypatch):
    """Inject a mock collection so tests don't need a real Mongo."""
    coll = MagicMock()
    monkeypatch.setattr(session_memory, "get_collection", lambda name: coll)
    return coll


def test_new_session_id_is_uuid_v4():
    sid = session_memory.new_session_id()
    assert len(sid) == 36
    assert sid.count("-") == 4


def test_load_history_unknown_session(mock_collection):
    mock_collection.find_one.return_value = None
    assert session_memory.load_history("does-not-exist") == []


def test_load_history_filters_system(mock_collection):
    mock_collection.find_one.return_value = {
        "messages": [
            {"role": "system", "content": "do not include"},
            {"role": "user", "content": "hello", "ts": "2026-01-01"},
            {"role": "assistant", "content": "hi", "ts": "2026-01-01"},
        ]
    }
    history = session_memory.load_history("sid")
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant"]
    # ``ts`` should be stripped
    assert all("ts" not in m for m in history)


def test_load_history_limit(mock_collection):
    mock_collection.find_one.return_value = {
        "messages": [{"role": "user", "content": str(i)} for i in range(10)]
    }
    history = session_memory.load_history("sid", limit=3)
    assert len(history) == 3
    assert [m["content"] for m in history] == ["7", "8", "9"]


def test_persist_turn_filters_system(mock_collection):
    msgs = [
        {"role": "system", "content": "ignore"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey"},
    ]
    session_memory.persist_turn("sid", msgs, user_id="u", intent="data")
    args, kwargs = mock_collection.update_one.call_args
    update = args[1]
    pushed = update["$push"]["messages"]["$each"]
    assert all(m["role"] != "system" for m in pushed)
    assert len(pushed) == 2


def test_persist_turn_empty_noop(mock_collection):
    session_memory.persist_turn("sid", [])
    mock_collection.update_one.assert_not_called()


def test_persist_turn_no_session_id_noop(mock_collection):
    session_memory.persist_turn("", [{"role": "user", "content": "hi"}])
    mock_collection.update_one.assert_not_called()


def test_persist_turn_increments_intent_counter(mock_collection):
    session_memory.persist_turn(
        "sid",
        [{"role": "user", "content": "x"}],
        intent="knowledge",
    )
    update = mock_collection.update_one.call_args[0][1]
    assert update["$inc"]["agent_calls.knowledge"] == 1
    assert update["$inc"]["turn_count"] == 1


def test_reset_session_returns_bool(mock_collection):
    mock_collection.delete_one.return_value = MagicMock(deleted_count=1)
    assert session_memory.reset_session("sid") is True
    mock_collection.delete_one.return_value = MagicMock(deleted_count=0)
    assert session_memory.reset_session("sid") is False


def test_reset_session_empty_returns_false(mock_collection):
    assert session_memory.reset_session("") is False
    mock_collection.delete_one.assert_not_called()


def test_session_stats_unknown(mock_collection):
    mock_collection.find_one.return_value = None
    assert session_memory.session_stats("sid") == {}


def test_session_stats_returns_doc_without_messages(mock_collection):
    mock_collection.find_one.return_value = {
        "session_id": "sid",
        "turn_count": 5,
        "agent_calls": {"data": 3, "knowledge": 2},
    }
    stats = session_memory.session_stats("sid")
    assert stats["turn_count"] == 5
    assert stats["agent_calls"]["data"] == 3


def test_ensure_session_indexes_creates_when_missing(mock_collection):
    mock_collection.list_indexes.return_value = []
    session_memory.ensure_session_indexes()
    # Both indexes should be created
    assert mock_collection.create_index.call_count == 2


def test_ensure_session_indexes_idempotent(mock_collection):
    mock_collection.list_indexes.return_value = [
        {"name": "session_id_unique"},
        {"name": "ttl_last_active"},
    ]
    session_memory.ensure_session_indexes()
    mock_collection.create_index.assert_not_called()


# ─────────────────── load_history error / branches ───────────────────
def test_load_history_empty_session_id(mock_collection):
    assert session_memory.load_history("") == []


def test_load_history_swallows_pymongo_error(mock_collection):
    from pymongo.errors import PyMongoError
    mock_collection.find_one.side_effect = PyMongoError("boom")
    assert session_memory.load_history("sid") == []


def test_load_history_applies_limit(mock_collection):
    mock_collection.find_one.return_value = {
        "messages": [
            {"role": "user", "content": "m1"},
            {"role": "assistant", "content": "m2"},
            {"role": "user", "content": "m3"},
        ]
    }
    history = session_memory.load_history("sid", limit=1)
    assert len(history) == 1
    assert history[0]["content"] == "m3"


# ─────────────────── persist_turn ───────────────────
def test_persist_turn_noop_without_session(mock_collection):
    session_memory.persist_turn("", [{"role": "user", "content": "x"}])
    mock_collection.update_one.assert_not_called()


def test_persist_turn_noop_without_messages(mock_collection):
    session_memory.persist_turn("sid", [])
    mock_collection.update_one.assert_not_called()


def test_persist_turn_skips_when_only_system(mock_collection):
    session_memory.persist_turn("sid", [{"role": "system", "content": "x"}])
    mock_collection.update_one.assert_not_called()


def test_persist_turn_upserts_with_intent(mock_collection):
    session_memory.persist_turn(
        "sid", [{"role": "user", "content": "hi"}], intent="DATA"
    )
    args, kwargs = mock_collection.update_one.call_args
    assert kwargs.get("upsert") is True
    update = args[1]
    assert "agent_calls.data" in update["$inc"]


def test_persist_turn_swallows_operation_failure(mock_collection):
    from pymongo.errors import OperationFailure
    mock_collection.update_one.side_effect = OperationFailure("dup")
    # Should not raise
    session_memory.persist_turn("sid", [{"role": "user", "content": "hi"}])


# ─────────────────── reset_session / session_stats ───────────────────
def test_reset_session_empty_id(mock_collection):
    assert session_memory.reset_session("") is False


def test_reset_session_deletes(mock_collection):
    mock_collection.delete_one.return_value = MagicMock(deleted_count=1)
    assert session_memory.reset_session("sid") is True


def test_reset_session_missing(mock_collection):
    mock_collection.delete_one.return_value = MagicMock(deleted_count=0)
    assert session_memory.reset_session("sid") is False


def test_session_stats_empty_id(mock_collection):
    assert session_memory.session_stats("") == {}


def test_session_stats_returns_doc(mock_collection):
    mock_collection.find_one.return_value = {"session_id": "sid", "turn_count": 3}
    assert session_memory.session_stats("sid") == {"session_id": "sid", "turn_count": 3}


def test_session_stats_missing_returns_empty(mock_collection):
    mock_collection.find_one.return_value = None
    assert session_memory.session_stats("sid") == {}


# ─────────────────── _sanitize_history ───────────────────
def test_sanitize_drops_orphan_tool():
    msgs = [
        {"role": "tool", "tool_call_id": "x", "content": "orphan"},
        {"role": "user", "content": "hi"},
    ]
    out = session_memory._sanitize_history(msgs)
    assert all(m.get("role") != "tool" for m in out)


def test_sanitize_keeps_complete_tool_group():
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "a"}]},
        {"role": "tool", "tool_call_id": "a", "content": "result"},
    ]
    out = session_memory._sanitize_history(msgs)
    assert len(out) == 2


def test_sanitize_drops_incomplete_tool_group():
    msgs = [
        {"role": "assistant", "tool_calls": [{"id": "a"}, {"id": "b"}]},
        {"role": "tool", "tool_call_id": "a", "content": "only one"},
    ]
    out = session_memory._sanitize_history(msgs)
    assert out == []
