from pathlib import Path
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.ai.providers import BedrockProvider, OpenAICompatibleProvider, get_ai_provider
from src.ai.research_tools import search_arxiv
from src.api.routes import get_dashboard_stats, health_check
from src.core.config import Config, config
from src.core.db import db
from src.core.snapshot import SnapshotError, load_bundle, write_bundle
from scripts.import_snapshot import recreate_indexes
from src.github.graphql_client import GitHubGraphQLClient


def test_snapshot_round_trip_and_checksum_verification(tmp_path):
    bundle = tmp_path / "snapshot"
    manifest = write_bundle(
        bundle,
        {"repositories": [{"_id": "r1", "name": "demo", "api_key": "must-not-leak"}]},
        database_name="quantum_github",
        extra_files={"offline_chat.json": b'{"hello":"offline reply"}'},
    )
    assert manifest["version"] == 1
    loaded_manifest, collections = load_bundle(bundle)
    assert loaded_manifest["format"] == "entangle-snapshot"
    assert collections["repositories"][0]["api_key"] == "[REDACTED]"
    (bundle / "collections" / "repositories.jsonl").write_text(
        "tampered\n", encoding="utf-8"
    )
    with pytest.raises(SnapshotError, match="Checksum"):
        load_bundle(bundle)
    with pytest.raises(SnapshotError, match="vacía"):
        load_bundle("")


def test_snapshot_preserves_and_recreates_indexes(tmp_path):
    bundle = tmp_path / "snapshot-indexes"
    write_bundle(
        bundle,
        {"repositories": [{"_id": "r1", "embedding": [0.1, 0.2]}]},
        database_name="quantum_github",
        indexes={
            "repositories": [
                {
                    "name": "embedding_vector",
                    "key": {"embedding": "cosmosSearch"},
                    "cosmosSearchOptions": {
                        "kind": "vector-ivf",
                        "numLists": 10,
                        "similarity": "COS",
                        "dimensions": 2,
                    },
                }
            ]
        },
    )
    manifest, _ = load_bundle(bundle)
    definitions = manifest["collections"]["repositories"]["indexes"]
    assert definitions[0]["name"] == "embedding_vector"
    assert definitions[0]["key"] == [["embedding", "cosmosSearch"]]

    collection = MagicMock()
    collection.name = "repositories"
    collection.list_indexes.return_value = [
        {"name": "_id_"},
        {
            "name": "embedding_vector",
            "key": {"embedding": "cosmosSearch"},
            "cosmosSearchOptions": {
                "kind": "vector-ivf",
                "numLists": 10,
                "similarity": "COS",
                "dimensions": 2,
            },
        },
    ]
    recreate_indexes(collection, definitions)
    collection.create_index.assert_called_once_with(
        [("embedding", "cosmosSearch")],
        name="embedding_vector",
        cosmosSearchOptions={
            "kind": "vector-ivf",
            "numLists": 10,
            "similarity": "COS",
            "dimensions": 2,
        },
    )


def test_snapshot_preserves_compound_index_order(tmp_path):
    bundle = tmp_path / "compound-index"
    write_bundle(
        bundle,
        {"repositories": [{"_id": "r1"}]},
        database_name="quantum_github",
        indexes={
            "repositories": [
                {"name": "ordered", "key": {"z": 1, "a": -1}, "unique": True}
            ]
        },
    )
    manifest, _ = load_bundle(bundle)
    definition = manifest["collections"]["repositories"]["indexes"][0]
    assert definition["key"] == [["z", 1], ["a", -1]]


def test_disabled_github_blocks_enrichment_rest(monkeypatch):
    from src.github.repositories_enrichment import EnrichmentEngine

    monkeypatch.setattr(config, "GITHUB_PROVIDER", "disabled")
    with pytest.raises(RuntimeError, match="deshabilitado"):
        EnrichmentEngine("still-present", MagicMock())


def test_offline_provider_replays_captured_reply(monkeypatch):
    fixture = Path(__file__).parents[1] / "preservation" / "fixtures" / "offline"
    monkeypatch.setattr(config, "AI_PROVIDER", "offline")
    monkeypatch.setattr(config, "SNAPSHOT_PATH", str(fixture))
    response = get_ai_provider().complete(
        {"messages": [{"role": "user", "content": "what is this?"}]}
    )
    assert "deterministic" in response["choices"][0]["message"]["content"]


def test_snapshot_configuration_requires_portable_database(monkeypatch):
    monkeypatch.setattr(Config, "DATA_MODE", "snapshot")
    monkeypatch.setattr(Config, "DATABASE_PROVIDER", "mongo")
    monkeypatch.setattr(Config, "SNAPSHOT_PATH", "fixture")
    monkeypatch.setattr(Config, "AI_PROVIDER", "offline")
    with pytest.raises(ValueError, match="portable-mongo"):
        Config.validate()


def test_production_snapshot_azure_requires_managed_identity(monkeypatch):
    monkeypatch.setattr(Config, "ENVIRONMENT", "production")
    monkeypatch.setattr(Config, "DATA_MODE", "snapshot")
    monkeypatch.setattr(Config, "DATABASE_PROVIDER", "portable-mongo")
    monkeypatch.setattr(Config, "SNAPSHOT_PATH", "fixture")
    monkeypatch.setattr(Config, "AI_PROVIDER", "azure-openai")
    monkeypatch.setattr(Config, "AZURE_AI_ENDPOINT", "https://example.services.ai.azure.com")
    monkeypatch.setattr(Config, "AZURE_MANAGED_IDENTITY_CLIENT_ID", "")
    with pytest.raises(ValueError, match="AZURE_MANAGED_IDENTITY_CLIENT_ID"):
        Config.validate()


