"""Tests for the RAG search tool (search_knowledge_base)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from src.ai import rag_tool


@pytest.fixture
def mock_embed_and_search(monkeypatch):
    embed = MagicMock(return_value=[0.1] * 1536)
    search = MagicMock(return_value=[
        {
            "source_id": "repo:abc",
            "source_type": "repository",
            "repo_full_name": "Qiskit/qiskit",
            "repo_name": "qiskit",
            "primary_language": "Python",
            "stargazer_count": 7000,
            "section_path": "Installation",
            "text": "Qiskit is an open-source SDK for quantum computing.",
            "score": 0.92,
        }
    ])
    monkeypatch.setattr(rag_tool, "embed_one", embed)
    monkeypatch.setattr(rag_tool, "vector_search", search)
    return embed, search


def test_empty_query_returns_error(mock_embed_and_search):
    result = json.loads(rag_tool.search_knowledge_base(""))
    assert "error" in result
    embed, _ = mock_embed_and_search
    embed.assert_not_called()


def test_basic_search_returns_curated_payload(mock_embed_and_search):
    payload = json.loads(rag_tool.search_knowledge_base("quantum"))
    assert payload["query"] == "quantum"
    assert payload["count"] == 1
    hit = payload["results"][0]
    assert hit["repo"] == "Qiskit/qiskit"
    assert hit["language"] == "Python"
    assert hit["stars"] == 7000
    assert hit["score"] == 0.92
    assert "Qiskit is" in hit["snippet"]


def test_top_k_is_capped(mock_embed_and_search):
    _, search = mock_embed_and_search
    rag_tool.search_knowledge_base("x", top_k=999)
    # k clamped to 20 max
    assert search.call_args.kwargs["k"] == 20


def test_top_k_min_is_one(mock_embed_and_search):
    _, search = mock_embed_and_search
    rag_tool.search_knowledge_base("x", top_k=0)
    assert search.call_args.kwargs["k"] == 1


def test_pre_filter_includes_language(mock_embed_and_search):
    _, search = mock_embed_and_search
    rag_tool.search_knowledge_base("x", primary_language="Python")
    assert search.call_args.kwargs["pre_filter"]["primary_language"] == "Python"


def test_pre_filter_includes_min_stars(mock_embed_and_search):
    _, search = mock_embed_and_search
    rag_tool.search_knowledge_base("x", min_stars=500)
    assert search.call_args.kwargs["pre_filter"]["stargazer_count"] == {"$gte": 500}


def test_snippet_truncated(mock_embed_and_search):
    _, search = mock_embed_and_search
    search.return_value = [{
        "source_id": "x", "source_type": "repository",
        "repo_full_name": "x", "primary_language": "X",
        "stargazer_count": 0, "section_path": "",
        "text": "a" * 2000, "score": 0.5,
    }]
    payload = json.loads(rag_tool.search_knowledge_base("x"))
    assert len(payload["results"][0]["snippet"]) == 800


def test_embed_failure_returns_error(monkeypatch):
    monkeypatch.setattr(rag_tool, "embed_one", MagicMock(side_effect=RuntimeError("boom")))
    result = json.loads(rag_tool.search_knowledge_base("x"))
    assert "error" in result
    assert "boom" in result["error"]
