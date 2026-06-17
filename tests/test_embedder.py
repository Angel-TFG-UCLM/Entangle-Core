"""Tests for the Azure AI Foundry embeddings client."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.ai import embedder


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Los backoffs de reintento no deben dormir de verdad en los tests."""
    monkeypatch.setattr(embedder.time, "sleep", lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def _fake_endpoint(monkeypatch):
    monkeypatch.setattr(embedder.config, "AZURE_AI_ENDPOINT", "https://fake.openai.azure.com")
    monkeypatch.setattr(embedder.config, "AZURE_AI_API_KEY", "fake-key")


def _embedding_response(vectors):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)],
        "usage": {"total_tokens": 10},
    }
    return resp


def test_embed_texts_empty_returns_empty():
    assert embedder.embed_texts([]) == []


def test_embed_texts_requires_endpoint(monkeypatch):
    monkeypatch.setattr(embedder.config, "AZURE_AI_ENDPOINT", "")
    with pytest.raises(RuntimeError, match="AZURE_AI_ENDPOINT"):
        embedder.embed_texts(["hello"])


def test_embed_texts_returns_vectors_in_order():
    resp = _embedding_response([[0.1, 0.2], [0.3, 0.4]])
    with patch("src.ai.embedder.requests.post", return_value=resp):
        out = embedder.embed_texts(["a", "b"])
    assert out == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_texts_sorts_by_index():
    resp = MagicMock(status_code=200)
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": [
            {"index": 1, "embedding": [9.0]},
            {"index": 0, "embedding": [1.0]},
        ],
        "usage": {"total_tokens": 4},
    }
    with patch("src.ai.embedder.requests.post", return_value=resp):
        out = embedder.embed_texts(["x", "y"])
    assert out == [[1.0], [9.0]]


def test_embed_texts_batches_multiple_requests():
    calls = {"n": 0}

    def fake_post(url, headers, json, timeout):
        calls["n"] += 1
        return _embedding_response([[float(calls["n"])]])

    with patch("src.ai.embedder.requests.post", side_effect=fake_post):
        out = embedder.embed_texts(["a", "b", "c"], batch_size=1)
    assert calls["n"] == 3
    assert len(out) == 3


def test_embed_one_returns_single_vector():
    resp = _embedding_response([[0.5, 0.6]])
    with patch("src.ai.embedder.requests.post", return_value=resp):
        vec = embedder.embed_one("hello")
    assert vec == [0.5, 0.6]


def test_call_with_retry_retries_on_429_then_succeeds():
    err = MagicMock(status_code=429, headers={})
    ok = _embedding_response([[1.0]])
    with patch("src.ai.embedder.requests.post", side_effect=[err, ok]):
        out = embedder.embed_texts(["a"])
    assert out == [[1.0]]


def test_call_with_retry_raises_after_exhausting():
    with patch(
        "src.ai.embedder.requests.post",
        side_effect=requests.ConnectionError("dns"),
    ):
        with pytest.raises(requests.RequestException):
            embedder.embed_texts(["a"])


def test_auth_headers_prefers_api_key():
    headers = embedder._auth_headers()
    assert headers["api-key"] == "fake-key"
    assert "Authorization" not in headers


def test_auth_headers_falls_back_to_entra(monkeypatch):
    monkeypatch.setattr(embedder.config, "AZURE_AI_API_KEY", "")
    fake_token = MagicMock(token="tok123")
    fake_cred = MagicMock()
    fake_cred.get_token.return_value = fake_token
    monkeypatch.setattr(embedder, "_get_credential", lambda: fake_cred)
    headers = embedder._auth_headers()
    assert headers["Authorization"] == "Bearer tok123"
