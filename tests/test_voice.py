"""Tests de la capa de voz (ElevenLabs): módulo ``src.ai.voice`` y rutas
``/api/v1/voice/*``. Todas las llamadas HTTP a ElevenLabs están mockeadas,
así que no consumen créditos ni requieren API key."""
import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.api.main import app
from src.ai import voice


@pytest.fixture
def client():
    # Sin ``with``: no dispara el lifespan (ni DB ni GitHub), igual que el
    # resto de tests de la API.
    return TestClient(app)


class TestVoiceModule:
    def test_is_configured_false(self, monkeypatch):
        monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "")
        assert voice.is_configured() is False

    def test_is_configured_true(self, monkeypatch):
        monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "sk-test")
        assert voice.is_configured() is True

    def test_tts_raises_without_key(self, monkeypatch):
        monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "")
        with pytest.raises(voice.VoiceError):
            voice.text_to_speech("hola")

    def test_tts_raises_on_empty_text(self, monkeypatch):
        monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "sk-test")
        with pytest.raises(voice.VoiceError):
            voice.text_to_speech("   ")

    def test_tts_calls_api(self, monkeypatch):
        monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "sk-test")
        monkeypatch.setattr(voice.config, "ELEVENLABS_VOICE_ID", "voice-123")
        mock_resp = MagicMock()
        mock_resp.content = b"MP3DATA"
        mock_resp.raise_for_status = MagicMock()
        with patch("src.ai.voice.requests.post", return_value=mock_resp) as mock_post:
            out = voice.text_to_speech("hola mundo")
        assert out == b"MP3DATA"
        assert mock_post.called
        assert "voice-123" in mock_post.call_args[0][0]

    def test_stt_calls_api(self, monkeypatch):
        monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "sk-test")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"text": "hola"}
        mock_resp.raise_for_status = MagicMock()
        with patch("src.ai.voice.requests.post", return_value=mock_resp):
            out = voice.speech_to_text(b"audio-bytes")
        assert out == "hola"

    def test_stt_raises_on_empty_audio(self, monkeypatch):
        monkeypatch.setattr(voice.config, "ELEVENLABS_API_KEY", "sk-test")
        with pytest.raises(voice.VoiceError):
            voice.speech_to_text(b"")


class TestVoiceRoutes:
    def test_status(self, client):
        resp = client.get("/api/v1/voice/status")
        assert resp.status_code == 200
        assert "configured" in resp.json()

    def test_tts_503_without_key(self, client):
        with patch("src.api.voice_routes.voice.is_configured", return_value=False):
            resp = client.post("/api/v1/voice/tts", json={"text": "hola"})
        assert resp.status_code == 503

    def test_tts_ok(self, client):
        with patch("src.api.voice_routes.voice.is_configured", return_value=True), \
             patch("src.api.voice_routes.voice.text_to_speech", return_value=b"MP3"):
            resp = client.post("/api/v1/voice/tts", json={"text": "hola"})
        assert resp.status_code == 200
        assert resp.content == b"MP3"
        assert resp.headers["content-type"].startswith("audio/mpeg")

    def test_stt_ok(self, client):
        with patch("src.api.voice_routes.voice.is_configured", return_value=True), \
             patch("src.api.voice_routes.voice.speech_to_text", return_value="hola"):
            resp = client.post(
                "/api/v1/voice/stt",
                files={"file": ("a.webm", b"xxx", "audio/webm")},
            )
        assert resp.status_code == 200
        assert resp.json()["text"] == "hola"
