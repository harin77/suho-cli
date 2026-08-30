"""LLM Provider abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel


class LLMResponse(BaseModel):
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: Optional[str] = None


class ToolCallResponse(BaseModel):
    tool: str
    args: dict[str, Any]
    content: Optional[str] = None  # any text alongside the tool call
    reasoning: Optional[str] = None  # thinking/reasoning model output
    input_tokens: int = 0
    output_tokens: int = 0


class ModelInfo(BaseModel):
    name: str
    provider: str
    available: bool = True
    context_length: Optional[int] = None


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Generate a response without tool use."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.1,
    ) -> AsyncIterator[str]:
        """Stream a response token by token."""
        ...

    @abstractmethod
    async def tool_call(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.1,
    ) -> Optional[ToolCallResponse]:
        """
        Generate a response with tool use.
        Returns None if the model decides no tool is needed (task complete).
        """
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Estimate token count for a string."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable."""
        ...

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """List available models from this provider."""
        ...
