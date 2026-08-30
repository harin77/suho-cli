"""Layer 3: Command Parser — shell token analysis to detect dangerous constructs."""

from __future__ import annotations

from typing import Any


# Shell constructs that escalate risk
SUBSHELL_PATTERNS = [
    "$(",     # command substitution
    "`",      # backtick substitution
    "| sh",   # pipe to shell
    "| bash",
    "| zsh",
    "| dash",
    ";",      # command chaining (warn, not block)
    "&&",     # conditional chaining
    "||",     # conditional chaining
]

REDIRECT_DANGEROUS = [
    ">/etc/",
    ">/usr/",
    ">/bin/",
    ">/sbin/",
    ">/proc/",
    ">/dev/",
]

# Commands that elevate privilege
PRIVILEGE_ESCALATION = [
    "sudo",
    "su -",
    "su root",
    "doas",
    "pkexec",
]

# Highly destructive patterns
DESTRUCTIVE = [
    "rm -rf /",
    "rm -Rf /",
    "rm -r /",
    "mkfs",
    "fdisk",
    "dd if=",
    "shred",
    "wipefs",
    ":(){:|:&};:",  # fork bomb
]

# Dangerous commands
DANGEROUS_COMMANDS = [
    "rm -rf",
    "rm -Rf",
    "rm -r",
    "rm -R",
]


class CommandParser:
    """
    Layer 3: Shell command token analysis.
    Analyzes shell syntax to detect injection and dangerous constructs.
    """

    def analyze(self, args: dict[str, Any]) -> tuple[str, list[str]]:
        """Returns (level, reasons)."""
        command = args.get("command")
        if not isinstance(command, str):
            return "SAFE", []

        level = "SAFE"
        reasons: list[str] = []

        # Check destructive patterns first
        for pattern in DESTRUCTIVE:
            if pattern in command:
                return "CRITICAL", [f"Destructive pattern detected: '{pattern}'"]

        # Check dangerous command patterns
        for pattern in DANGEROUS_COMMANDS:
            if pattern in command:
                level = max_level(level, "DANGEROUS")
                reasons.append(f"Dangerous command pattern: '{pattern}'")

        # Check privilege escalation
        for pattern in PRIVILEGE_ESCALATION:
            if command.strip().startswith(pattern) or f" {pattern} " in command:
                level = "DANGEROUS"
                reasons.append(f"Privilege escalation: '{pattern}'")

        # Check subshell injection
        for pattern in SUBSHELL_PATTERNS:
            if pattern in command:
                if pattern in ("$(","`","| sh","| bash","| zsh","| dash"):
                    level = max_level(level, "DANGEROUS")
                    reasons.append(f"Potential shell injection: '{pattern}'")
                else:
                    level = max_level(level, "MODERATE")
                    reasons.append(f"Command chaining detected: '{pattern}'")

        # Check dangerous redirects
        for pattern in REDIRECT_DANGEROUS:
            if pattern in command:
                level = max_level(level, "DANGEROUS")
                reasons.append(f"Dangerous redirect target: '{pattern}'")

        # Try to use bashlex for deeper analysis
        try:
            import bashlex
            parts = list(bashlex.parse(command))
            for part in parts:
                self._analyze_bashlex_node(part, reasons)
                if reasons:
                    level = max_level(level, "MODERATE")
        except ImportError:
            pass  # bashlex not available, rely on pattern matching
        except Exception:
            pass  # bashlex parse error (complex commands)

        return level, reasons

    def _analyze_bashlex_node(self, node: Any, reasons: list[str]) -> None:
        """Recursively analyze bashlex AST nodes."""
        if not hasattr(node, "kind"):
            return

        if node.kind == "command_substitution":
            reasons.append("Command substitution detected in shell AST")

        if node.kind == "compound":
            reasons.append("Compound command (subshell/loop) detected")

        # Recurse
        for part in getattr(node, "parts", []):
            self._analyze_bashlex_node(part, reasons)


def max_level(a: str, b: str) -> str:
    order = {"SAFE": 0, "MODERATE": 1, "DANGEROUS": 2, "CRITICAL": 3}
    return a if order.get(a, 0) >= order.get(b, 0) else b
