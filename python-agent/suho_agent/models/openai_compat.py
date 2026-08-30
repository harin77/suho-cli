"""OpenAI-compatible LLM Provider — works with OpenAI, LM Studio, vLLM, etc."""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

import structlog
from openai import AsyncOpenAI, APIConnectionError, APIStatusError

from suho_agent.models.base import LLMProvider, LLMResponse, ModelInfo, ToolCallResponse

log = structlog.get_logger(__name__)


class OpenAICompatProvider(LLMProvider):
    """
    OpenAI-compatible API provider.
    Works with:
    - OpenAI API
    - LM Studio
    - vLLM
    - Any OpenAI-compat endpoint
    """

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 120,
        temperature: float = 0.1,
    ) -> None:
        if model == "gemini-2.5-flash":
            model = "gemini-2.0-flash"
        self.model = model
        self.temperature = temperature

        self._client = AsyncOpenAI(
            api_key=api_key or "sk-placeholder",
            base_url=base_url,
            timeout=timeout,
        )

    async def generate(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        try:
            resp = await self._client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                output_tokens=resp.usage.completion_tokens if resp.usage else 0,
                finish_reason=choice.finish_reason,
            )
        except (APIConnectionError, APIStatusError) as e:
            log.error("OpenAI-compat request failed", error=str(e))
            raise

    async def stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    async def tool_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.1,
    ) -> Optional[ToolCallResponse]:
        # Convert tool schemas to OpenAI function format
        openai_tools = [
            {"type": "function", "function": t}
            for t in tools
        ]

        resp = None
        for attempt in range(3):
            try:
                resp = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                    temperature=temperature,
                )
                break
            except Exception as e:
                err_str = str(e)
                if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower()) and attempt < 2:
                    log.warning("Rate limit / quota hit, waiting 6s before retry...", attempt=attempt + 1, error=err_str[:150])
                    import asyncio
                    await asyncio.sleep(6.0 * (attempt + 1))
                else:
                    log.error("Tool call failed", error=err_str)
                    raise

        choice = resp.choices[0]
        message = choice.message

        reasoning = getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None)
        raw_content = message.content or ""
        if not reasoning and "<think>" in raw_content:
            import re
            m = re.search(r"<think>(.*?)</think>", raw_content, re.DOTALL)
            if m:
                reasoning = m.group(1).strip()

        if message.tool_calls:
            tc = message.tool_calls[0]
            import json
            args = {}
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                pass

            return ToolCallResponse(
                tool=tc.function.name,
                args=args,
                content=message.content,
                reasoning=reasoning,
                input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            )

        # No tool call — task complete or conversational text
        if message.content:
            content_strip = message.content.strip()
            if "<task_complete>" in content_strip or "[TASK_COMPLETE]" in content_strip or '{"tool": "__complete__"' in content_strip:
                return ToolCallResponse(
                    tool="__complete__",
                    args={},
                    content=message.content,
                    reasoning=reasoning,
                    input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                    output_tokens=resp.usage.completion_tokens if resp.usage else 0,
                )

            return ToolCallResponse(
                tool="",
                args={},
                content=message.content,
                reasoning=reasoning,
                input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            )

        return None

    def count_tokens(self, text: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(self.model)
            return len(enc.encode(text))
        except Exception:
            return len(text) // 4  # fallback estimate

    async def health_check(self) -> bool:
        if self._client.api_key and self._client.api_key != "sk-placeholder":
            return True
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False

    async def list_models(self) -> list[ModelInfo]:
        base_url_str = str(self._client.base_url)
        if "generativelanguage.googleapis.com" in base_url_str:
            import httpx
            api_key = self._client.api_key
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    r = await client.get(url)
                    if r.status_code == 200:
                        data = r.json()
                        models = []
                        deprecated = {"gemini-2.5-flash", "gemini-2.5-flash-preview-tts"}
                        for m in data.get("models", []):
                            raw_name = m.get("name", "").replace("models/", "")
                            if raw_name and raw_name not in deprecated and "embed" not in raw_name and "bison" not in raw_name and "imagen" not in raw_name:
                                models.append(ModelInfo(name=raw_name, provider="gemini", available=True))
                        if models:
                            return models
            except Exception as e:
                log.warning("Failed to fetch live Gemini models from Google API", error=str(e))

        try:
            import asyncio
            resp = await asyncio.wait_for(self._client.models.list(), timeout=6.0)
            return [
                ModelInfo(name=m.id, provider="openai_compat", available=True)
                for m in resp.data
            ]
        except Exception as e:
            log.warning("Failed to list models via API endpoint, returning configured model", error=str(e))
            return [ModelInfo(name=self.model, provider="openai_compat", available=True)]
