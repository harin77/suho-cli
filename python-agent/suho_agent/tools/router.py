"""ToolRouter — registry of all available tools."""

from __future__ import annotations

from typing import Any, Optional

import structlog

from suho_agent.tools.base import Tool, ToolInfo

log = structlog.get_logger(__name__)


class ToolRouter:
    """
    Registry and dispatcher for all tools.

    Separation axiom:
      ToolRouter knows WHICH tools exist.
      It does NOT decide IF they can run (PolicyEngine + SecurityGate do that).
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """Register all built-in tools."""
        from suho_agent.tools.filesystem import (
            ReadFileTool, WriteFileTool, EditFileTool, CreateFileTool,
            DeleteFileTool, ListDirectoryTool, SearchFilesTool, FindFilesTool,
            MoveFileTool, CopyFileTool,
        )
        from suho_agent.tools.terminal import ExecuteCommandTool
        from suho_agent.tools.git import (
            GitStatusTool, GitDiffTool, GitLogTool, GitBranchTool,
            GitAddTool, GitCommitTool, GitPullTool, GitPushTool,
            GitCheckoutTool,
        )
        from suho_agent.tools.system import (
            SystemInfoTool, DiskUsageTool, MemoryUsageTool,
            ProcessListTool, NetworkInfoTool,
        )
        from suho_agent.tools.development import (
            FlutterAnalyzeTool, FlutterTestTool, FlutterBuildTool,
            CargoCheckTool, CargoTestTool, CargoBuildTool, CargoClippyTool,
            PytestRunTool, PipInstallTool, PythonRunTool,
            NpmInstallTool, NpmRunTool, NpmTestTool,
        )

        all_tools: list[Tool] = [
            # Filesystem
            ReadFileTool(), WriteFileTool(), EditFileTool(), CreateFileTool(),
            DeleteFileTool(), ListDirectoryTool(), SearchFilesTool(), FindFilesTool(),
            MoveFileTool(), CopyFileTool(),
            # Terminal
            ExecuteCommandTool(),
            # Git
            GitStatusTool(), GitDiffTool(), GitLogTool(), GitBranchTool(),
            GitAddTool(), GitCommitTool(), GitPullTool(), GitPushTool(),
            GitCheckoutTool(),
            # System
            SystemInfoTool(), DiskUsageTool(), MemoryUsageTool(),
            ProcessListTool(), NetworkInfoTool(),
            # Development
            FlutterAnalyzeTool(), FlutterTestTool(), FlutterBuildTool(),
            CargoCheckTool(), CargoTestTool(), CargoBuildTool(), CargoClippyTool(),
            PytestRunTool(), PipInstallTool(), PythonRunTool(),
            NpmInstallTool(), NpmRunTool(), NpmTestTool(),
        ]

        for tool in all_tools:
            self._tools[tool.name] = tool

        log.debug("Tools registered", count=len(self._tools))

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return all tools in OpenAI function-calling format."""
        return [t.to_llm_schema() for t in self._tools.values()]

    def get_available_schemas(self) -> list[dict[str, Any]]:
        """Return only available tools in LLM format."""
        schemas = []
        for tool in self._tools.values():
            available, _ = tool.is_available()
            if available:
                schemas.append(tool.to_llm_schema())
        return schemas

    async def list_tools(
        self, verbose: bool = False, category: Optional[str] = None
    ) -> list[ToolInfo]:
        """List all tools with availability status."""
        tools = []
        for tool in self._tools.values():
            info = tool.to_tool_info()
            if category and info.category.lower() != category.lower():
                continue
            tools.append(info)
        return sorted(tools, key=lambda t: (t.category, t.name))

    def check_available(self, name: str) -> tuple[bool, Optional[str]]:
        tool = self._tools.get(name)
        if not tool:
            return False, f"Tool '{name}' not found"
        return tool.is_available()
