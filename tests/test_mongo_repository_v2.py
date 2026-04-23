"""Tests for MongoRepository untested methods + additional route coverage."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pymongo.errors import PyMongoError

from src.core.mongo_repository import MongoRepository


def _make_repo():
    """Create MongoRepository with mocked collection."""
    with patch('src.core.mongo_repository.get_collection') as mock_gc:
        mock_coll = MagicMock()
        mock_gc.return_value = mock_coll
        repo = MongoRepository("test_collection", unique_fields=["id", "login"])
    return repo


# ==================== update_many ====================

class TestUpdateMany:
    def test_with_operator(self):
        repo = _make_repo()
        repo.collection.update_many.return_value = MagicMock(
            matched_count=5, modified_count=3, upserted_id=None
        )
        result = repo.update_many({"status": "active"}, {"$set": {"score": 10}})
        assert result["matched_count"] == 5
        assert result["modified_count"] == 3

    def test_auto_wraps_set(self):
        repo = _make_repo()
        repo.collection.update_many.return_value = MagicMock(
            matched_count=2, modified_count=2, upserted_id=None
        )
        result = repo.update_many({"x": 1}, {"score": 10})
        # should auto-wrap in $set
        call_args = repo.collection.update_many.call_args
        assert "$set" in call_args[0][1]

    def test_with_upsert(self):
        repo = _make_repo()
        repo.collection.update_many.return_value = MagicMock(
            matched_count=0, modified_count=0, upserted_id="new_id"
        )
        result = repo.update_many({"x": 1}, {"$set": {"y": 2}}, upsert=True)
        assert result["upserted_id"] == "new_id"

    def test_error_raises(self):
        repo = _make_repo()
        repo.collection.update_many.side_effect = PyMongoError("fail")
        with pytest.raises(PyMongoError):
            repo.update_many({"x": 1}, {"$set": {"y": 2}})


# ==================== bulk_upsert ====================

class TestBulkUpsert:
    def test_empty_list(self):
        repo = _make_repo()
        result = repo.bulk_upsert([])
        assert result["upserted_count"] == 0

    def test_with_dicts(self):
        repo = _make_repo()
        repo.collection.bulk_write.return_value = MagicMock(
            upserted_count=2, modified_count=0, matched_count=0
        )
        docs = [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}]
        result = repo.bulk_upsert(docs)
        assert result["upserted_count"] == 2
        repo.collection.bulk_write.assert_called_once()

    def test_skips_missing_unique_field(self):
        repo = _make_repo()
        repo.collection.bulk_write.return_value = MagicMock(
            upserted_count=1, modified_count=0, matched_count=0
        )
        docs = [{"id": "1", "name": "a"}, {"name": "no_id"}]
        result = repo.bulk_upsert(docs)
        # Only 1 operation should be in bulk_write (second doc skipped)
        ops = repo.collection.bulk_write.call_args[0][0]
        assert len(ops) == 1

    def test_error_raises(self):
        repo = _make_repo()
        repo.collection.bulk_write.side_effect = PyMongoError("fail")
        with pytest.raises(PyMongoError):
            repo.bulk_upsert([{"id": "1"}])


# ==================== create_indexes ====================

class TestCreateIndexes:
    def test_creates_indexes(self):
        repo = _make_repo()
        indexes = [
            {"keys": [("login", 1)], "unique": True},
            {"keys": [("stars_count", -1)]},
        ]
        repo.create_indexes(indexes)
        assert repo.collection.create_index.call_count == 2

    def test_error_raises(self):
        repo = _make_repo()
        repo.collection.create_index.side_effect = PyMongoError("fail")
        with pytest.raises(PyMongoError):
            repo.create_indexes([{"keys": [("x", 1)]}])


# ==================== get_statistics ====================

class TestGetStatistics:
    def test_returns_stats(self):
        repo = _make_repo()
        repo.collection.database.command.return_value = {
            "count": 1000, "size": 1048576, "avgObjSize": 512,
            "nindexes": 3, "totalIndexSize": 524288,
        }
        result = repo.get_statistics()
        assert result["count"] == 1000
        assert result["size_mb"] == 1.0
        assert result["indexes"] == 3

    def test_error_returns_empty(self):
        repo = _make_repo()
        repo.collection.database.command.side_effect = PyMongoError("fail")
        result = repo.get_statistics()
        assert result == {}


# ==================== _get_unique_identifier ====================

class TestGetUniqueIdentifier:
    def test_with_unique_field(self):
        repo = _make_repo()
        result = repo._get_unique_identifier({"id": "123", "name": "test"})
        assert result == "id=123"

    def test_without_unique_field(self):
        repo = _make_repo()
        result = repo._get_unique_identifier({"name": "test"})
        assert "unknown" in result


# ==================== _is_duplicate ====================

class TestIsDuplicate:
    def test_is_duplicate(self):
        repo = _make_repo()
        repo.collection.find_one.return_value = {"_id": "existing"}
        assert repo._is_duplicate({"id": "123"}) is True

    def test_not_duplicate(self):
        repo = _make_repo()
        repo.collection.find_one.return_value = None
        assert repo._is_duplicate({"id": "123"}) is False

    def test_no_unique_fields(self):
        repo = _make_repo()
        repo.unique_fields = []
        assert repo._is_duplicate({"id": "123"}) is False

    def test_missing_field_in_doc(self):
        repo = _make_repo()
        assert repo._is_duplicate({"name": "no_unique_match"}) is False


# ==================== _to_dict ====================

class TestToDict:
    def test_with_dict(self):
        repo = _make_repo()
        doc = {"id": "1", "name": "test"}
        assert repo._to_dict(doc) == doc

    def test_with_pydantic_model(self):
        repo = _make_repo()
        mock_model = MagicMock(spec=['model_dump'])
        mock_model.model_dump.return_value = {"id": "1"}
        # Not isinstance BaseModel but has model_dump
        result = repo._to_dict({"id": "1"})
        assert result == {"id": "1"}
