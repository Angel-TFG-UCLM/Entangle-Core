"""Unit tests for the pure helper functions of the config-driven agent.

These cover the deterministic, side-effect-free helpers (payload
normalization for reasoning models, action extraction, tool-result
truncation, URL building) without exercising the streaming/HTTP machinery.
"""
import json

import pytest

from src.ai import agent


# ─────────────────── _is_reasoning_model / _build_api_url ───────────────────
def test_is_reasoning_model_true_for_gpt5(monkeypatch):
    monkeypatch.setattr(agent.config, "AZURE_AI_DEPLOYMENT", "gpt-5-mini")
    assert agent._is_reasoning_model() is True


def test_is_reasoning_model_false_for_gpt4o(monkeypatch):
    monkeypatch.setattr(agent.config, "AZURE_AI_DEPLOYMENT", "gpt-4o")
    assert agent._is_reasoning_model() is False


def test_build_api_url_contains_deployment(monkeypatch):
    monkeypatch.setattr(agent.config, "AZURE_AI_ENDPOINT", "https://x.openai.azure.com")
    monkeypatch.setattr(agent.config, "AZURE_AI_DEPLOYMENT", "gpt-5-mini")
    url = agent._build_api_url()
    assert "gpt-5-mini" in url
    assert "api-version=2024-12-01-preview" in url


# ─────────────────── _is_default_temperature ───────────────────
@pytest.mark.parametrize("value,expected", [
    (1.0, True),
    (1, True),
    (0.5, False),
    (0, False),
    (None, False),
    ("not-a-number", False),
])
def test_is_default_temperature(value, expected):
    assert agent._is_default_temperature(value) is expected


# ─────────────────── _normalize_payload ───────────────────
def test_normalize_payload_passthrough_for_non_reasoning(monkeypatch):
    monkeypatch.setattr(agent.config, "AZURE_AI_DEPLOYMENT", "gpt-4o")
    payload = {"max_tokens": 10, "temperature": 0.5}
    assert agent._normalize_payload(payload) == payload


def test_normalize_payload_renames_max_tokens(monkeypatch):
    monkeypatch.setattr(agent.config, "AZURE_AI_DEPLOYMENT", "gpt-5-mini")
    out = agent._normalize_payload({"max_tokens": 10})
    assert "max_tokens" not in out
    assert out["max_completion_tokens"] == max(10 * 4, 200)


def test_normalize_payload_drops_non_default_temperature(monkeypatch):
    monkeypatch.setattr(agent.config, "AZURE_AI_DEPLOYMENT", "gpt-5-mini")
    out = agent._normalize_payload({"temperature": 0.2})
    assert "temperature" not in out
    assert out["reasoning_effort"] == "minimal"


def test_normalize_payload_keeps_default_temperature(monkeypatch):
    monkeypatch.setattr(agent.config, "AZURE_AI_DEPLOYMENT", "gpt-5-mini")
    out = agent._normalize_payload({"temperature": 1.0})
    assert out["temperature"] == 1.0


def test_normalize_payload_respects_existing_reasoning_effort(monkeypatch):
    monkeypatch.setattr(agent.config, "AZURE_AI_DEPLOYMENT", "gpt-5-mini")
    out = agent._normalize_payload({"reasoning_effort": "high"})
    assert out["reasoning_effort"] == "high"


# ─────────────────── _extract_actions ───────────────────
def test_extract_actions_none():
    cleaned, actions = agent._extract_actions("Just a normal reply.")
    assert actions == []
    assert cleaned == "Just a normal reply."


def test_extract_actions_open_universe_no_data():
    cleaned, actions = agent._extract_actions("Abriendo. [ACTION:OPEN_UNIVERSE]")
    assert actions == [{"action": "OPEN_UNIVERSE", "data": {}}]
    assert "[ACTION" not in cleaned


def test_extract_actions_with_json_data():
    reply = 'Hecho [ACTION:CREATE_VIEW:{"orgs":["qiskit","IBM"]}]'
    cleaned, actions = agent._extract_actions(reply)
    assert actions[0]["action"] == "CREATE_VIEW"
    assert actions[0]["data"] == {"orgs": ["qiskit", "IBM"]}


def test_extract_actions_unwraps_code_fence():
    reply = "Texto\n```\n[ACTION:OPEN_UNIVERSE]\n```"
    cleaned, actions = agent._extract_actions(reply)
    assert actions == [{"action": "OPEN_UNIVERSE", "data": {}}]
    assert "```" not in cleaned


def test_extract_actions_invalid_json_yields_empty_data():
    reply = "[ACTION:CREATE_VIEW:{not valid json}]"
    cleaned, actions = agent._extract_actions(reply)
    assert actions[0]["action"] == "CREATE_VIEW"
    assert actions[0]["data"] == {}


# ─────────────────── _truncate_tool_result ───────────────────
def test_truncate_short_passthrough():
    assert agent._truncate_tool_result("small") == "small"


def test_truncate_reduces_results_list():
    big = {"count": 100, "results": [{"i": i, "pad": "x" * 200} for i in range(100)]}
    out = agent._truncate_tool_result(json.dumps(big))
    data = json.loads(out)
    assert data["_truncated"] is True
    assert len(data["results"]) <= 5


def test_truncate_non_json_falls_back_to_error():
    out = agent._truncate_tool_result("y" * (agent._MAX_TOOL_RESULT_CHARS + 1))
    data = json.loads(out)
    assert data["_truncated"] is True
    assert "error" in data


# ─────────────────── config / tools ───────────────────
def test_agent_config_has_six_workers():
    cfg = agent._agent_config()
    assert len(cfg.workers) == 6


def test_build_agent_tools_returns_schemas():
    tools = agent._build_agent_tools()
    assert isinstance(tools, list)
    # cada schema es un dict con "type": "function"
    assert all(t.get("type") == "function" for t in tools)
