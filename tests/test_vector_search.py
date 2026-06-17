"""Tests for the Cosmos vCore vector search helpers."""
from unittest.mock import MagicMock

import pytest
from pymongo.errors import OperationFailure

from src.core import vector_search


@pytest.fixture
def mock_db(monkeypatch):
    """Mock get_database so the helpers never hit Cosmos."""
    fake_coll = MagicMock()
    fake_db = MagicMock()
    fake_db.__getitem__.return_value = fake_coll
    monkeypatch.setattr(vector_search, "get_database", lambda: fake_db)
    return fake_db, fake_coll


def test_ensure_vector_index_creates_when_missing(mock_db):
    fake_db, fake_coll = mock_db
    fake_coll.list_indexes.return_value = [{"name": "_id_"}]
    assert vector_search.ensure_vector_index() is True
    # createIndexes command issued for the vector index
    assert fake_db.command.called
    cmd = fake_db.command.call_args[0][0]
    assert cmd["createIndexes"] == vector_search.CHUNKS_COLLECTION
    # auxiliary filter indexes created
    assert fake_coll.create_index.call_count == 4


def test_ensure_vector_index_idempotent_when_present(mock_db):
    fake_db, fake_coll = mock_db
    existing = [{"name": vector_search.VECTOR_INDEX_NAME}, {"name": "source_type_1"},
                {"name": "primary_language_1"}, {"name": "stargazer_count_1"},
                {"name": "source_id_1"}]
    fake_coll.list_indexes.return_value = existing
    assert vector_search.ensure_vector_index() is True
    fake_db.command.assert_not_called()
    fake_coll.create_index.assert_not_called()


def test_ensure_vector_index_raises_on_list_failure(mock_db):
    _, fake_coll = mock_db
    fake_coll.list_indexes.side_effect = OperationFailure("boom")
    with pytest.raises(OperationFailure):
        vector_search.ensure_vector_index()


def test_ensure_vector_index_tolerates_aux_index_failure(mock_db):
    fake_db, fake_coll = mock_db
    fake_coll.list_indexes.return_value = [{"name": vector_search.VECTOR_INDEX_NAME}]
    fake_coll.create_index.side_effect = OperationFailure("dup")
    # Should not raise even if aux index creation fails
    assert vector_search.ensure_vector_index() is True


def test_vector_search_validates_dimension(mock_db):
    with pytest.raises(ValueError, match="dim"):
        vector_search.vector_search([0.1, 0.2], k=5)


def test_vector_search_returns_hits(mock_db):
    _, fake_coll = mock_db
    hits = [{"source_id": "repo:1", "score": 0.9}]
    fake_coll.aggregate.return_value = iter(hits)
    out = vector_search.vector_search([0.0] * vector_search.EMBEDDING_DIM, k=5)
    assert out == hits


def test_vector_search_caps_k(mock_db):
    _, fake_coll = mock_db
    fake_coll.aggregate.return_value = iter([])
    vector_search.vector_search([0.0] * vector_search.EMBEDDING_DIM, k=999)
    pipeline = fake_coll.aggregate.call_args[0][0]
    assert pipeline[0]["$search"]["cosmosSearch"]["k"] == 50


def test_vector_search_applies_pre_filter(mock_db):
    _, fake_coll = mock_db
    fake_coll.aggregate.return_value = iter([])
    vector_search.vector_search(
        [0.0] * vector_search.EMBEDDING_DIM, k=3, pre_filter={"primary_language": "Python"}
    )
    cosmos = fake_coll.aggregate.call_args[0][0][0]["$search"]["cosmosSearch"]
    assert cosmos["filter"] == {"primary_language": "Python"}


def test_vector_search_raises_on_aggregate_failure(mock_db):
    _, fake_coll = mock_db
    fake_coll.aggregate.side_effect = OperationFailure("index missing")
    with pytest.raises(OperationFailure):
        vector_search.vector_search([0.0] * vector_search.EMBEDDING_DIM, k=5)
