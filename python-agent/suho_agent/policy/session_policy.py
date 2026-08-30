"""Layer 5: Session Policy — session-level allow/deny rules."""

from __future__ import annotations


_LEVEL_ORDER = {"SAFE": 0, "MODERATE": 1, "DANGEROUS": 2, "CRITICAL": 3}


class SessionPolicy:
    """
    Layer 5: Session-level policy.
    Manages tool-level allow/deny decisions that persist within a session.
    These are set by the user during permission prompts.
    """

    def __init__(self) -> None:
        self._allowed_tools: set[str] = set()
        self._denied_tools: set[str] = set()
        self._max_auto_level: str = "MODERATE"  # auto-allow up to this level

    def allow_tool(self, tool: str) -> None:
        """Grant session-level permission for a tool."""
        self._allowed_tools.add(tool)
        self._denied_tools.discard(tool)

    def deny_tool(self, tool: str) -> None:
        """Session-level deny for a tool."""
        self._denied_tools.add(tool)
        self._allowed_tools.discard(tool)

    def check(self, tool: str, level: str) -> tuple[bool, str | None]:
        """Returns (allowed, reason)."""
        if tool in self._denied_tools:
            return False, f"Tool '{tool}' was denied for this session"

        if tool in self._allowed_tools:
            return True, None

        # Auto-allow if within configured threshold
        if _LEVEL_ORDER.get(level, 0) <= _LEVEL_ORDER.get(self._max_auto_level, 1):
            return True, None

        # Needs explicit permission (Rust SecurityGate will prompt)
        return True, None  # not blocking — Rust gate handles the prompt

    def set_max_auto_level(self, level: str) -> None:
        """Set the maximum level that is auto-allowed without prompting."""
        self._max_auto_level = level
