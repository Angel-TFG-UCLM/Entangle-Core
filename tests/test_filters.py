"""
Tests for src.github.filters
=============================
Tests for RepositoryFilters and helper functions — mostly pure logic.
"""
import pytest
from datetime import datetime, timezone, timedelta
from src.github.filters import (
    RepositoryFilters,
    _get_searchable_text,
    _has_strong_keywords,
    filter_by_activity,
    filter_by_fork_validity,
    filter_by_documentation,
    NON_QC_BLACKLIST_PATTERNS,
    NON_QC_KNOWN_REPOS,
    REAL_QC_KEYWORDS,
)


# ── Helpers ──

def _make_repo(**overrides):
    """Create a minimal repo dict with sensible defaults."""
    now = datetime.now(timezone.utc)
    repo = {
        "name": "quantum-test",
        "nameWithOwner": "user/quantum-test",
        "description": "A quantum computing test repo",
        "updatedAt": now.isoformat(),
        "pushedAt": now.isoformat(),
        "isFork": False,
        "isArchived": False,
        "stargazerCount": 50,
        "forkCount": 10,
        "diskUsage": 500,
        "watchers": {"totalCount": 20},
        "primaryLanguage": {"name": "Python"},
        "defaultBranchRef": {
            "target": {"history": {"totalCount": 100}}
        },
        "repositoryTopics": {"nodes": []},
        "object": {"text": "# Quantum Computing Repo\nqiskit based library"},
    }
    repo.update(overrides)
    return repo


class TestGetSearchableText:

    def test_basic(self):
        repo = _make_repo()
        text = _get_searchable_text(repo)
        assert "quantum-test" in text
        assert "quantum computing test repo" in text

    def test_with_topics(self):
        repo = _make_repo(repositoryTopics={
            "nodes": [{"topic": {"name": "quantum-circuit"}}, {"topic": {"name": "openqasm"}}]
        })
        text = _get_searchable_text(repo)
        assert "quantum-circuit" in text
        assert "openqasm" in text

    def test_with_readme(self):
        repo = _make_repo(object={"text": "This is a Qiskit based project for VQE"})
        text = _get_searchable_text(repo)
        assert "qiskit" in text

    def test_no_readme(self):
        repo = _make_repo(object=None)
        text = _get_searchable_text(repo)
        assert "quantum-test" in text

    def test_none_description(self):
        repo = _make_repo(description=None)
        text = _get_searchable_text(repo)
        assert "quantum-test" in text


class TestHasStrongKeywords:

    def test_found(self):
        assert _has_strong_keywords("this uses qiskit for circuits", ["qiskit", "cirq"])

    def test_not_found(self):
        assert not _has_strong_keywords("this is just a web app", ["qiskit", "cirq"])

    def test_case_insensitive(self):
        # Function expects text in lowercase; keywords are lowered internally
        assert _has_strong_keywords("qiskit is here", ["QISKIT"])

    def test_empty_keywords(self):
        assert not _has_strong_keywords("some text", [])


class TestIsActive:

    def test_recent_repo(self):
        repo = _make_repo()
        assert RepositoryFilters.is_active(repo)

    def test_old_repo(self):
        old_date = (datetime.now(timezone.utc) - timedelta(days=500)).isoformat()
        repo = _make_repo(updatedAt=old_date, pushedAt=old_date)
        assert not RepositoryFilters.is_active(repo, max_inactivity_days=365)

    def test_no_date(self):
        repo = _make_repo(updatedAt=None, pushedAt=None)
        assert not RepositoryFilters.is_active(repo)

    def test_custom_days(self):
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        repo = _make_repo(updatedAt=old)
        assert RepositoryFilters.is_active(repo, max_inactivity_days=365)
        assert not RepositoryFilters.is_active(repo, max_inactivity_days=30)

    def test_invalid_date(self):
        repo = _make_repo(updatedAt="not-a-date", pushedAt=None)
        assert not RepositoryFilters.is_active(repo)


