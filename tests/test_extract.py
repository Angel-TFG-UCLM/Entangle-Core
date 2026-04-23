"""
Tests for src.github.extract
================================
Unit tests for extract_organization, extract_repository, extract_user,
and search_repositories. All external calls are mocked.
"""
import pytest
from unittest.mock import patch, MagicMock
from src.github.extract import (
    extract_organization,
    extract_repository,
    extract_user,
    search_repositories,
)


@pytest.fixture
def mock_deps():
    """Patch github_client and db used by extract functions."""
    with patch("src.github.extract.github_client") as mock_client, \
         patch("src.github.extract.db") as mock_db:
        mock_collection = MagicMock()
        mock_db.get_collection.return_value = mock_collection
        yield mock_client, mock_db, mock_collection


class TestExtractOrganization:
    def test_returns_org_data(self, mock_deps):
        mock_client, _, mock_col = mock_deps
        mock_client.execute_query.return_value = {
            "data": {"organization": {"id": "org1", "login": "qiskit"}}
        }
        result = extract_organization("qiskit")
        assert result["login"] == "qiskit"
        mock_col.update_one.assert_called_once()

    def test_org_not_found(self, mock_deps):
        mock_client, _, _ = mock_deps
        mock_client.execute_query.return_value = {"data": {"organization": None}}
        result = extract_organization("nonexistent")
        assert result == {}

    def test_skip_save(self, mock_deps):
        mock_client, _, mock_col = mock_deps
        mock_client.execute_query.return_value = {
            "data": {"organization": {"id": "org1", "login": "test"}}
        }
        extract_organization("test", save_to_db=False)
        mock_col.update_one.assert_not_called()


class TestExtractRepository:
    def test_returns_repo_data(self, mock_deps):
        mock_client, _, mock_col = mock_deps
        mock_client.execute_query.return_value = {
            "data": {"repository": {"id": "repo1", "full_name": "owner/repo"}}
        }
        result = extract_repository("owner", "repo")
        assert result["id"] == "repo1"
        mock_col.update_one.assert_called_once()

    def test_repo_not_found(self, mock_deps):
        mock_client, _, _ = mock_deps
        mock_client.execute_query.return_value = {"data": {"repository": None}}
        assert extract_repository("owner", "missing") == {}

    def test_skip_save(self, mock_deps):
        mock_client, _, mock_col = mock_deps
        mock_client.execute_query.return_value = {
            "data": {"repository": {"id": "r1"}}
        }
        extract_repository("o", "r", save_to_db=False)
        mock_col.update_one.assert_not_called()


class TestExtractUser:
    def test_returns_user_data(self, mock_deps):
        mock_client, _, mock_col = mock_deps
        mock_client.execute_query.return_value = {
            "data": {"user": {"id": "u1", "login": "alice"}}
        }
        result = extract_user("alice")
        assert result["login"] == "alice"
        mock_col.update_one.assert_called_once()

    def test_user_not_found(self, mock_deps):
        mock_client, _, _ = mock_deps
        mock_client.execute_query.return_value = {"data": {"user": None}}
        assert extract_user("ghost") == {}

    def test_skip_save(self, mock_deps):
        mock_client, _, mock_col = mock_deps
        mock_client.execute_query.return_value = {
            "data": {"user": {"id": "u1", "login": "bob"}}
        }
        extract_user("bob", save_to_db=False)
        mock_col.update_one.assert_not_called()


class TestSearchRepositories:
    def test_returns_list(self, mock_deps):
        mock_client, _, _ = mock_deps
        mock_client.execute_query.return_value = {
            "data": {
                "search": {
                    "edges": [
                        {"node": {"id": "r1", "name": "qiskit"}},
                        {"node": {"id": "r2", "name": "cirq"}},
                    ]
                }
            }
        }
        result = search_repositories("quantum", first=2)
        assert len(result) == 2
        assert result[0]["name"] == "qiskit"

    def test_empty_results(self, mock_deps):
        mock_client, _, _ = mock_deps
        mock_client.execute_query.return_value = {"data": {"search": {"edges": []}}}
        assert search_repositories("nonexistent") == []

    def test_save_to_db(self, mock_deps):
        mock_client, _, mock_col = mock_deps
        mock_client.execute_query.return_value = {
            "data": {"search": {"edges": [{"node": {"id": "r1"}}]}}
        }
        search_repositories("quantum", save_to_db=True)
        mock_col.update_one.assert_called_once()

    def test_no_save_by_default(self, mock_deps):
        mock_client, _, mock_col = mock_deps
        mock_client.execute_query.return_value = {
            "data": {"search": {"edges": [{"node": {"id": "r1"}}]}}
        }
        search_repositories("quantum")
        mock_col.update_one.assert_not_called()
