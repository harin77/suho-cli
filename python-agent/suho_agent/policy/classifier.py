"""Layer 4: Pattern Classifier — SAFE/MODERATE/DANGEROUS/CRITICAL classification."""

from __future__ import annotations

from typing import Any


# Tool-based classification (tool name → level)
TOOL_LEVELS: dict[str, str] = {
    # SAFE — read-only / analysis
    "filesystem.read_file": "SAFE",
    "filesystem.list_directory": "SAFE",
    "filesystem.search_files": "SAFE",
    "filesystem.find_files": "SAFE",
    "git.status": "SAFE",
    "git.diff": "SAFE",
    "git.log": "SAFE",
    "git.branch": "SAFE",
    "system.system_info": "SAFE",
    "system.disk_usage": "SAFE",
    "system.memory_usage": "SAFE",
    "system.process_list": "SAFE",
    "system.network_info": "SAFE",

    # MODERATE — write / create / build
    "filesystem.write_file": "MODERATE",
    "filesystem.create_file": "MODERATE",
    "filesystem.edit_file": "MODERATE",
    "filesystem.move_file": "MODERATE",
    "filesystem.copy_file": "MODERATE",
    "git.add": "MODERATE",
    "git.commit": "MODERATE",
    "git.checkout": "MODERATE",
    "development.pip_install": "MODERATE",
    "development.npm_install": "MODERATE",

    # DANGEROUS — destructive / remote / privileged
    "filesystem.delete_file": "DANGEROUS",
    "filesystem.delete_recursive": "DANGEROUS",
    "git.push": "DANGEROUS",
    "git.pull": "MODERATE",
    "git.reset_hard": "DANGEROUS",
    "git.push_force": "DANGEROUS",
    "development.docker_run": "DANGEROUS",

    # CRITICAL — system-level
    "system.shutdown": "CRITICAL",
    "system.reboot": "CRITICAL",
}

# Command-pattern → level (for terminal.execute)
COMMAND_PATTERNS: list[tuple[str, str]] = [
    # SAFE
    ("ls", "SAFE"),
    ("pwd", "SAFE"),
    ("whoami", "SAFE"),
    ("echo", "SAFE"),
    ("cat ", "SAFE"),
    ("head ", "SAFE"),
    ("tail ", "SAFE"),
    ("grep ", "SAFE"),
    ("find ", "SAFE"),
    ("git status", "SAFE"),
    ("git diff", "SAFE"),
    ("git log", "SAFE"),
    ("git branch", "SAFE"),
    ("flutter analyze", "SAFE"),
    ("flutter doctor", "SAFE"),
    ("cargo check", "SAFE"),
    ("cargo clippy", "SAFE"),
    ("python --version", "SAFE"),
    ("python3 --version", "SAFE"),
    ("node --version", "SAFE"),
    ("which ", "SAFE"),

    # MODERATE
    ("git add", "MODERATE"),
    ("git commit", "MODERATE"),
    ("git checkout", "MODERATE"),
    ("flutter build", "MODERATE"),
    ("flutter test", "MODERATE"),
    ("cargo build", "MODERATE"),
    ("cargo test", "MODERATE"),
    ("npm install", "MODERATE"),
    ("npm run", "MODERATE"),
    ("pip install", "MODERATE"),
    ("pip3 install", "MODERATE"),
    ("docker build", "MODERATE"),
    ("mkdir", "MODERATE"),
    ("cp ", "MODERATE"),
    ("mv ", "MODERATE"),
    ("touch ", "MODERATE"),
    ("chmod ", "MODERATE"),
    ("chown ", "MODERATE"),

    # DANGEROUS
    ("sudo", "DANGEROUS"),
    ("rm -rf", "DANGEROUS"),
    ("rm -Rf", "DANGEROUS"),
    ("git push", "DANGEROUS"),
    ("git reset --hard", "DANGEROUS"),
    ("git push --force", "DANGEROUS"),
    ("docker run", "DANGEROUS"),
    ("docker exec", "DANGEROUS"),
    ("ssh ", "DANGEROUS"),
    ("curl | bash", "DANGEROUS"),
    ("wget -O- | bash", "DANGEROUS"),
    ("curl | sh", "DANGEROUS"),

    # CRITICAL
    ("shutdown", "CRITICAL"),
    ("reboot", "CRITICAL"),
    ("systemctl disable", "CRITICAL"),
    ("mkfs", "CRITICAL"),
    ("fdisk", "CRITICAL"),
    ("dd if=", "CRITICAL"),
    ("wipefs", "CRITICAL"),
]


class PatternClassifier:
    """
    Layer 4: Pattern-based classification.
    Uses tool name and command patterns to classify risk level.
    """

    def classify(self, tool: str, args: dict[str, Any]) -> tuple[str, list[str]]:
        """Returns (level, reasons)."""
        reasons: list[str] = []

        # Tool-based lookup first
        if tool in TOOL_LEVELS:
            return TOOL_LEVELS[tool], [f"Tool '{tool}' classified as {TOOL_LEVELS[tool]}"]

        # For terminal execute: scan command patterns
        if tool in ("terminal.execute", "terminal.execute_command"):
            command = args.get("command", "")
            if isinstance(command, str):
                level, reason = self._classify_command(command)
                reasons.append(reason)
                return level, reasons

        # Default for unknown tools
        return "MODERATE", [f"Unknown tool '{tool}' — defaulting to MODERATE"]

    def _classify_command(self, command: str) -> tuple[str, str]:
        """Match command against pattern table, take highest level."""
        best_level = "SAFE"
        best_pattern = "No specific pattern matched"

        for pattern, level in COMMAND_PATTERNS:
            if pattern in command:
                if self._level_order(level) > self._level_order(best_level):
                    best_level = level
                    best_pattern = f"Pattern matched: '{pattern}'"

        return best_level, best_pattern

    @staticmethod
    def _level_order(level: str) -> int:
        return {"SAFE": 0, "MODERATE": 1, "DANGEROUS": 2, "CRITICAL": 3}.get(level, 0)