class TestIsValidFork:

    def test_not_a_fork(self):
        repo = _make_repo(isFork=False)
        assert RepositoryFilters.is_valid_fork(repo)

    def test_fork_with_contributions(self):
        repo = _make_repo(
            isFork=True,
            defaultBranchRef={"target": {"history": {"totalCount": 50}}},
            openIssues={"totalCount": 3},
            closedIssues={"totalCount": 2},
            pullRequests={"totalCount": 5},
        )
        assert RepositoryFilters.is_valid_fork(repo)

    def test_fork_without_contributions(self):
        repo = _make_repo(
            isFork=True,
            defaultBranchRef={"target": {"history": {"totalCount": 2}}},
            openIssues={"totalCount": 0},
            closedIssues={"totalCount": 0},
            pullRequests={"totalCount": 0},
        )
        assert not RepositoryFilters.is_valid_fork(repo)


class TestHasDescription:

    def test_with_description(self):
        repo = _make_repo(description="A quantum computing project")
        assert RepositoryFilters.has_description(repo)

    def test_with_readme_only(self):
        repo = _make_repo(description=None, object={"text": "# Readme"})
        assert RepositoryFilters.has_description(repo)

    def test_no_description_no_readme(self):
        repo = _make_repo(description=None, object=None)
        assert not RepositoryFilters.has_description(repo)

    def test_empty_description(self):
        repo = _make_repo(description="   ", object=None)
        assert not RepositoryFilters.has_description(repo)


class TestIsMinimalProject:

    def test_passes(self):
        repo = _make_repo()
        assert RepositoryFilters.is_minimal_project(repo)

    def test_too_few_commits(self):
        repo = _make_repo(defaultBranchRef={"target": {"history": {"totalCount": 3}}})
        assert not RepositoryFilters.is_minimal_project(repo, min_commits=10)

    def test_too_small(self):
        repo = _make_repo(diskUsage=2)
        assert not RepositoryFilters.is_minimal_project(repo, min_size_kb=10)

    def test_no_branch_ref(self):
        repo = _make_repo(defaultBranchRef=None)
        assert not RepositoryFilters.is_minimal_project(repo)


class TestMatchesKeywords:

    def test_name_match(self):
        repo = _make_repo(name="qiskit-aer")
        assert RepositoryFilters.matches_keywords(repo, ["qiskit"])

    def test_description_match(self):
        repo = _make_repo(description="Quantum computing with cirq")
        assert RepositoryFilters.matches_keywords(repo, ["cirq"])

    def test_topic_match(self):
        repo = _make_repo(repositoryTopics={
            "nodes": [{"topic": {"name": "quantum-computing"}}]
        })
        assert RepositoryFilters.matches_keywords(repo, ["quantum-computing"])

    def test_no_match(self):
        repo = _make_repo(name="web-app", description="A web application", object=None)
        assert not RepositoryFilters.matches_keywords(repo, ["qiskit", "cirq"])

    def test_empty_keywords_list(self):
        repo = _make_repo()
        assert RepositoryFilters.matches_keywords(repo, [])


class TestHasValidLanguage:

    def test_valid_primary(self):
        repo = _make_repo(primaryLanguage={"name": "Python"})
        assert RepositoryFilters.has_valid_language(repo, ["Python", "C++"])

    def test_invalid_primary_valid_secondary(self):
        repo = _make_repo(
            primaryLanguage={"name": "Jupyter Notebook"},
            languages={"edges": [{"node": {"name": "Python"}}]}
        )
        assert RepositoryFilters.has_valid_language(repo, ["Python"])

    def test_invalid_all_but_quantum_keywords(self):
        repo = _make_repo(
            primaryLanguage={"name": "HTML"},
            languages={"edges": []},
            object={"text": "This project uses qiskit for quantum circuits"},
        )
        assert RepositoryFilters.has_valid_language(repo, ["Python"])

    def test_no_language_no_keywords(self):
        repo = _make_repo(primaryLanguage=None, object={"text": "Generic text"})
        assert not RepositoryFilters.has_valid_language(repo, ["Python"])

    def test_no_language_with_keywords(self):
        repo = _make_repo(primaryLanguage=None, object={"text": "Uses qiskit for VQE"})
        assert RepositoryFilters.has_valid_language(repo, ["Python"])


