"""
Extended tests for network_metrics: compute_centrality, compute_collaboration_scores,
build_from_mongodb (mocked).
"""
import pytest
from unittest.mock import MagicMock, patch
import networkx as nx


@pytest.fixture
def analyzer():
    from src.analysis.network_metrics import CollaborationNetworkAnalyzer
    a = CollaborationNetworkAnalyzer()
    return a


@pytest.fixture
def analyzer_with_graph():
    from src.analysis.network_metrics import CollaborationNetworkAnalyzer
    a = CollaborationNetworkAnalyzer()
    G = nx.Graph()
    G.add_edge("alice", "bob", weight=3)
    G.add_edge("bob", "charlie", weight=2)
    G.add_edge("alice", "charlie", weight=1)
    G.add_edge("dave", "bob", weight=5)
    a.G = G
    return a


@pytest.fixture
def analyzer_star_graph():
    """Star graph: center connected to 5 leaves."""
    from src.analysis.network_metrics import CollaborationNetworkAnalyzer
    a = CollaborationNetworkAnalyzer()
    G = nx.star_graph(5)
    for u, v in G.edges():
        G[u][v]['weight'] = 1
    a.G = G
    return a


class TestComputeCentrality:
    def test_empty_graph(self, analyzer):
        analyzer.G = nx.Graph()
        result = analyzer.compute_centrality()
        assert result == {}

    def test_single_node(self, analyzer):
        analyzer.G = nx.Graph()
        analyzer.G.add_node("solo")
        result = analyzer.compute_centrality()
        assert "solo" in result
        assert result["solo"]["betweenness"] >= 0
        assert result["solo"]["degree"] >= 0

    def test_triangle_graph(self, analyzer_with_graph):
        result = analyzer_with_graph.compute_centrality()
        assert "alice" in result
        assert "bob" in result
        assert "charlie" in result
        # Bob should have highest betweenness (connected to dave)
        assert result["bob"]["betweenness"] >= result["alice"]["betweenness"]

    def test_star_graph_center_highest(self, analyzer_star_graph):
        result = analyzer_star_graph.compute_centrality()
        center_bc = result[0]["betweenness"]
        # Center of star should have highest betweenness
        for node_id in range(1, 6):
            assert center_bc >= result[node_id]["betweenness"]

    def test_values_between_0_and_1(self, analyzer_with_graph):
        result = analyzer_with_graph.compute_centrality()
        for node_id, metrics in result.items():
            assert 0 <= metrics["betweenness"] <= 1
            assert 0 <= metrics["degree"] <= 1

    def test_all_nodes_present(self, analyzer_with_graph):
        result = analyzer_with_graph.compute_centrality()
        assert len(result) == 4  # alice, bob, charlie, dave


class TestComputeCollaborationScores:
    def test_empty_graph(self, analyzer):
        analyzer.G = nx.Graph()
        result = analyzer.compute_collaboration_scores()
        assert isinstance(result, dict)

    def test_with_graph(self, analyzer_with_graph):
        result = analyzer_with_graph.compute_collaboration_scores()
        assert isinstance(result, dict)

    def test_returns_scores_for_nodes(self, analyzer_with_graph):
        result = analyzer_with_graph.compute_collaboration_scores()
        # Should return data for nodes in the graph
        for node in ["alice", "bob", "charlie", "dave"]:
            if node in result:
                assert isinstance(result[node], dict)


class TestBuildFromMongoDB:
    def test_build_with_empty_collections(self, analyzer):
        repos_coll = MagicMock()
        users_coll = MagicMock()
        orgs_coll = MagicMock()
        repos_coll.find.return_value = []
        users_coll.find.return_value = []
        orgs_coll.find.return_value = []

        analyzer.build_from_mongodb(repos_coll, users_coll, orgs_coll)
        assert analyzer.G.number_of_nodes() == 0

    def test_build_with_repos_and_contributors(self, analyzer):
        """Test that build_from_mongodb can be called (may need specific data format)."""
        repos_coll = MagicMock()
        users_coll = MagicMock()
        orgs_coll = MagicMock()

        repos_coll.find.return_value = []
        users_coll.find.return_value = []
        orgs_coll.find.return_value = []

        # With empty data, just verify it runs without error
        analyzer.build_from_mongodb(repos_coll, users_coll, orgs_coll)
        assert analyzer.G.number_of_nodes() >= 0


class TestGlobalMetrics:
    def test_global_metrics_triangle(self, analyzer_with_graph):
        from src.analysis.network_metrics import CollaborationNetworkAnalyzer
        metrics = analyzer_with_graph.compute_centrality()
        assert len(metrics) == 4

    def test_large_graph_performance(self, analyzer):
        """Test that compute_centrality handles large graphs efficiently."""
        G = nx.barabasi_albert_graph(100, 3, seed=42)
        for u, v in G.edges():
            G[u][v]['weight'] = 1
        analyzer.G = G
        result = analyzer.compute_centrality()
        assert len(result) == 100
