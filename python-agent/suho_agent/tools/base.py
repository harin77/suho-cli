"""Tool base classes — Tool ABC and ToolResult model.

IMPORTANT: Python tools do NOT execute anything directly.
They build a ToolRequest that is sent to Rust for execution.
Actual execution happens in Rust SecurityGate → Executor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Structured result from tool execution (received from Rust)."""
    success: bool
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    secrets_redacted: int = 0
    data: Optional[Any] = None  # structured data for non-command tools


class ToolInfo(BaseModel):
    """Tool metadata for listing/discovery."""
    name: str
    description: str
    category: str
    permission_level: str  # SAFE / MODERATE / DANGEROUS / CRITICAL
    available: bool = True
    unavailable_reason: Optional[str] = None
    parameters: dict[str, Any] = {}


class Tool(ABC):
    """Abstract base class for all tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name (e.g. 'filesystem.read_file')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for LLM."""
        ...

    @property
    @abstractmethod
    def category(self) -> str:
        """Category (filesystem, terminal, git, etc.)."""
        ...

    @property
    @abstractmethod
    def permission_level(self) -> str:
        """Default permission level (SAFE/MODERATE/DANGEROUS/CRITICAL)."""
        ...

    @property
    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema for the tool's parameters (OpenAI function format)."""
        ...

    def is_available(self) -> tuple[bool, Optional[str]]:
        """Return (available, reason_if_not)."""
        return True, None

    def to_llm_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format for LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }

    def to_tool_info(self) -> ToolInfo:
        available, reason = self.is_available()
        return ToolInfo(
            name=self.name,
            description=self.description,
            category=self.category,
            permission_level=self.permission_level,
            available=available,
            unavailable_reason=reason,
            parameters=self.parameters_schema,
        )