def test_snapshot_database_runs_without_external_mongo(monkeypatch):
    fixture = Path(__file__).parents[1] / "preservation" / "fixtures" / "offline"
    db.disconnect()
    monkeypatch.setattr(config, "DATA_MODE", "snapshot")
    monkeypatch.setattr(config, "DATABASE_PROVIDER", "portable-mongo")
    monkeypatch.setattr(config, "SNAPSHOT_PATH", str(fixture))
    db.connect()
    assert db.get_collection("repositories").count_documents({}) == 1
    db.disconnect()


def test_sparse_offline_snapshot_dashboard_uses_zero_for_missing_average(monkeypatch):
    fixture = Path(__file__).parents[1] / "preservation" / "fixtures" / "offline"
    db.disconnect()
    monkeypatch.setattr(config, "DATA_MODE", "snapshot")
    monkeypatch.setattr(config, "DATABASE_PROVIDER", "portable-mongo")
    monkeypatch.setattr(config, "SNAPSHOT_PATH", str(fixture))
    db.connect()
    try:
        dashboard = asyncio.run(
            get_dashboard_stats(
                force_refresh=False,
                org=None,
                language=None,
                repo=None,
                collab_type=None,
                include_bots=False,
                discipline=None,
            )
        )
        assert dashboard["kpis"]["avgExpertise"] == 0
        assert dashboard["kpis"]["avgStars"] == 42.0
    finally:
        db.disconnect()


def test_snapshot_excludes_admin_documents_and_rejects_unexpected_files(tmp_path):
    bundle = tmp_path / "snapshot"
    manifest = write_bundle(
        bundle,
        {
            "repositories": [{"_id": "r1", "password_hash": "must-not-export"}],
            "admin_config": [{"password_hash": "admin-secret"}],
        },
        database_name="quantum_github",
    )
    assert "admin_config" not in manifest["collections"]
    assert manifest["excluded_collections"] == ["admin_config"]
    assert load_bundle(bundle)[1]["repositories"][0]["password_hash"] == "[REDACTED]"
    (bundle / "unexpected.txt").write_text("not covered by manifest", encoding="utf-8")
    with pytest.raises(SnapshotError, match="inesperados"):
        load_bundle(bundle)


def test_offline_chat_requires_verified_sidecar(monkeypatch, tmp_path):
    bundle = tmp_path / "snapshot"
    write_bundle(
        bundle,
        {},
        database_name="quantum_github",
        extra_files={"offline_chat.json": b"{}"},
    )
    (bundle / "offline_chat.json").write_text('{"x":"tampered"}', encoding="utf-8")
    monkeypatch.setattr(config, "AI_PROVIDER", "offline")
    monkeypatch.setattr(config, "SNAPSHOT_PATH", str(bundle))
    with pytest.raises(SnapshotError, match="Checksum"):
        get_ai_provider().complete({"messages": [{"role": "user", "content": "x"}]})


def test_disabled_search_blocks_arxiv(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_PROVIDER", "disabled")
    assert "disabled" in search_arxiv("quantum")


def test_disabled_github_provider_never_calls_network(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_PROVIDER", "disabled")
    monkeypatch.setattr(config, "GITHUB_TOKEN", "still-present")
    client = GitHubGraphQLClient()
    with patch("requests.post") as post:
        with pytest.raises(RuntimeError, match="deshabilitado|no configurada"):
            client.execute_query("query { viewer { login } }")
        with pytest.raises(RuntimeError, match="deshabilitado"):
            client.search_repositories_segmented(search_keyword="qiskit")
        post.assert_not_called()


def test_openai_compatible_includes_model_without_azure_reasoning_params(monkeypatch):
    monkeypatch.setattr(config, "AI_MODEL", "llama3.2")
    payload = OpenAICompatibleProvider().prepare_chat_payload(
        {"messages": [], "reasoning_effort": "minimal", "max_completion_tokens": 400}
    )
    assert payload["model"] == "llama3.2"
    assert "reasoning_effort" not in payload
    assert "max_completion_tokens" not in payload


def test_bedrock_maps_tools_and_tool_results(monkeypatch):
    monkeypatch.setattr(config, "AI_MODEL", "amazon.nova-lite-v1:0")
    monkeypatch.setattr(config, "AWS_REGION", "eu-west-1")
    response = {
        "output": {
            "message": {
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "call-1",
                            "name": "query",
                            "input": {"limit": 1},
                        }
                    }
                ]
            }
        }
    }
    client = MagicMock()
    client.converse.return_value = response
    payload = {
        "messages": [{"role": "user", "content": "find data"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "query",
                    "description": "q",
                    "parameters": {"type": "object"},
                },
            }
        ],
        "tool_choice": "required",
    }
    with patch("boto3.client", return_value=client):
        result = BedrockProvider().complete(payload)
    request = client.converse.call_args.kwargs
    assert request["toolConfig"]["toolChoice"] == {"any": {}}
    assert (
        result["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "query"
    )


def test_liveness_does_not_ping_database(monkeypatch):
    monkeypatch.setattr(
        db, "is_connected", lambda: (_ for _ in ()).throw(AssertionError("no ping"))
    )
    monkeypatch.setattr(db, "is_ready", lambda: True)
    response = asyncio.run(health_check())
    assert response["status"] == "healthy"
