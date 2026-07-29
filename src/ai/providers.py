"""Provider-neutral AI transport adapters.

The application continues to use the OpenAI chat-completions contract internally.
Each adapter maps that contract to a configured provider; no provider is guessed
from reachable endpoints or ambient credentials.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

from ..core.config import config
from ..core.snapshot import load_offline_replies

_AZURE_SCOPE = "https://cognitiveservices.azure.com/.default"


class AIProvider:
    http_transport = True

    def headers(self) -> Dict[str, str]:
        raise NotImplementedError

    def chat_url(self) -> str:
        raise NotImplementedError

    def embedding_url(self, deployment: str) -> str:
        raise NotImplementedError

    def prepare_chat_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return payload


class AzureOpenAIProvider(AIProvider):
    def _credential(self):
        # Azure Container Apps receives a dedicated user-assigned identity ID.
        # DefaultAzureCredential remains restricted to local development.
        if config.AZURE_MANAGED_IDENTITY_CLIENT_ID:
            return ManagedIdentityCredential(
                client_id=config.AZURE_MANAGED_IDENTITY_CLIENT_ID
            )
        return DefaultAzureCredential()

    def headers(self) -> Dict[str, str]:
        if config.AZURE_AI_API_KEY and config.ENVIRONMENT != "production":
            return {
                "Content-Type": "application/json",
                "api-key": config.AZURE_AI_API_KEY,
            }
        token = self._credential().get_token(_AZURE_SCOPE)
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token.token}",
        }

    def chat_url(self) -> str:
        return (
            f"{config.AZURE_AI_ENDPOINT.rstrip('/')}/openai/deployments/"
            f"{config.AZURE_AI_DEPLOYMENT}/chat/completions?api-version=2024-12-01-preview"
        )

    def embedding_url(self, deployment: str) -> str:
        return (
            f"{config.AZURE_AI_ENDPOINT.rstrip('/')}/openai/deployments/{deployment}"
            "/embeddings?api-version=2024-02-01"
        )


class OpenAICompatibleProvider(AIProvider):
    def _base_url(self) -> str:
        if not config.AI_BASE_URL:
            raise RuntimeError("AI_BASE_URL es obligatorio para openai-compatible")
        return config.AI_BASE_URL.rstrip("/")

    def headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if config.AI_API_KEY:
            headers["Authorization"] = f"Bearer {config.AI_API_KEY}"
        return headers

    def chat_url(self) -> str:
        return f"{self._base_url()}/v1/chat/completions"

    def embedding_url(self, deployment: str) -> str:
        return f"{self._base_url()}/v1/embeddings"

    def prepare_chat_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # OpenAI-compatible servers require their model in the request and
        # must not receive Azure GPT-5-only fields.
        prepared = dict(payload)
        prepared["model"] = config.AI_MODEL
        prepared.pop("reasoning_effort", None)
        prepared.pop("max_completion_tokens", None)
        return prepared


class BedrockProvider(AIProvider):
    """AWS Bedrock Converse adapter, imported only when explicitly selected."""

    http_transport = False

    def headers(self) -> Dict[str, str]:
        return {}

    def chat_url(self) -> str:
        return "bedrock://converse"

    def embedding_url(self, deployment: str) -> str:
        return "bedrock://embed"

    @staticmethod
    def _message(message: Dict[str, Any]) -> Dict[str, Any]:
        role = message.get("role")
        if role == "tool":
            return {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": message["tool_call_id"],
                            "content": [{"text": str(message.get("content", ""))}],
                        }
                    }
                ],
            }
        if role == "assistant" and message.get("tool_calls"):
            return {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": call["id"],
                            "name": call["function"]["name"],
                            "input": json.loads(
                                call["function"].get("arguments") or "{}"
                            ),
                        }
                    }
                    for call in message["tool_calls"]
                ],
            }
        content = message.get("content") or ""
        return {
            "role": "assistant" if role == "assistant" else "user",
            "content": (
                content if isinstance(content, list) else [{"text": str(content)}]
            ),
        }

    @staticmethod
    def _tool_config(payload: Dict[str, Any]) -> Dict[str, Any] | None:
        tools = payload.get("tools") or []
        if not tools or payload.get("tool_choice") == "none":
            return None
        tool_config: Dict[str, Any] = {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool["function"]["name"],
                        "description": tool["function"].get("description", ""),
                        "inputSchema": {"json": tool["function"].get("parameters", {})},
                    }
                }
                for tool in tools
            ],
        }
        choice = payload.get("tool_choice", "auto")
        if choice == "auto":
            tool_config["toolChoice"] = {"auto": {}}
        elif choice == "required":
            tool_config["toolChoice"] = {"any": {}}
        elif isinstance(choice, dict) and choice.get("function", {}).get("name"):
            tool_config["toolChoice"] = {"tool": {"name": choice["function"]["name"]}}
        return tool_config

    def complete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        import boto3

        model = config.AI_MODEL
        client = boto3.client("bedrock-runtime", region_name=config.AWS_REGION or None)
        system = [
            {"text": str(item.get("content", ""))}
            for item in payload.get("messages", [])
            if item.get("role") == "system"
        ]
        messages = []
        source_messages = [item for item in payload.get("messages", []) if item.get("role") != "system"]
        index = 0
        while index < len(source_messages):
            item = source_messages[index]
            if item.get("role") == "tool":
                results = []
                while index < len(source_messages) and source_messages[index].get("role") == "tool":
                    results.extend(self._message(source_messages[index])["content"])
                    index += 1
                messages.append({"role": "user", "content": results})
                continue
            messages.append(self._message(item))
            index += 1
        request: Dict[str, Any] = {"modelId": model, "messages": messages}
        if system:
            request["system"] = system
        tool_config = self._tool_config(payload)
        if tool_config:
            request["toolConfig"] = tool_config
        inference: Dict[str, Any] = {}
        if payload.get("temperature") is not None:
            inference["temperature"] = payload["temperature"]
        if payload.get("max_tokens") is not None:
            inference["maxTokens"] = payload["max_tokens"]
        if inference:
            request["inferenceConfig"] = inference
        response = client.converse(**request)
        content = response.get("output", {}).get("message", {}).get("content", [])
        text = "".join(item.get("text", "") for item in content)
        tool_calls = [
            {
                "id": item["toolUse"]["toolUseId"],
                "type": "function",
                "function": {
                    "name": item["toolUse"]["name"],
                    "arguments": json.dumps(item["toolUse"].get("input", {})),
                },
            }
            for item in content
            if item.get("toolUse")
        ]
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": text,
                        "tool_calls": tool_calls or None,
                    },
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
            ]
        }

    def embed(self, texts: list[str], deployment: str) -> list[list[float]]:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=config.AWS_REGION or None)
        model = config.AI_EMBEDDING_MODEL
        if not model:
            raise RuntimeError(
                "AI_EMBEDDING_MODEL es obligatorio para embeddings de Bedrock"
            )
        vectors = []
        for text in texts:
            response = client.invoke_model(
                modelId=model,
                body=('{"inputText": ' + __import__("json").dumps(text) + "}").encode(
                    "utf-8"
                ),
                contentType="application/json",
                accept="application/json",
            )
            vectors.append(
                __import__("json").loads(response["body"].read()).get("embedding", [])
            )
        return vectors


class OfflineProvider(AIProvider):
    http_transport = False

    def headers(self) -> Dict[str, str]:
        return {}

    def chat_url(self) -> str:
        return "offline://snapshot"

    def embedding_url(self, deployment: str) -> str:
        return "offline://snapshot"

    def complete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        replies = load_offline_replies(config.SNAPSHOT_PATH)
        message = next(
            (
                str(item.get("content", ""))
                for item in reversed(payload.get("messages", []))
                if item.get("role") == "user"
            ),
            "",
        )
        answer = replies.get(
            message.strip().lower(),
            "This is a deterministic offline Entangle snapshot. No live AI, GitHub, or web research was used.",
        )
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ]
        }


class DisabledProvider(OfflineProvider):
    def complete(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError("El proveedor de IA está deshabilitado explícitamente")


def get_ai_provider() -> AIProvider:
    providers = {
        "azure-openai": AzureOpenAIProvider,
        "openai-compatible": OpenAICompatibleProvider,
        "bedrock": BedrockProvider,
        "offline": OfflineProvider,
        "disabled": DisabledProvider,
    }
    try:
        return providers[config.AI_PROVIDER]()
    except KeyError as exc:
        raise RuntimeError(
            f"Proveedor de IA no compatible: {config.AI_PROVIDER}"
        ) from exc
