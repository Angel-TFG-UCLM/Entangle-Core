"""Tests for the INSIGHTS worker tools (find_similar_repos, compare_repos,
collaboration_strength).

These tools query the real Mongo schema fields:
  - owner.login (not owner_login)
  - collaborators[].login (not top_contributors)
  - license_info.spdx_id (not license)
  - repository_topics (not topics)
  - url (not html_url)

The tests below lock in that field mapping so the bug we hit in production
(0 shared contributors because of wrong field names) cannot regress.
"""
import json
from unittest.mock import MagicMock

import pytest

from src.ai import insights_tools


# ──────────────────────────────────────────────────────────────────────
# Fakes for Mongo collections
# ──────────────────────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def limit(self, n):
        return FakeCursor(self._docs[:n])

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    def __init__(self, find_one_fn=None, find_fn=None, count_fn=None):
        self._find_one_fn = find_one_fn or (lambda q, p=None: None)
        self._find_fn = find_fn or (lambda q, p=None: [])
        self._count_fn = count_fn or (lambda q: 0)

    def find_one(self, query, projection=None):
        return self._find_one_fn(query, projection)

    def find(self, query, projection=None):
        return FakeCursor(self._find_fn(query, projection))

    def count_documents(self, query):
        return self._count_fn(query)


def _patch_db(monkeypatch, collections):
    """Patch insights_tools.db so get_collection(name) returns a fake."""
    fake_db = MagicMock()
    fake_db.ensure_connection = MagicMock()
    fake_db.get_collection = MagicMock(side_effect=lambda name: collections[name])
    monkeypatch.setattr(insights_tools, "db", fake_db)
    return fake_db


# ──────────────────────────────────────────────────────────────────────
# _interpret_strength
# ──────────────────────────────────────────────────────────────────────

def test_interpret_strength_thresholds():
    assert insights_tools._interpret_strength(0.0, 0) == "ninguna colaboración detectada"
    assert insights_tools._interpret_strength(0.5, 100) == "colaboración muy fuerte"
    assert insights_tools._interpret_strength(0.15, 50) == "colaboración significativa"
    assert insights_tools._interpret_strength(0.05, 10) == "colaboración moderada"
    assert insights_tools._interpret_strength(0.01, 2) == "colaboración débil"


# ──────────────────────────────────────────────────────────────────────
# compare_repos
# ──────────────────────────────────────────────────────────────────────

def test_compare_repos_requires_at_least_two():
    result = json.loads(insights_tools.compare_repos(["qiskit"]))
    assert "error" in result


def test_compare_repos_maps_real_fields(monkeypatch):
    qiskit_doc = {
        "full_name": "Qiskit/qiskit",
        "name": "qiskit",
        "description": "Qiskit SDK",
        "stargazer_count": 7092,
        "fork_count": 2778,
        "watchers_count": 226,
        "open_issues_count": 859,
        "primary_language": "Python",
        "license_info": {"spdx_id": "Apache-2.0", "name": "Apache License 2.0"},
        "repository_topics": ["quantum-computing", "qiskit", "sdk"],
        "owner": {"login": "Qiskit"},
        "collaborators_count": 656,
        "collaborators": [{"login": "a"}, {"login": "b"}],
        "created_at": "2017-03-03",
        "pushed_at": "2026-03-02",
        "url": "https://github.com/Qiskit/qiskit",
    }
    cirq_doc = {
        "full_name": "quantumlib/Cirq",
        "name": "Cirq",
        "stargazer_count": 4881,
        "owner": {"login": "quantumlib"},
        "collaborators_count": 200,
        "repository_topics": ["quantum"],
        "license_info": {"spdx_id": "Apache-2.0"},
        "url": "https://github.com/quantumlib/Cirq",
    }

    def find_one(query, projection=None):
        # Match by full_name or name regex content
        q = json.dumps(query)
        if "qiskit" in q.lower():
            return qiskit_doc
        if "cirq" in q.lower():
            return cirq_doc
        return None

    _patch_db(monkeypatch, {"repositories": FakeCollection(find_one_fn=find_one)})

    payload = json.loads(insights_tools.compare_repos(["Qiskit/qiskit", "quantumlib/Cirq"]))
    assert payload["count"] == 2
    assert payload["not_found"] == []
    row = payload["results"][0]
    # Field mapping locked in
    assert row["full_name"] == "Qiskit/qiskit"
    assert row["stargazer_count"] == 7092
    assert row["watcher_count"] == 226          # from watchers_count
    assert row["license"] == "Apache-2.0"        # from license_info.spdx_id
    assert row["owner"] == "Qiskit"              # from owner.login
    assert row["contributors_count"] == 656      # from collaborators_count
    assert "quantum-computing" in row["topics"]  # from repository_topics
    assert row["url"] == "https://github.com/Qiskit/qiskit"


