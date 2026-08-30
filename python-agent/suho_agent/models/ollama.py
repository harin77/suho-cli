"""Ollama LLM Provider — connects to local Ollama server."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx
import structlog

from suho_agent.models.base import LLMProvider, LLMResponse, ModelInfo, ToolCallResponse

log = structlog.get_logger(__name__)

# Sentinel: marks end of streaming
_DONE_SENTINEL = "[DONE]"


class OllamaProvider(LLMProvider):
    """
    Ollama LLM provider.
    Supports Ollama's /api/chat endpoint with optional tool use (function calling).
    """

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        timeout: int = 120,
        temperature: float = 0.1,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature
        self._client = httpx.AsyncClient(timeout=timeout)

    async def generate(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        try:
            resp = await self._client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

            return LLMResponse(
                content=data.get("message", {}).get("content", ""),
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
                finish_reason=data.get("done_reason"),
            )
        except httpx.HTTPError as e:
            log.error("Ollama request failed", error=str(e))
            raise

    async def stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature},
        }

        async with self._client.stream("POST", f"{self.base_url}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue

    async def tool_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.1,
    ) -> Optional[ToolCallResponse]:
        """
        Use Ollama's tool/function calling support.
        Falls back to JSON parsing from plain text if tools not supported by model.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "tools": tools,
            "options": {"temperature": temperature},
        }

        try:
            resp = await self._client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            log.error("Ollama tool call failed", error=str(e))
            raise

        message = data.get("message", {})
        tool_calls = message.get("tool_calls", [])

        if tool_calls:
            tc = tool_calls[0]
            return ToolCallResponse(
                tool=tc.get("function", {}).get("name", ""),
                args=tc.get("function", {}).get("arguments", {}),
                content=message.get("content"),
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            )

        # Fallback: try parsing JSON from response content
        content = message.get("content", "")
        if content:
            return self._parse_tool_from_text(
                content,
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
            )

        return None

    def _parse_tool_from_text(
        self, text: str, input_tokens: int = 0, output_tokens: int = 0
    ) -> Optional[ToolCallResponse]:
        """Attempt to extract a tool call from free-form text (JSON block)."""
        import re

        # Try ```json ... ``` blocks
        pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        matches = re.findall(pattern, text, re.DOTALL)
        for match in matches:
            try:
                data = json.loads(match)
                if "tool" in data and "args" in data:
                    return ToolCallResponse(
                        tool=data["tool"],
                        args=data["args"],
                        content=text,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )
            except json.JSONDecodeError:
                continue

        # Check for "complete" signal
        if any(kw in text.lower() for kw in ["task complete", "task is complete", "i'm done", "finished"]):
            return ToolCallResponse(
                tool="__complete__",
                args={},
                content=text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        return None

    def count_tokens(self, text: str) -> int:
        """Estimate token count (rough: 4 chars ≈ 1 token)."""
        return len(text) // 4

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[ModelInfo]:
        try:
            resp = await self._client.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("models", []):
                models.append(ModelInfo(
                    name=m.get("name", ""),
                    provider="ollama",
                    available=True,
                    context_length=None,
                ))
            return models
        except Exception as e:
            log.warning("Failed to list Ollama models", error=str(e))
            return []

    async def __aenter__(self) -> "OllamaProvider":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()
