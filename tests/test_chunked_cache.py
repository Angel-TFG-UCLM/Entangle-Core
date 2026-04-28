"""
Tests for src.core.chunked_cache
=================================
Tests for chunked MongoDB cache operations using mock collections.
"""
import pytest
import json
from unittest.mock import MagicMock, patch, call
from src.core.chunked_cache import (
    _estimate_items_per_chunk,
    _shallow_copy,
    _get_nested,
    _set_nested,
    _remove_nested,
    save_chunked,
    load_chunked,
    delete_chunked,
    get_cache_age_seconds,
    TARGET_CHUNK_BYTES,
)
from datetime import datetime, timezone, timedelta


# ── Tests for internal helpers ──

class TestEstimateItemsPerChunk:

    def test_empty_array(self):
        result = _estimate_items_per_chunk([])
        assert result >= 0

    def test_small_items(self):
        items = [{"id": i, "name": f"item_{i}"} for i in range(100)]
        result = _estimate_items_per_chunk(items)
        assert result > 10

    def test_large_items(self):
        items = [{"id": i, "data": "x" * 100000} for i in range(10)]
        result = _estimate_items_per_chunk(items)
        assert result >= 1

    def test_minimum_one(self):
        items = [{"data": "x" * 5000000}]
        result = _estimate_items_per_chunk(items)
        assert result >= 1


class TestShallowCopy:

    def test_basic_copy(self):
        data = {"a": 1, "b": [1, 2], "c": {"x": 10}}
        copy = _shallow_copy(data)
        assert copy == data
        assert copy is not data

    def test_nested_dict_is_new_ref(self):
        data = {"nested": {"key": "value"}}
        copy = _shallow_copy(data)
        assert copy["nested"] is not data["nested"]

    def test_list_is_same_ref(self):
        data = {"items": [1, 2, 3]}
        copy = _shallow_copy(data)
        assert copy["items"] is data["items"]


class TestGetNested:

    def test_single_level(self):
        assert _get_nested({"a": 42}, "a") == 42

    def test_two_levels(self):
        assert _get_nested({"a": {"b": 42}}, "a.b") == 42

    def test_missing_key(self):
        assert _get_nested({"a": 1}, "b") is None

    def test_deep_missing(self):
        assert _get_nested({"a": {"b": 1}}, "a.c") is None


class TestSetNested:

    def test_single_level(self):
        obj = {}
        _set_nested(obj, "a", 42)
        assert obj == {"a": 42}

    def test_two_levels(self):
        obj = {"a": {}}
        _set_nested(obj, "a.b", 42)
        assert obj == {"a": {"b": 42}}

    def test_creates_intermediate(self):
        obj = {}
        _set_nested(obj, "a.b.c", 42)
        assert obj == {"a": {"b": {"c": 42}}}


class TestRemoveNested:

    def test_single_level(self):
        obj = {"a": 1, "b": 2}
        _remove_nested(obj, "a")
        assert obj == {"b": 2}

    def test_two_levels(self):
        obj = {"a": {"b": 1, "c": 2}}
        _remove_nested(obj, "a.b")
        assert obj == {"a": {"c": 2}}

    def test_missing_key(self):
        obj = {"a": 1}
        _remove_nested(obj, "b")
        assert obj == {"a": 1}


# ── Tests with mock MongoDB collection ──

