"""Anthropic Claude LLM Provider."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx
import structlog

from suho_agent.models.base import LLMProvider, LLMResponse, ModelInfo, ToolCallResponse

log = structlog.get_logger(__name__)


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider using direct Messages API."""

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-20241022",
        api_key: Optional[str] = None,
        timeout: int = 120,
        temperature: float = 0.1,
    ) -> None:
        self.model = model
        self.api_key = api_key or ""
        self.timeout = timeout
        self.temperature = temperature
        self._client = httpx.AsyncClient(timeout=timeout)

    async def generate(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        system, formatted = self._format_messages(messages)
        payload = {
            "model": self.model,
            "messages": formatted,
            "max_tokens": max_tokens or 4096,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            resp = await self._client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            text_content = ""
            for c in data.get("content", []):
                if c.get("type") == "text":
                    text_content += c.get("text", "")

            usage = data.get("usage", {})
            return LLMResponse(
                content=text_content,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                finish_reason=data.get("stop_reason"),
            )
        except Exception as e:
            log.error("Anthropic generate error", error=str(e))
            raise

    async def stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        system, formatted = self._format_messages(messages)
        payload = {
            "model": self.model,
            "messages": formatted,
            "max_tokens": 4096,
            "temperature": temperature,
            "stream": True,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with self._client.stream("POST", "https://api.anthropic.com/v1/messages", json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    line_data = line[6:].strip()
                    try:
                        obj = json.loads(line_data)
                        if obj.get("type") == "content_block_delta":
                            delta = obj.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield delta.get("text", "")
                    except Exception:
                        continue

    async def tool_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.1,
    ) -> Optional[ToolCallResponse]:
        # Convert tools to Anthropic tool schema
        anthropic_tools = [
            {
                "name": t.get("name"),
                "description": t.get("description"),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]

        system, formatted = self._format_messages(messages)
        payload = {
            "model": self.model,
            "messages": formatted,
            "tools": anthropic_tools,
            "max_tokens": 4096,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            resp = await self._client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error("Anthropic tool call error", error=str(e))
            raise

        text_content = ""
        tool_call_obj = None

        for c in data.get("content", []):
            if c.get("type") == "text":
                text_content += c.get("text", "")
            elif c.get("type") == "tool_use":
                tool_call_obj = c

        usage = data.get("usage", {})

        if tool_call_obj:
            return ToolCallResponse(
                tool=tool_call_obj.get("name", ""),
                args=tool_call_obj.get("input", {}),
                content=text_content,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        if text_content and any(kw in text_content.lower() for kw in ["task complete", "finished", "done"]):
            return ToolCallResponse(
                tool="__complete__",
                args={},
                content=text_content,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        return None

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    async def health_check(self) -> bool:
        return bool(self.api_key)

    async def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(name="claude-3-5-sonnet-20241022", provider="anthropic", available=True),
            ModelInfo(name="claude-3-5-haiku-20241022", provider="anthropic", available=True),
            ModelInfo(name="claude-3-opus-20240229", provider="anthropic", available=True),
        ]

    def _format_messages(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict]]:
        system = ""
        formatted = []
        for m in messages:
            role = m.get("role")
            content = m.get("content", "")
            if role == "system":
                system += content + "\n"
            elif role in ("user", "assistant"):
                formatted.append({"role": role, "content": content})
        return system.strip(), formatted
