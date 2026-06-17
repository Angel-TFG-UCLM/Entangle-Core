"""Tests for the external research tools (Tavily web + arXiv)."""
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.ai import research_tools


# ─────────────────── web_search (Tavily) ───────────────────
def test_web_search_no_key(monkeypatch):
    monkeypatch.setattr(research_tools, "_TAVILY_API_KEY", "")
    result = json.loads(research_tools.web_search("quantum news"))
    assert "error" in result
    assert "TAVILY_API_KEY" in result["error"]


def test_web_search_success(monkeypatch):
    monkeypatch.setattr(research_tools, "_TAVILY_API_KEY", "fake-key")
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "results": [
            {"title": "Quantum news", "url": "https://x.com/1", "content": "Long article text " * 50, "score": 0.9},
            {"title": "Another", "url": "https://x.com/2", "content": "Short", "score": 0.7},
        ]
    }
    fake_response.raise_for_status = MagicMock()
    with patch("src.ai.research_tools.requests.post", return_value=fake_response):
        result = json.loads(research_tools.web_search("quantum", max_results=5))

    assert result["count"] == 2
    assert result["results"][0]["title"] == "Quantum news"
    assert len(result["results"][0]["snippet"]) <= 600


def test_web_search_max_results_capped(monkeypatch):
    monkeypatch.setattr(research_tools, "_TAVILY_API_KEY", "fake-key")
    captured: dict = {}
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"results": []}
    fake_response.raise_for_status = MagicMock()

    def capture_post(url, json, timeout):
        captured["payload"] = json
        return fake_response

    with patch("src.ai.research_tools.requests.post", side_effect=capture_post):
        research_tools.web_search("q", max_results=999)
    assert captured["payload"]["max_results"] == 10


def test_web_search_include_domains(monkeypatch):
    monkeypatch.setattr(research_tools, "_TAVILY_API_KEY", "fake-key")
    captured: dict = {}
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"results": []}
    fake_response.raise_for_status = MagicMock()

    def capture_post(url, json, timeout):
        captured["payload"] = json
        return fake_response

    with patch("src.ai.research_tools.requests.post", side_effect=capture_post):
        research_tools.web_search("q", include_domains=["github.com", "ibm.com"])
    assert captured["payload"]["include_domains"] == ["github.com", "ibm.com"]


def test_web_search_request_failure(monkeypatch):
    monkeypatch.setattr(research_tools, "_TAVILY_API_KEY", "fake-key")
    with patch("src.ai.research_tools.requests.post", side_effect=requests.RequestException("network down")):
        result = json.loads(research_tools.web_search("q"))
    assert "error" in result


# ─────────────────── search_arxiv ───────────────────
ARXIV_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>Variational Quantum Eigensolvers
      with Noise</title>
    <summary>We study the impact of noise on VQE algorithms.
      Our results show...</summary>
    <published>2024-01-15T12:00:00Z</published>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.00001v1</id>
    <title>Another quantum paper</title>
    <summary>Lorem ipsum dolor sit amet.</summary>
    <published>2024-02-01T10:00:00Z</published>
    <author><name>Charlie Brown</name></author>
  </entry>
</feed>"""


def test_search_arxiv_parses_feed():
    fake_response = MagicMock(status_code=200, content=ARXIV_SAMPLE.encode("utf-8"))
    fake_response.raise_for_status = MagicMock()
    with patch("src.ai.research_tools.requests.get", return_value=fake_response):
        result = json.loads(research_tools.search_arxiv("VQE"))

    assert result["count"] == 2
    first = result["results"][0]
    assert "Variational" in first["title"]
    assert first["authors"] == ["Alice Smith", "Bob Jones"]
    assert first["url"] == "http://arxiv.org/abs/2401.12345v1"
    assert first["published"] == "2024-01-15"


def test_search_arxiv_with_category():
    captured: dict = {}
    fake_response = MagicMock(status_code=200, content=b"<feed xmlns='http://www.w3.org/2005/Atom'/>")
    fake_response.raise_for_status = MagicMock()

    def capture_get(url, params, timeout, headers=None):
        captured["params"] = params
        return fake_response

    with patch("src.ai.research_tools.requests.get", side_effect=capture_get):
        research_tools.search_arxiv("VQE", category="quant-ph")
    assert "cat:quant-ph" in captured["params"]["search_query"]


def test_search_arxiv_max_results_capped():
    captured: dict = {}
    fake_response = MagicMock(status_code=200, content=b"<feed xmlns='http://www.w3.org/2005/Atom'/>")
    fake_response.raise_for_status = MagicMock()

    def capture_get(url, params, timeout, headers=None):
        captured["params"] = params
        return fake_response

    with patch("src.ai.research_tools.requests.get", side_effect=capture_get):
        research_tools.search_arxiv("q", max_results=999)
    assert captured["params"]["max_results"] == 10


def test_search_arxiv_network_failure():
    with patch("src.ai.research_tools.requests.get", side_effect=requests.RequestException("dns")):
        result = json.loads(research_tools.search_arxiv("q"))
    assert "error" in result


def test_search_arxiv_invalid_xml():
    fake_response = MagicMock(status_code=200, content=b"<<<not xml>>>")
    fake_response.raise_for_status = MagicMock()
    with patch("src.ai.research_tools.requests.get", return_value=fake_response):
        result = json.loads(research_tools.search_arxiv("q"))
    assert "error" in result