class TestSaveChunked:

    def test_saves_small_data(self):
        collection = MagicMock()
        collection.find_one.return_value = None
        collection.delete_many.return_value = MagicMock(deleted_count=0)

        data = {"info": "test", "items": [1, 2, 3]}
        save_chunked(collection, "test_cache", data, large_fields=["items"])

        collection.insert_many.assert_called_once()
        docs = collection.insert_many.call_args[0][0]
        # Should have meta doc + chunk docs
        assert any(d.get("_id") == "test_cache" for d in docs)

    def test_saves_with_empty_field(self):
        collection = MagicMock()
        collection.find_one.return_value = None
        collection.delete_many.return_value = MagicMock(deleted_count=0)

        data = {"info": "test", "items": []}
        save_chunked(collection, "test_cache", data, large_fields=["items"])

        collection.insert_many.assert_called_once()

    def test_saves_dict_field(self):
        collection = MagicMock()
        collection.find_one.return_value = None
        collection.delete_many.return_value = MagicMock(deleted_count=0)

        data = {"mapping": {"a": 1, "b": 2}}
        save_chunked(collection, "test_cache", data, large_fields=["mapping"])

        collection.insert_many.assert_called_once()

    def test_saves_nested_field(self):
        collection = MagicMock()
        collection.find_one.return_value = None
        collection.delete_many.return_value = MagicMock(deleted_count=0)

        data = {"graph": {"nodes": [{"id": 1}, {"id": 2}], "edges": []}}
        save_chunked(collection, "graph_cache", data, large_fields=["graph.nodes"])

        collection.insert_many.assert_called_once()


class TestLoadChunked:

    def test_returns_none_if_not_found(self):
        collection = MagicMock()
        collection.find_one.return_value = None
        assert load_chunked(collection, "nonexistent") is None

    def test_loads_legacy_doc(self):
        collection = MagicMock()
        collection.find_one.return_value = {
            "_id": "test",
            "cached_at": "2025-01-01",
            "data": [1, 2, 3],
        }
        result = load_chunked(collection, "test")
        assert result["data"] == [1, 2, 3]
        assert "_id" not in result

    def test_loads_chunked_doc(self):
        collection = MagicMock()
        collection.find_one.return_value = {
            "_id": "test",
            "_chunked": True,
            "_cached_at": "2025-01-01",
            "_chunk_map": {
                "items": {"count": 2, "kind": "list", "total": 4},
            },
        }
        collection.find.return_value = [
            {"_id": "test##items##0", "items": [1, 2]},
            {"_id": "test##items##1", "items": [3, 4]},
        ]
        result = load_chunked(collection, "test")
        assert result["items"] == [1, 2, 3, 4]

    def test_loads_chunked_dict(self):
        collection = MagicMock()
        collection.find_one.return_value = {
            "_id": "test",
            "_chunked": True,
            "_cached_at": "2025-01-01",
            "_chunk_map": {
                "mapping": {"count": 1, "kind": "dict", "total": 2},
            },
        }
        collection.find.return_value = [
            {"_id": "test##mapping##0", "items": [["a", 1], ["b", 2]]},
        ]
        result = load_chunked(collection, "test")
        assert result["mapping"] == {"a": 1, "b": 2}


class TestDeleteChunked:

    def test_deletes_simple(self):
        collection = MagicMock()
        collection.find_one.return_value = None
        collection.delete_many.return_value = MagicMock(deleted_count=1)
        result = delete_chunked(collection, "test")
        assert result == 1

    def test_deletes_with_chunks(self):
        collection = MagicMock()
        collection.find_one.return_value = {
            "_id": "test",
            "_chunked": True,
            "_chunk_map": {"items": {"count": 3, "kind": "list", "total": 100}},
        }
        collection.delete_many.return_value = MagicMock(deleted_count=4)
        result = delete_chunked(collection, "test")
        assert result == 4
        # Should have meta + 3 chunk IDs
        ids = collection.delete_many.call_args[0][0]["_id"]["$in"]
        assert len(ids) == 4


class TestGetCacheAgeSeconds:

    def test_returns_none_if_missing(self):
        collection = MagicMock()
        collection.find_one.return_value = None
        assert get_cache_age_seconds(collection, "x") is None

    def test_returns_none_if_no_cached_at(self):
        collection = MagicMock()
        collection.find_one.return_value = {"_id": "x"}
        assert get_cache_age_seconds(collection, "x") is None

    def test_returns_age(self):
        past = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        collection = MagicMock()
        collection.find_one.return_value = {"_id": "x", "_cached_at": past}
        age = get_cache_age_seconds(collection, "x")
        assert age is not None
        assert 110 < age < 130

    def test_invalid_date(self):
        collection = MagicMock()
        collection.find_one.return_value = {"_id": "x", "_cached_at": "not-a-date"}
        assert get_cache_age_seconds(collection, "x") is None
