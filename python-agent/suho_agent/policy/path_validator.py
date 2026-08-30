"""Layer 2: Path Validator — prevents path traversal and unsafe path access."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


TRAVERSAL_PATTERNS = [
    "../", "..\\",
    "/etc/shadow", "/etc/passwd", "/etc/sudoers",
    "/proc/", "/sys/",
    "~/.ssh/",
    "~/.gnupg/",
    "~/.aws/credentials",
    "/root/",
]


class PathValidator:
    """
    Layer 2: Path Validation.
    Checks all path arguments for traversal attacks and unsafe locations.
    """

    def validate(self, args: dict[str, Any], cwd: str) -> tuple[bool, list[str]]:
        """Returns (safe, list_of_issues)."""
        issues: list[str] = []

        for key, value in args.items():
            if not isinstance(value, str):
                continue
            if not self._looks_like_path(key, value):
                continue

            # Check traversal
            for pattern in TRAVERSAL_PATTERNS:
                if pattern in value:
                    return False, [
                        f"Path traversal detected in '{key}': '{pattern}' found in '{value[:80]}'"
                    ]

            # Warn if path escapes CWD (not blocking, just flag)
            try:
                abs_path = Path(value).expanduser().resolve()
                abs_cwd = Path(cwd).resolve()
                if not str(abs_path).startswith(str(abs_cwd)):
                    issues.append(f"Path '{value}' is outside working directory")
            except Exception:
                pass

        return True, issues

    def _looks_like_path(self, key: str, value: str) -> bool:
        """Heuristic: does this arg look like a file path?"""
        path_keys = {"path", "file", "directory", "dir", "dest", "destination", "src", "source", "target"}
        if any(k in key.lower() for k in path_keys):
            return True
        if value.startswith("/") or value.startswith("~") or value.startswith("./"):
            return True
        if os.sep in value and len(value) > 2:
            return True
        return False