def test_compare_repos_reports_not_found(monkeypatch):
    found = {
        "full_name": "Qiskit/qiskit", "name": "qiskit", "owner": {"login": "Qiskit"},
        "stargazer_count": 1, "url": "u",
    }

    def find_one(query, projection=None):
        q = json.dumps(query).lower()
        if "qiskit" in q:
            return found
        return None

    _patch_db(monkeypatch, {"repositories": FakeCollection(find_one_fn=find_one)})
    payload = json.loads(insights_tools.compare_repos(["qiskit", "nonexistent-xyz"]))
    assert payload["count"] == 1
    assert "nonexistent-xyz" in payload["not_found"]


def test_compare_repos_caps_at_five(monkeypatch):
    seen = []

    def find_one(query, projection=None):
        seen.append(query)
        return {"full_name": "x/y", "name": "y", "owner": {"login": "x"}, "stargazer_count": 0, "url": "u"}

    _patch_db(monkeypatch, {"repositories": FakeCollection(find_one_fn=find_one)})
    insights_tools.compare_repos(["a", "b", "c", "d", "e", "f", "g"])
    # Only 5 lookups despite 7 requested
    assert len(seen) == 5


# ──────────────────────────────────────────────────────────────────────
# collaboration_strength — org vs org
# ──────────────────────────────────────────────────────────────────────

def test_collaboration_org_vs_org_shares_contributors(monkeypatch):
    org_a = {"login": "Qiskit"}
    org_b = {"login": "qiskit-community"}

    # Repos for each org with collaborators (real field shape)
    repos_a = [{"collaborators": [{"login": "alice"}, {"login": "bob"}, {"login": "carol"}]}]
    repos_b = [{"collaborators": [{"login": "bob"}, {"login": "carol"}, {"login": "dave"}]}]

    def org_find_one(query, projection=None):
        q = json.dumps(query).lower()
        if "qiskit-community" in q:
            return org_b
        if "qiskit" in q:
            return org_a
        return None

    def repos_find(query, projection=None):
        q = json.dumps(query)
        if "qiskit-community" in q:
            return repos_b
        if "Qiskit" in q:
            return repos_a
        return []

    def repos_count(query):
        q = json.dumps(query)
        return 51 if "qiskit-community" in q else 32

    collections = {
        "organizations": FakeCollection(find_one_fn=org_find_one),
        "users": FakeCollection(),  # not used in org-vs-org
        "repositories": FakeCollection(find_fn=repos_find, count_fn=repos_count),
    }
    _patch_db(monkeypatch, collections)

    payload = json.loads(insights_tools.collaboration_strength("Qiskit", "qiskit-community"))
    assert payload["kind"] == "org_vs_org"
    # alice,bob,carol ∩ bob,carol,dave = {bob, carol}
    assert payload["shared_count"] == 2
    assert set(payload["shared_contributors"]) == {"bob", "carol"}
    # union = 4, shared = 2 → 0.5
    assert payload["jaccard_similarity"] == 0.5
    assert payload["entity_a"]["repos"] == 32
    assert payload["entity_b"]["repos"] == 51
    assert payload["interpretation"] == "colaboración muy fuerte"


def test_collaboration_entity_not_found(monkeypatch):
    collections = {
        "organizations": FakeCollection(),  # returns None always
        "users": FakeCollection(),
        "repositories": FakeCollection(),
    }
    _patch_db(monkeypatch, collections)
    payload = json.loads(insights_tools.collaboration_strength("ghost1", "ghost2"))
    assert "error" in payload


def test_collaboration_user_vs_user(monkeypatch):
    user_a = {"login": "alice"}
    user_b = {"login": "bob"}

    def user_find_one(query, projection=None):
        q = json.dumps(query).lower()
        if "alice" in q:
            return user_a
        if "bob" in q:
            return user_b
        return None

    def repos_find(query, projection=None):
        q = json.dumps(query)
        if "alice" in q:
            return [{"full_name": "r1"}, {"full_name": "r2"}]
        if "bob" in q:
            return [{"full_name": "r2"}, {"full_name": "r3"}]
        return []

    collections = {
        "organizations": FakeCollection(),  # both resolve as users (orgs return None)
        "users": FakeCollection(find_one_fn=user_find_one),
        "repositories": FakeCollection(find_fn=repos_find),
    }
    _patch_db(monkeypatch, collections)

    payload = json.loads(insights_tools.collaboration_strength("alice", "bob", kind="user"))
    assert payload["kind"] == "user_vs_user"
    assert payload["shared_repos"] == ["r2"]
    assert payload["shared_count"] == 1


