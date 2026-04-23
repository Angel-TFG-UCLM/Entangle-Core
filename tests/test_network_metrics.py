"""
Tests for src.analysis.network_metrics
========================================
Unit tests for pure/helper functions in the network analysis module.
Mocks NetworkX for class-level methods. 
"""
import pytest
import networkx as nx
from unittest.mock import MagicMock, patch
from src.analysis.network_metrics import (
    _hsl_to_hex,
    community_color,
    _are_sibling_orgs,
    GOLDEN_ANGLE,
    CollaborationNetworkAnalyzer,
)


# ========================================================================
# _hsl_to_hex
# ========================================================================
class TestHslToHex:
    def test_red(self):
        result = _hsl_to_hex(0, 100, 50)
        assert result.startswith("#")
        assert len(result) == 7

    def test_green(self):
        result = _hsl_to_hex(120, 100, 50)
        assert isinstance(result, str)

    def test_blue(self):
        result = _hsl_to_hex(240, 100, 50)
        assert result.startswith("#")

    def test_black(self):
        result = _hsl_to_hex(0, 0, 0)
        assert result == "#000000"

    def test_white(self):
        result = _hsl_to_hex(0, 0, 100)
        assert result == "#ffffff"

    def test_returns_hex_format(self):
        for h in range(0, 360, 60):
            r = _hsl_to_hex(h, 80, 60)
            assert len(r) == 7 and r[0] == "#"


# ========================================================================
# community_color
# ========================================================================
class TestCommunityColor:
    def test_deterministic(self):
        assert community_color(0) == community_color(0)
        assert community_color(5) == community_color(5)

    def test_different_for_consecutive_indices(self):
        colors = [community_color(i) for i in range(10)]
        # Most should be distinct
        assert len(set(colors)) >= 7

    def test_returns_hex_string(self):
        for i in range(20):
            c = community_color(i)
            assert c.startswith("#") and len(c) == 7

    def test_golden_angle_constant(self):
        assert GOLDEN_ANGLE == pytest.approx(137.508)


# ========================================================================
# _are_sibling_orgs
# ========================================================================
class TestAreSiblingOrgs:
    def test_identical(self):
        assert _are_sibling_orgs("qiskit", "qiskit") is True

    def test_case_insensitive(self):
        assert _are_sibling_orgs("Qiskit", "qiskit") is True

    def test_prefix_sibling(self):
        assert _are_sibling_orgs("qiskit", "qiskit-community") is True

    def test_no_relation(self):
        assert _are_sibling_orgs("google", "microsoft") is False

    def test_empty_strings(self):
        assert _are_sibling_orgs("", "qiskit") is False
        assert _are_sibling_orgs("qiskit", "") is False

    def test_none_values(self):
        assert _are_sibling_orgs(None, "x") is False
        assert _are_sibling_orgs("x", None) is False

    def test_short_prefix_rejected(self):
        # Prefix must be >= 4 chars
        assert _are_sibling_orgs("ibm", "ibm-quantum") is False

    def test_long_prefix_accepted(self):
        assert _are_sibling_orgs("microsoft", "MicrosoftDocs") is True

    def test_ratio_too_large(self):
        # If longer name is >3x shorter, should reject
        assert _are_sibling_orgs("test", "testverylongnamethatexceedsratio") is False

    def test_both_multitoken_no_match(self):
        # Both multi-token with same first token → False (requires one single-token)
        assert _are_sibling_orgs("quantum-X", "quantum-Y") is False


# ========================================================================
# _detect_bot_by_login (static method)
# ========================================================================
class TestDetectBotByLogin:
    def test_bot_suffix(self):
        assert CollaborationNetworkAnalyzer._detect_bot_by_login("github-actions[bot]") is True

    def test_dependabot(self):
        assert CollaborationNetworkAnalyzer._detect_bot_by_login("dependabot") is True

    def test_renovate(self):
        assert CollaborationNetworkAnalyzer._detect_bot_by_login("renovate-bot") is True

    def test_normal_user(self):
        assert CollaborationNetworkAnalyzer._detect_bot_by_login("johndoe") is False

    def test_snyk(self):
        assert CollaborationNetworkAnalyzer._detect_bot_by_login("snyk-bot") is True

    def test_codecov(self):
        assert CollaborationNetworkAnalyzer._detect_bot_by_login("codecov-reporter") is True

    def test_case_insensitive(self):
        assert CollaborationNetworkAnalyzer._detect_bot_by_login("Dependabot-Preview") is True


# ========================================================================
# CollaborationNetworkAnalyzer - unit-level with small graphs
# ========================================================================
class TestAnalyzerComputeCentrality:
    def test_empty_graph(self):
        a = CollaborationNetworkAnalyzer()
        assert a.compute_centrality() == {}

    def test_simple_graph(self):
        a = CollaborationNetworkAnalyzer()
        a.G.add_node("user_alice", type="user")
        a.G.add_node("repo_test/test", type="repo")
        a.G.add_edge("user_alice", "repo_test/test", weight=5, type="contributed_to")
        result = a.compute_centrality()
        assert "user_alice" in result
        assert "betweenness" in result["user_alice"]
        assert "degree" in result["user_alice"]


class TestAnalyzerComputeGlobalMetrics:
    def test_empty_graph(self):
        a = CollaborationNetworkAnalyzer()
        assert a.compute_global_metrics() == {}

    def test_simple_metrics(self):
        a = CollaborationNetworkAnalyzer()
        a.G.add_node("user_a", type="user")
        a.G.add_node("repo_r", type="repo")
        a.G.add_edge("user_a", "repo_r", weight=1, type="contributed_to")
        m = a.compute_global_metrics()
        assert m["num_nodes"] == 2
        assert m["num_edges"] == 1
        assert "density" in m
        assert "node_types" in m
        assert m["node_types"]["user"] == 1
        assert m["node_types"]["repo"] == 1


class TestAnalyzerFindPath:
    def test_missing_source(self):
        a = CollaborationNetworkAnalyzer()
        a.G.add_node("user_a", type="user")
        result = a.find_path("user_nonexistent", "user_a")
        assert result is None or (isinstance(result, dict) and "error" in str(result).lower())

    def test_same_node(self):
        a = CollaborationNetworkAnalyzer()
        a.G.add_node("user_a", type="user")
        result = a.find_path("user_a", "user_a")
        # Should return a path of length 0 or the node itself
        assert result is not None


class TestAnalyzerBusFactor:
    def test_empty_graph(self):
        a = CollaborationNetworkAnalyzer()
        result = a.compute_bus_factor()
        assert isinstance(result, (dict, list))

    def test_single_contributor(self):
        a = CollaborationNetworkAnalyzer()
        a.G.add_node("user_a", type="user")
        a.G.add_node("repo_r", type="repo")
        a.G.add_edge("user_a", "repo_r", weight=100, contributions=100, type="contributed_to")
        a._repos_data["r"] = {"full_name": "r"}
        result = a.compute_bus_factor()
        assert isinstance(result, (dict, list))
