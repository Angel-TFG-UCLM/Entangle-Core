"""Tests for the YAML-driven worker configuration loader."""
from pathlib import Path

import pytest

from src.ai import workers


def test_load_default_config():
    cfg = workers.load_agent_config()
    # Defaults defined in config/workers.yaml
    assert "data" in cfg.workers
    assert "dashboard" in cfg.workers
    assert "universe" in cfg.workers
    assert "knowledge" in cfg.workers
    assert "deep_research" in cfg.workers
    assert cfg.router.fallback == "data"


def test_worker_data_has_tools():
    cfg = workers.load_agent_config()
    data = cfg.get_worker("data")
    assert data.has_tools is True
    assert "query_database" in data.tools
    assert "run_aggregation" in data.tools
    assert data.tool_choice_first_round == "required"


def test_worker_dashboard_no_tools():
    cfg = workers.load_agent_config()
    dash = cfg.get_worker("dashboard")
    assert dash.has_tools is False
    assert dash.tools == []


def test_unknown_intent_falls_back():
    cfg = workers.load_agent_config()
    fallback = cfg.get_worker("nonexistent-intent")
    assert fallback.intent == cfg.router.fallback


def test_invalid_yaml_missing_prompt(tmp_path):
    bad_yaml = tmp_path / "workers.yaml"
    bad_yaml.write_text(
        """
router:
  prompt_constant: DOES_NOT_EXIST
  intents: [data]
  fallback: data
workers:
  data:
    prompt_constant: DATA_ANALYST_PROMPT
""",
        encoding="utf-8",
    )
    workers._load_cached.cache_clear()
    with pytest.raises(ValueError, match="DOES_NOT_EXIST"):
        workers.load_agent_config(bad_yaml)
    workers._load_cached.cache_clear()


def test_invalid_yaml_fallback_outside_intents(tmp_path):
    bad_yaml = tmp_path / "workers.yaml"
    bad_yaml.write_text(
        """
router:
  prompt_constant: ROUTER_PROMPT
  intents: [data, dashboard]
  fallback: universe
workers:
  data:
    prompt_constant: DATA_ANALYST_PROMPT
  dashboard:
    prompt_constant: UI_DASHBOARD_PROMPT
""",
        encoding="utf-8",
    )
    workers._load_cached.cache_clear()
    with pytest.raises(ValueError, match="fallback"):
        workers.load_agent_config(bad_yaml)
    workers._load_cached.cache_clear()


def test_router_config_defaults():
    cfg = workers.load_agent_config()
    assert cfg.router.reasoning_effort == "minimal"
    assert cfg.router.max_completion_tokens == 10


def test_worker_config_dataclass_immutable():
    cfg = workers.load_agent_config()
    data = cfg.get_worker("data")
    with pytest.raises(Exception):
        data.temperature = 1.0  # frozen=True
