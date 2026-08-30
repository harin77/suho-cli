"""Unit tests for project detection."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from suho_agent.detection.project import ProjectDetector, ProjectType


class TestProjectDetector:
    def detect(self, files: dict[str, str]) -> object:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path, content in files.items():
                full = root / path
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content)
            detector = ProjectDetector()
            return detector.detect(str(root))

    def test_flutter_detected(self):
        result = self.detect({"pubspec.yaml": "name: myapp\nversion: 1.0.0"})
        assert result is not None
        assert result.type == ProjectType.FLUTTER
        assert result.metadata.get("name") == "myapp"

    def test_rust_detected(self):
        result = self.detect({"Cargo.toml": '[package]\nname = "myapp"\nversion = "0.1.0"'})
        assert result is not None
        assert result.type == ProjectType.RUST
        assert result.metadata.get("name") == "myapp"

    def test_python_detected(self):
        result = self.detect({"pyproject.toml": '[project]\nname = "myapp"'})
        assert result is not None
        assert result.type == ProjectType.PYTHON

    def test_node_detected(self):
        result = self.detect({"package.json": '{"name": "myapp", "version": "1.0.0"}'})
        assert result is not None
        assert result.type == ProjectType.NODE

    def test_empty_dir_returns_none(self):
        result = self.detect({})
        assert result is None

    def test_flutter_takes_priority_over_python(self):
        # pubspec.yaml + requirements.txt → Flutter wins
        result = self.detect({
            "pubspec.yaml": "name: myapp",
            "requirements.txt": "requests",
        })
        assert result is not None
        assert result.type == ProjectType.FLUTTER
