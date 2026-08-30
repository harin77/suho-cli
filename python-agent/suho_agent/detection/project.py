"""Project Detector — identifies project type from directory markers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class ProjectType(str, Enum):
    FLUTTER = "flutter"
    RUST = "rust"
    PYTHON = "python"
    NODE = "node"
    UNITY = "unity"
    UNKNOWN = "unknown"


@dataclass
class ProjectInfo:
    type: ProjectType
    root: Path
    markers: list[str]
    metadata: dict[str, str]


# Ordered from most specific to least specific
DETECTION_RULES: list[tuple[ProjectType, list[str]]] = [
    (ProjectType.FLUTTER, ["pubspec.yaml"]),
    (ProjectType.RUST, ["Cargo.toml"]),
    (ProjectType.UNITY, ["ProjectSettings/ProjectVersion.txt", "Assets"]),
    (ProjectType.PYTHON, ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"]),
    (ProjectType.NODE, ["package.json"]),
]


class ProjectDetector:
    """Detects project type from directory marker files."""

    def detect(self, directory: str) -> Optional[ProjectInfo]:
        """Detect project type for a directory."""
        path = Path(directory).resolve()

        # Search CWD and parent directories (up to 3 levels)
        for search_path in [path, path.parent, path.parent.parent]:
            if not search_path.exists():
                continue

            result = self._detect_in_dir(search_path)
            if result:
                return result

        return None

    def _detect_in_dir(self, path: Path) -> Optional[ProjectInfo]:
        for project_type, markers in DETECTION_RULES:
            found_markers = [m for m in markers if (path / m).exists()]
            if found_markers:
                metadata = self._extract_metadata(project_type, path)
                return ProjectInfo(
                    type=project_type,
                    root=path,
                    markers=found_markers,
                    metadata=metadata,
                )
        return None

    def _extract_metadata(self, project_type: ProjectType, path: Path) -> dict[str, str]:
        meta: dict[str, str] = {}

        try:
            if project_type == ProjectType.FLUTTER:
                pubspec = path / "pubspec.yaml"
                if pubspec.exists():
                    content = pubspec.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        if line.startswith("name:"):
                            meta["name"] = line.split(":", 1)[1].strip()
                        if line.startswith("version:"):
                            meta["version"] = line.split(":", 1)[1].strip()

            elif project_type == ProjectType.RUST:
                cargo = path / "Cargo.toml"
                if cargo.exists():
                    content = cargo.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        if line.startswith("name ="):
                            meta["name"] = line.split("=", 1)[1].strip().strip('"')
                        if line.startswith("version ="):
                            meta["version"] = line.split("=", 1)[1].strip().strip('"')

            elif project_type == ProjectType.NODE:
                pkg = path / "package.json"
                if pkg.exists():
                    import json
                    data = json.loads(pkg.read_text(encoding="utf-8"))
                    meta["name"] = data.get("name", "")
                    meta["version"] = data.get("version", "")

            elif project_type == ProjectType.PYTHON:
                pyproject = path / "pyproject.toml"
                if pyproject.exists():
                    content = pyproject.read_text(encoding="utf-8")
                    for line in content.splitlines():
                        if line.strip().startswith("name ="):
                            meta["name"] = line.split("=", 1)[1].strip().strip('"')

        except Exception:
            pass

        # Always check for git
        if (path / ".git").exists():
            meta["git"] = "true"

        return meta
