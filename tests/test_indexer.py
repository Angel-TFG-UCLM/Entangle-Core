"""Tests for the indexer pipeline (idempotency + skip logic)."""
from unittest.mock import MagicMock, patch

import pytest

from src.ai import indexer


@pytest.fixture
def mock_db(monkeypatch):
    """Mock all collection accesses so the indexer never hits Mongo."""
    fake_repos = MagicMock()
    fake_chunks = MagicMock()
    collections = {"repositories": fake_repos, indexer.CHUNKS_COLLECTION: fake_chunks}
    monkeypatch.setattr(indexer, "get_collection", lambda name: collections[name])
    return collections


def test_source_id_uses_repo_id():
    sid = indexer._stable_source_id({"id": "ABC123", "full_name": "foo/bar"})
    assert sid == "repo:ABC123"


def test_source_id_falls_back_to_full_name():
    sid = indexer._stable_source_id({"full_name": "foo/bar"})
    assert sid == "repo:foo/bar"


def test_source_id_unknown():
    assert indexer._stable_source_id({}) == "repo:unknown"


def test_build_source_text_concatenates_fields():
    repo = {
        "description": "Quantum lib for X",
        "readme_text": "## Install\npip install foo",
        "stargazer_count": 10,  # NOT a string field, should be ignored
    }
    text = indexer._build_source_text(repo)
    assert "Quantum lib for X" in text
    assert "Install" in text
    assert "10" not in text


def test_build_source_text_empty_when_no_text():
    assert indexer._build_source_text({"stargazer_count": 5}) == ""
    assert indexer._build_source_text({"description": "", "readme_text": None}) == ""


def test_index_skips_when_hash_matches(monkeypatch, mock_db):
    """If a repo's content hash equals the stored one, no embedding occurs."""
    repo = {
        "id": "1",
        "description": "stable content",
        "readme_text": "more stable content",
        "_indexing": {
            "content_hash": indexer.text_hash("stable content\n\nmore stable content"),
        },
    }
    mock_db["repositories"].find.return_value.__iter__.return_value = iter([repo])
    embed_mock = MagicMock()
    monkeypatch.setattr(indexer, "embed_texts", embed_mock)
    monkeypatch.setattr(indexer, "ensure_vector_index", MagicMock())

    stats = indexer.index_repositories()

    embed_mock.assert_not_called()
    assert stats["skipped_unchanged"] == 1
    assert stats["indexed"] == 0


def test_index_skips_when_no_text(monkeypatch, mock_db):
    """Repos with no text fields are skipped."""
    repo = {"id": "2", "description": None, "readme_text": None}
    mock_db["repositories"].find.return_value.__iter__.return_value = iter([repo])
    monkeypatch.setattr(indexer, "embed_texts", MagicMock())
    monkeypatch.setattr(indexer, "ensure_vector_index", MagicMock())

    stats = indexer.index_repositories()
    assert stats["skipped_no_text"] == 1
    assert stats["indexed"] == 0


def test_index_force_reindexes(monkeypatch, mock_db):
    """``force=True`` ignores the matching hash and embeds again."""
    repo = {
        "id": "3",
        "description": "force me",
        "readme_text": "force more",
        "_indexing": {"content_hash": indexer.text_hash("force me\n\nforce more")},
        "full_name": "foo/bar",
    }
    mock_db["repositories"].find.return_value.__iter__.return_value = iter([repo])
    mock_db["repositories"].update_one = MagicMock()

    # Embeddings devuelve 1 vector por chunk (de prueba uno solo)
    monkeypatch.setattr(indexer, "embed_texts", lambda texts, batch_size: [[0.1] * 1536 for _ in texts])
    monkeypatch.setattr(indexer, "ensure_vector_index", MagicMock())
    mock_db[indexer.CHUNKS_COLLECTION].insert_many = MagicMock()

    stats = indexer.index_repositories(force=True)
    assert stats["indexed"] == 1
    assert stats["chunks_total"] >= 1
    mock_db[indexer.CHUNKS_COLLECTION].insert_many.assert_called_once()


def test_dry_run_skips_persistence(monkeypatch, mock_db):
    repo = {"id": "4", "description": "ABC content for dry run"}
    mock_db["repositories"].find.return_value.__iter__.return_value = iter([repo])
    monkeypatch.setattr(indexer, "embed_texts", lambda texts, batch_size: [[0.0] * 1536 for _ in texts])
    monkeypatch.setattr(indexer, "ensure_vector_index", MagicMock())

    stats = indexer.index_repositories(dry_run=True)
    assert stats["indexed"] == 1
    mock_db[indexer.CHUNKS_COLLECTION].insert_many.assert_not_called()
