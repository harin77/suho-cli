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

            # Check sensitive system patterns
            sensitive_patterns = [
                "/etc/shadow", "/etc/passwd", "/etc/sudoers",
                "/proc/", "/sys/", "~/.ssh/", "~/.gnupg/", "~/.aws/credentials", "/root/"
            ]
            for pattern in sensitive_patterns:
                if pattern in value:
                    return False, [f"Access to sensitive path pattern '{pattern}' is blocked"]

            # Resolve path relative to CWD to check traversal
            try:
                abs_cwd = Path(cwd).resolve()
                path_obj = Path(value).expanduser()
                is_abs = path_obj.is_absolute() or value.startswith("/") or value.startswith("\\") or value.startswith("~")
                if is_abs:
                    abs_path = path_obj.resolve() if path_obj.is_absolute() else Path(value).resolve()
                else:
                    abs_path = (abs_cwd / path_obj).resolve()

                has_traversal_str = "../" in value or "..\\" in value
                is_outside = not str(abs_path).startswith(str(abs_cwd))

                if has_traversal_str or (is_outside and not is_abs):
                    return False, [f"Path traversal detected in '{key}': '{value}' escapes working directory '{abs_cwd}'"]
                elif is_outside and is_abs:
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
