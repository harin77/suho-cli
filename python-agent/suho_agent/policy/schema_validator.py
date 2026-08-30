"""Layer 1: Schema Validator — args match tool parameter schema."""

from __future__ import annotations

from typing import Any


class SchemaValidator:
    """Validates tool arguments against expected schema."""

    # Minimal required args per tool (expandable)
    REQUIRED_ARGS: dict[str, list[str]] = {
        "terminal.execute": ["command"],
        "terminal.execute_command": ["command"],
        "filesystem.read_file": ["path"],
        "filesystem.write_file": ["path", "content"],
        "filesystem.create_file": ["path", "content"],
        "filesystem.delete_file": ["path"],
        "filesystem.list_directory": ["path"],
        "filesystem.edit_file": ["path", "diff"],
        "filesystem.search_files": ["path", "pattern"],
        "git.commit": ["message"],
        "git.push": [],
        "git.reset_hard": ["ref"],
    }

    MAX_COMMAND_LENGTH = 4096
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB

    def validate(self, tool: str, args: dict[str, Any]) -> tuple[bool, str | None]:
        """Returns (valid, error_message)."""
        if not isinstance(args, dict):
            return False, "args must be a dict"

        # Check required args
        required = self.REQUIRED_ARGS.get(tool, [])
        for req in required:
            if req not in args:
                return False, f"Missing required arg '{req}' for tool '{tool}'"
            if args[req] is None or args[req] == "":
                return False, f"Arg '{req}' must not be empty"

        # Validate command length
        if "command" in args:
            cmd = args["command"]
            if not isinstance(cmd, str):
                return False, "'command' must be a string"
            if len(cmd) > self.MAX_COMMAND_LENGTH:
                return False, f"Command too long: {len(cmd)} chars (max {self.MAX_COMMAND_LENGTH})"

        # Validate content length
        if "content" in args:
            content = args["content"]
            if not isinstance(content, str):
                return False, "'content' must be a string"
            if len(content) > self.MAX_CONTENT_LENGTH:
                return False, f"Content too large: {len(content)} bytes"

        # Validate path format
        if "path" in args:
            path = args["path"]
            if not isinstance(path, str):
                return False, "'path' must be a string"

        return True, None