class TestIsNotArchived:

    def test_not_archived(self):
        repo = _make_repo(isArchived=False)
        assert RepositoryFilters.is_not_archived(repo)

    def test_archived(self):
        repo = _make_repo(isArchived=True)
        assert not RepositoryFilters.is_not_archived(repo)


class TestHasMinimumStars:

    def test_enough_stars(self):
        repo = _make_repo(stargazerCount=100)
        assert RepositoryFilters.has_minimum_stars(repo, min_stars=10)

    def test_not_enough_stars(self):
        repo = _make_repo(stargazerCount=5)
        assert not RepositoryFilters.has_minimum_stars(repo, min_stars=10)


class TestHasCommunityEngagement:

    def test_enough_watchers(self):
        repo = _make_repo(watchers={"totalCount": 10}, forkCount=0)
        assert RepositoryFilters.has_community_engagement(repo)

    def test_enough_forks(self):
        repo = _make_repo(watchers={"totalCount": 0}, forkCount=5)
        assert RepositoryFilters.has_community_engagement(repo)

    def test_no_engagement(self):
        repo = _make_repo(watchers={"totalCount": 0}, forkCount=0)
        assert not RepositoryFilters.has_community_engagement(repo)


class TestIsNotBlacklisted:

    def test_normal_repo(self):
        repo = _make_repo()
        assert RepositoryFilters.is_not_blacklisted(repo)

    def test_known_blacklisted(self):
        repo = _make_repo(nameWithOwner="bloomberg/quantum")
        assert not RepositoryFilters.is_not_blacklisted(repo)

    def test_pattern_blacklisted_firefox_quantum(self):
        repo = _make_repo(name="firefox-quantum-extension", description="Firefox quantum browser")
        assert not RepositoryFilters.is_not_blacklisted(repo)

    def test_pattern_blacklisted_quantumult(self):
        repo = _make_repo(name="quantumultx-config", description="quantumult proxy rules")
        assert not RepositoryFilters.is_not_blacklisted(repo)


class TestHasQuantumRelevance:

    def test_with_qc_keywords(self):
        repo = _make_repo(description="Qiskit circuits for VQE algorithm")
        assert RepositoryFilters.has_quantum_relevance(repo)

    def test_generic_quantum_no_context(self):
        repo = _make_repo(
            name="quantum",
            description="quantum app",
            primaryLanguage={"name": "JavaScript"},
            repositoryTopics={"nodes": []},
            object=None,
        )
        assert not RepositoryFilters.has_quantum_relevance(repo)

    def test_generic_quantum_with_context(self):
        repo = _make_repo(
            name="quantum-sim",
            description="quantum simulation algorithm solver framework",
            primaryLanguage={"name": "Python"},
            repositoryTopics={"nodes": [{"topic": {"name": "quantum-physics"}}]},
        )
        assert RepositoryFilters.has_quantum_relevance(repo)

    def test_no_quantum_word(self):
        repo = _make_repo(name="cirq-tools", description="A cirq extension")
        assert RepositoryFilters.has_quantum_relevance(repo)


class TestFilterHelpers:
    """Tests for the helper filter functions."""

    def test_filter_by_activity(self):
        old = (datetime.now(timezone.utc) - timedelta(days=500)).isoformat()
        repos = [
            _make_repo(name="active"),
            _make_repo(name="old", updatedAt=old, pushedAt=old),
        ]
        filtered = filter_by_activity(repos, max_inactivity_days=365)
        assert len(filtered) == 1
        assert filtered[0]["name"] == "active"

    def test_filter_by_fork_validity(self):
        repos = [
            _make_repo(isFork=False),
            _make_repo(
                isFork=True,
                defaultBranchRef={"target": {"history": {"totalCount": 1}}},
                openIssues={"totalCount": 0},
                closedIssues={"totalCount": 0},
                pullRequests={"totalCount": 0},
            ),
        ]
        filtered = filter_by_fork_validity(repos)
        assert len(filtered) == 1

    def test_filter_by_documentation(self):
        repos = [
            _make_repo(description="Documented", object={"text": "readme"}),
            _make_repo(description=None, object=None),
        ]
        filtered = filter_by_documentation(repos)
        assert len(filtered) == 1
