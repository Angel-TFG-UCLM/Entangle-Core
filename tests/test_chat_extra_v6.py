"""Tests for chat routes and additional coverage boosters."""
import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ==================== Chat endpoint (POST /chat) ====================

class TestChatEndpoint:
    @patch('src.api.chat_routes.chat')
    def test_chat_success(self, mock_chat, client):
        mock_chat.return_value = {
            "reply": "Hello! I can help with quantum computing repos.",
            "history": [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "Hello! I can help with quantum computing repos."}
            ],
            "tools_used": ["search_repos"],
            "actions": []
        }
        resp = client.post("/api/v1/chat", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert "reply" in data
        assert data["reply"] == "Hello! I can help with quantum computing repos."

    @patch('src.api.chat_routes.chat')
    def test_chat_with_history(self, mock_chat, client):
        mock_chat.return_value = {
            "reply": "Yes, Qiskit is popular.",
            "history": [],
            "tools_used": [],
            "actions": []
        }
        resp = client.post("/api/v1/chat", json={
            "message": "Tell me about Qiskit",
            "history": [{"role": "user", "content": "hi"}]
        })
        assert resp.status_code == 200

    @patch('src.api.chat_routes.chat')
    def test_chat_error(self, mock_chat, client):
        mock_chat.side_effect = Exception("AI service down")
        resp = client.post("/api/v1/chat", json={"message": "hello"})
        assert resp.status_code == 500

    def test_chat_empty_message(self, client):
        resp = client.post("/api/v1/chat", json={"message": ""})
        assert resp.status_code == 422


# ==================== Chat stream endpoint ====================

class TestChatStreamEndpoint:
    @patch('src.api.chat_routes.chat_stream')
    def test_chat_stream_success(self, mock_stream, client):
        events = [
            json.dumps({"type": "thinking", "content": "Analyzing..."}),
            json.dumps({"type": "answer", "content": "Qiskit is great"}),
        ]
        mock_stream.return_value = iter(events)
        resp = client.post("/api/v1/chat/stream", json={"message": "tell me about Qiskit"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


# ==================== Additional route coverage ====================

class TestAdminOperationRun:
    @patch('src.api.admin_routes._require_admin', return_value=None)
    @patch('src.api.admin_routes.active_operations', {})
    @patch('src.api.admin_routes.cancel_flags', {})
    @patch('src.api.admin_routes.threading')
    def test_run_operation(self, mock_threading, mock_admin, client):
        mock_thread = MagicMock()
        mock_threading.Thread.return_value = mock_thread
        mock_threading.Event.return_value = MagicMock()
        resp = client.post(
            "/api/v1/admin/operations/run?token=fake",
            json={"operation_type": "ingestion", "entity": "repositories", "mode": "incremental"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert "operation_id" in data

    @patch('src.api.admin_routes._require_admin', return_value=None)
    @patch('src.api.admin_routes.active_operations', {
        "op_running": {"operation_id": "op_running", "status": "running",
                       "operation_type": "ingestion", "entity": "repositories"}
    })
    def test_run_operation_conflict(self, mock_admin, client):
        resp = client.post(
            "/api/v1/admin/operations/run?token=fake",
            json={"operation_type": "ingestion", "entity": "repositories", "mode": "incremental"}
        )
        assert resp.status_code == 409


# ==================== _verify_password with valid hash ====================

class TestVerifyPasswordDetailed:
    @patch('src.api.admin_routes._get_admin_collection')
    def test_verify_password_valid(self, mock_col_fn):
        import bcrypt as _bcrypt
        from src.api.admin_routes import _verify_password
        real_hash = _bcrypt.hashpw(b"testpass", _bcrypt.gensalt(rounds=4))
        col = MagicMock()
        col.find_one.return_value = {"type": "admin_password", "password_hash": real_hash.decode('utf-8')}
        mock_col_fn.return_value = col
        assert _verify_password("testpass") is True

    @patch('src.api.admin_routes._get_admin_collection')
    def test_verify_password_invalid(self, mock_col_fn):
        import bcrypt as _bcrypt
        from src.api.admin_routes import _verify_password
        real_hash = _bcrypt.hashpw(b"testpass", _bcrypt.gensalt(rounds=4))
        col = MagicMock()
        col.find_one.return_value = {"type": "admin_password", "password_hash": real_hash.decode('utf-8')}
        mock_col_fn.return_value = col
        assert _verify_password("wrongpass") is False


# ==================== discipline_classifier classify_all_users ====================

class TestClassifyAllUsers:
    def test_classify_all_users_empty_graph(self):
        import networkx as nx
        from src.analysis.discipline_classifier import classify_all_users
        G = nx.Graph()
        users_col = MagicMock()
        repos_col = MagicMock()
        node_disciplines, analysis = classify_all_users(G, users_col, repos_col)
        assert node_disciplines == {}
        assert analysis["total_classified"] == 0

    def test_classify_all_users_with_users(self):
        import networkx as nx
        from src.analysis.discipline_classifier import classify_all_users
        G = nx.Graph()
        G.add_node("user_alice", type="user", is_bot=False)
        G.add_node("repo_org/quantum-sim", type="repo")
        G.add_edge("user_alice", "repo_org/quantum-sim", type="contributed_to")

        users_col = MagicMock()
        users_col.find.return_value = iter([
            {"login": "alice", "bio": "quantum physics researcher",
             "top_languages": ["Python", "C++"], "quantum_expertise_score": 80}
        ])
        repos_col = MagicMock()
        repos_col.find.return_value = iter([
            {"full_name": "org/quantum-sim", "repository_topics": ["quantum", "simulation"],
             "primary_language": "Python", "description": "Quantum simulation tool"}
        ])

        node_disciplines, analysis = classify_all_users(G, users_col, repos_col)
        assert "user_alice" in node_disciplines
        assert analysis["total_classified"] == 1
        assert "distribution" in analysis
        assert "mixing_matrix" in analysis

    def test_classify_all_users_multi_discipline(self):
        import networkx as nx
        from src.analysis.discipline_classifier import classify_all_users
        G = nx.Graph()
        G.add_node("user_alice", type="user", is_bot=False)
        G.add_node("user_bob", type="user", is_bot=False)
        G.add_node("repo_org/repo1", type="repo")
        G.add_edge("user_alice", "repo_org/repo1", type="contributed_to")
        G.add_edge("user_bob", "repo_org/repo1", type="contributed_to")

        users_col = MagicMock()
        users_col.find.return_value = iter([
            {"login": "alice", "bio": "quantum physics", "top_languages": ["Python"]},
            {"login": "bob", "bio": "machine learning engineer", "top_languages": ["Python"]},
        ])
        repos_col = MagicMock()
        repos_col.find.return_value = iter([
            {"full_name": "org/repo1", "repository_topics": ["quantum", "ml"],
             "primary_language": "Python", "description": "hybrid"}
        ])

        node_disciplines, analysis = classify_all_users(G, users_col, repos_col)
        assert analysis["total_classified"] == 2
        assert "cross_discipline_index" in analysis
