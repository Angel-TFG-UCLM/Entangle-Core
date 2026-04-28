"""
Tests for src.core.config
===========================
Tests for Config and IngestionConfig classes.
"""
import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import patch
from src.core.config import Config, IngestionConfig


class TestConfig:

    def test_defaults(self):
        assert Config.GITHUB_API_URL == "https://api.github.com/graphql"
        assert Config.MONGO_DB_NAME is not None
        assert Config.API_HOST == "0.0.0.0"
        assert isinstance(Config.API_PORT, int)
        assert Config.LOG_LEVEL in ("INFO", "DEBUG", "WARNING", "ERROR")

    def test_environment_default(self):
        assert Config.ENVIRONMENT in ("development", "production", "staging")

    def test_debug_flag(self):
        assert isinstance(Config.DEBUG, bool)


class TestIngestionConfig:

    def _create_config_file(self, data, tmpdir):
        filepath = tmpdir / "test_config.json"
        with open(filepath, 'w') as f:
            json.dump(data, f)
        return str(filepath)

    def test_loads_valid_config(self, tmp_path):
        data = {
            "keywords": ["quantum", "qiskit"],
            "languages": ["Python", "C++"],
            "min_stars": 10,
            "max_inactivity_days": 365,
            "exclude_forks": True,
        }
        path = self._create_config_file(data, tmp_path)
        config = IngestionConfig(config_path=path)
        assert config.keywords == ["quantum", "qiskit"]
        assert config.languages == ["Python", "C++"]
        assert config.min_stars == 10
        assert config.max_inactivity_days == 365
        assert config.exclude_forks is True

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            IngestionConfig(config_path=str(tmp_path / "nonexistent.json"))

    def test_invalid_json(self, tmp_path):
        filepath = tmp_path / "bad.json"
        filepath.write_text("not valid json {{{")
        with pytest.raises(ValueError):
            IngestionConfig(config_path=str(filepath))

    def test_missing_required_field(self, tmp_path):
        data = {"keywords": ["quantum"]}  # Missing languages, min_stars, etc.
        path = self._create_config_file(data, tmp_path)
        with pytest.raises(ValueError):
            IngestionConfig(config_path=path)

    def test_wrong_type(self, tmp_path):
        data = {
            "keywords": "should-be-list",
            "languages": ["Python"],
            "min_stars": 10,
            "max_inactivity_days": 365,
            "exclude_forks": True,
        }
        path = self._create_config_file(data, tmp_path)
        with pytest.raises(TypeError):
            IngestionConfig(config_path=path)

    def test_negative_min_stars(self, tmp_path):
        data = {
            "keywords": ["quantum"],
            "languages": ["Python"],
            "min_stars": -5,
            "max_inactivity_days": 365,
            "exclude_forks": True,
        }
        path = self._create_config_file(data, tmp_path)
        with pytest.raises(ValueError):
            IngestionConfig(config_path=path)

    def test_negative_inactivity_days(self, tmp_path):
        data = {
            "keywords": ["quantum"],
            "languages": ["Python"],
            "min_stars": 10,
            "max_inactivity_days": -1,
            "exclude_forks": True,
        }
        path = self._create_config_file(data, tmp_path)
        with pytest.raises(ValueError):
            IngestionConfig(config_path=path)

    def test_properties(self, tmp_path):
        data = {
            "keywords": ["quantum", "qiskit"],
            "search_keywords": ["quantum computing"],
            "languages": ["Python"],
            "min_stars": 5,
            "max_inactivity_days": 180,
            "exclude_forks": False,
            "min_contributors": 3,
            "additional_filters": {"custom": True},
        }
        path = self._create_config_file(data, tmp_path)
        config = IngestionConfig(config_path=path)
        assert config.search_keywords == ["quantum computing"]
        assert config.min_contributors == 3
        assert config.additional_filters == {"custom": True}

    def test_search_keywords_fallback(self, tmp_path):
        data = {
            "keywords": ["quantum", "qiskit"],
            "languages": ["Python"],
            "min_stars": 5,
            "max_inactivity_days": 365,
            "exclude_forks": True,
        }
        path = self._create_config_file(data, tmp_path)
        config = IngestionConfig(config_path=path)
        assert config.search_keywords == ["quantum"]
