"""
Cliente batched para Azure AI Foundry Embeddings.

Diseño:
  - Reutiliza la misma autenticación que el agente principal
    (DefaultAzureCredential + token caching) para no duplicar lógica.
  - Bucket por lotes: por defecto 64 textos por llamada (límite
    razonable de Azure OpenAI sin descompensar tokens/segundo).
  - Retries exponenciales con jitter en 429 y 5xx.
  - Devuelve embeddings en el mismo orden de entrada.

Modelo objetivo: ``text-embedding-3-small`` (1536 dim, ~$0.02/M tokens,
desplegado en ``entangle-ai-resource`` Sweden Central).
"""

from __future__ import annotations

import random
import threading
import time
from typing import List, Optional

import requests

from ..core.config import config
from ..core.logger import logger
from .providers import get_ai_provider


_DEFAULT_BATCH_SIZE = 64
_MAX_RETRIES = 3
_BASE_BACKOFF_S = 2.0
_REQUEST_TIMEOUT_S = 60

# Token cache compartido con agent.py (cada módulo tiene el suyo para
# evitar acoplamiento, pero la rotación interna del SDK ya cachea)
_credential: Optional[object] = None
_credential_lock = threading.Lock()


def _get_credential() -> object:
    global _credential
    with _credential_lock:
        if _credential is None:
            provider = get_ai_provider()
            _credential = (
                provider._credential()
            )  # Azure provider only; local tests patch this seam.
        return _credential


def _auth_headers() -> dict:
    """Authentication for the explicitly selected provider."""
    if config.AI_PROVIDER == "azure-openai":
        if config.AZURE_AI_API_KEY and config.ENVIRONMENT != "production":
            return {
                "Content-Type": "application/json",
                "api-key": config.AZURE_AI_API_KEY,
            }
        token = _get_credential().get_token(
            "https://cognitiveservices.azure.com/.default"
        )
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token.token}",
        }
    return get_ai_provider().headers()


def _embedding_url(deployment: str) -> str:
    return get_ai_provider().embedding_url(deployment)


def _call_with_retry(url: str, payload: dict) -> dict:
    last_error: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                url, headers=_auth_headers(), json=payload, timeout=_REQUEST_TIMEOUT_S
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                wait = (
                    float(retry_after)
                    if retry_after
                    else _BASE_BACKOFF_S * (2**attempt)
                )
                wait += random.uniform(0, 1.5)  # jitter
                wait = min(wait, 30.0)
                logger.warning(
                    "Embeddings HTTP %s — reintento %d/%d en %.1fs",
                    resp.status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                    wait,
                )
                time.sleep(wait)
                last_error = requests.HTTPError(f"{resp.status_code}", response=resp)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_error = e
            if attempt < _MAX_RETRIES:
                wait = _BASE_BACKOFF_S * (2**attempt)
                time.sleep(wait)
                continue
            raise

    raise RuntimeError(f"Embeddings agotó reintentos: {last_error!r}")


def embed_texts(
    texts: List[str],
    *,
    deployment: str = "text-embedding-3-small",
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> List[List[float]]:
    """Devuelve embeddings de cada texto, preservando el orden.

    Args:
        texts: lista de strings (no vacía).
        deployment: nombre del deployment en Azure AI Foundry.
        batch_size: ítems por petición HTTP.

    Returns:
        ``len(texts)`` vectores de 1536 floats.
    """
    if not texts:
        return []
    provider = get_ai_provider()
    if not config.EMBEDDINGS_ENABLED:
        raise RuntimeError("Embeddings deshabilitados explícitamente por configuración")
    if config.AI_PROVIDER == "bedrock":
        return provider.embed(texts, deployment)  # type: ignore[attr-defined]
    if config.AI_PROVIDER in {"offline", "disabled"}:
        raise RuntimeError(
            "Embeddings no disponibles con el proveedor de IA seleccionado"
        )
    if config.AI_PROVIDER == "azure-openai" and not config.AZURE_AI_ENDPOINT:
        raise RuntimeError("AZURE_AI_ENDPOINT no está configurado")

    url = _embedding_url(deployment)
    out: List[List[float]] = []
    total_tokens = 0
    t0 = time.time()

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        payload = {"input": batch, "model": config.AI_EMBEDDING_MODEL or deployment}
        data = _call_with_retry(url, payload)

        # Azure devuelve `data` ordenado por `index` ascendente.
        items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        for item in items:
            out.append(item["embedding"])
        total_tokens += data.get("usage", {}).get("total_tokens", 0)

    elapsed = time.time() - t0
    logger.info(
        "🧠 embed_texts: %d textos, %d tokens, %.1fs (%.0f t/s)",
        len(texts),
        total_tokens,
        elapsed,
        total_tokens / max(elapsed, 0.001),
    )
    return out


def embed_one(text: str, *, deployment: str = "text-embedding-3-small") -> List[float]:
    """Atajo para embedding de un solo texto (queries del agente)."""
    return embed_texts([text], deployment=deployment, batch_size=1)[0]
