"""Terminal tool — execute shell commands."""

from __future__ import annotations

from suho_agent.tools.base import Tool


class ExecuteCommandTool(Tool):
    name = "terminal.execute"
    description = (
        "Execute a shell command. Output is captured and returned. "
        "Use for running builds, tests, analysis tools, etc. "
        "Dangerous commands require user approval."
    )
    category = "terminal"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory (default: task working directory)",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30)",
                "default": 30,
            },
            "env": {
                "type": "object",
                "description": "Additional environment variables",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["command"],
    }