def test_collaboration_user_vs_org(monkeypatch):
    org = {"login": "Qiskit"}
    user = {"login": "alice"}

    def org_find_one(query, projection=None):
        q = json.dumps(query).lower()
        return org if "qiskit" in q else None

    def user_find_one(query, projection=None):
        q = json.dumps(query).lower()
        return user if "alice" in q else None

    def repos_find(query, projection=None):
        return [{"full_name": "Qiskit/qiskit", "stargazer_count": 7092}]

    def repos_count(query):
        return 32

    collections = {
        "organizations": FakeCollection(find_one_fn=org_find_one),
        "users": FakeCollection(find_one_fn=user_find_one),
        "repositories": FakeCollection(find_fn=repos_find, count_fn=repos_count),
    }
    _patch_db(monkeypatch, collections)

    payload = json.loads(insights_tools.collaboration_strength("Qiskit", "alice"))
    assert payload["kind"] == "user_vs_org"
    assert payload["user"] == "alice"
    assert payload["org"] == "Qiskit"
    assert payload["contributed_count"] == 1
    assert payload["total_org_repos"] == 32


# ──────────────────────────────────────────────────────────────────────
# find_similar_repos
# ──────────────────────────────────────────────────────────────────────

def test_find_similar_repo_not_found(monkeypatch):
    _patch_db(monkeypatch, {"repositories": FakeCollection(), "repos_chunks": FakeCollection()})
    payload = json.loads(insights_tools.find_similar_repos("nonexistent-xyz"))
    assert "error" in payload


def test_find_similar_repos_returns_results(monkeypatch):
    ref_doc = {
        "_id": "obj1",
        "id": "R_ref",
        "full_name": "Qiskit/qiskit",
        "name": "qiskit",
        "description": "Qiskit SDK",
        "stargazer_count": 7092,
    }
    similar_doc = {
        "id": "R_sim",
        "full_name": "qiskit-community/qiskit-experiments",
        "name": "qiskit-experiments",
        "description": "Experiments on Qiskit",
        "stargazer_count": 189,
        "primary_language": "Python",
        "repository_topics": ["quantum"],
        "url": "https://github.com/qiskit-community/qiskit-experiments",
    }

    def repos_find_one(query, projection=None):
        # reload-by-_id after candidate selection
        if "_id" in query:
            return ref_doc
        q = json.dumps(query).lower()
        return ref_doc if "qiskit" in q else None

    def repos_find(query, projection=None):
        q = json.dumps(query)
        if "$in" in q:
            # enrichment lookup by id
            return [similar_doc]
        # candidates lookup by name/full_name regex
        return [ref_doc]

    def chunks_find(query, projection=None):
        return [{"text": "Qiskit is an open-source SDK"}]

    collections = {
        "repositories": FakeCollection(find_one_fn=repos_find_one, find_fn=repos_find),
        "repos_chunks": FakeCollection(find_fn=chunks_find),
    }
    _patch_db(monkeypatch, collections)

    monkeypatch.setattr(insights_tools, "embed_one", MagicMock(return_value=[0.1] * 1536))
    monkeypatch.setattr(insights_tools, "vector_search", MagicMock(return_value=[
        {"source_id": "repo:R_sim", "score": 0.74, "text": "Experiments on Qiskit"},
        {"source_id": "repo:R_ref", "score": 0.99, "text": "self"},  # ref excluded
    ]))

    payload = json.loads(insights_tools.find_similar_repos("qiskit", top_k=5))
    assert payload["reference"] == "Qiskit/qiskit"
    assert payload["count"] == 1
    res = payload["results"][0]
    assert res["full_name"] == "qiskit-community/qiskit-experiments"
    assert res["similarity"] == 0.74
    assert res["url"].endswith("qiskit-experiments")


def test_find_similar_repos_uses_description_when_no_chunks(monkeypatch):
    ref_doc = {
        "_id": "obj1", "id": "R_ref", "full_name": "Foo/bar",
        "name": "bar", "description": "A tiny quantum lib",
    }

    def repos_find_one(query, projection=None):
        if "_id" in query:
            return ref_doc
        q = json.dumps(query).lower()
        return ref_doc if "bar" in q else None

    def repos_find(query, projection=None):
        q = json.dumps(query)
        if "$in" in q:
            return []  # no enrichment matches
        return [ref_doc]  # candidates

    collections = {
        "repositories": FakeCollection(find_one_fn=repos_find_one, find_fn=repos_find),
        "repos_chunks": FakeCollection(find_fn=lambda q, p=None: []),  # no chunks
    }
    _patch_db(monkeypatch, collections)

    embed = MagicMock(return_value=[0.1] * 1536)
    monkeypatch.setattr(insights_tools, "embed_one", embed)
    monkeypatch.setattr(insights_tools, "vector_search", MagicMock(return_value=[]))

    payload = json.loads(insights_tools.find_similar_repos("bar"))
    # No similar results but no crash; embed called with description fallback
    assert payload["count"] == 0
    embed.assert_called_once()
    seed_text = embed.call_args.args[0]
    assert "tiny quantum lib" in seed_text
