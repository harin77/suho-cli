"""Development tools — Flutter, Cargo/Rust, Python/pytest, npm/Node."""

from __future__ import annotations

import shutil
from typing import Optional

from suho_agent.tools.base import Tool


def _check(cmd: str) -> tuple[bool, Optional[str]]:
    return (True, None) if shutil.which(cmd) else (False, f"'{cmd}' not found in PATH")


# ── Flutter / Dart ────────────────────────────────────────────────────────────

class FlutterAnalyzeTool(Tool):
    name = "development.flutter_analyze"
    description = "Run flutter analyze to check for Dart/Flutter errors and warnings."
    category = "development"
    permission_level = "SAFE"
    parameters_schema = {"type": "object", "properties": {"cwd": {"type": "string"}}}
    def is_available(self): return _check("flutter")


class FlutterTestTool(Tool):
    name = "development.flutter_test"
    description = "Run Flutter widget and unit tests."
    category = "development"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "cwd": {"type": "string"},
            "test_file": {"type": "string", "description": "Specific test file (optional)"},
        },
    }
    def is_available(self): return _check("flutter")


class FlutterBuildTool(Tool):
    name = "development.flutter_build"
    description = "Build a Flutter application (apk, ios, web, linux, etc.)."
    category = "development"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Build target: apk, ios, web, linux, macos, windows", "default": "apk"},
            "cwd": {"type": "string"},
            "release": {"type": "boolean", "default": False},
        },
    }
    def is_available(self): return _check("flutter")


# ── Rust / Cargo ──────────────────────────────────────────────────────────────

class CargoCheckTool(Tool):
    name = "development.cargo_check"
    description = "Run cargo check — fast Rust type checking without building."
    category = "development"
    permission_level = "SAFE"
    parameters_schema = {"type": "object", "properties": {"cwd": {"type": "string"}}}
    def is_available(self): return _check("cargo")


class CargoTestTool(Tool):
    name = "development.cargo_test"
    description = "Run Rust tests with cargo test."
    category = "development"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "cwd": {"type": "string"},
            "test_name": {"type": "string", "description": "Optional test filter"},
        },
    }
    def is_available(self): return _check("cargo")


class CargoBuildTool(Tool):
    name = "development.cargo_build"
    description = "Build Rust project with cargo build."
    category = "development"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "cwd": {"type": "string"},
            "release": {"type": "boolean", "default": False},
        },
    }
    def is_available(self): return _check("cargo")


class CargoClippyTool(Tool):
    name = "development.cargo_clippy"
    description = "Run Rust linter (clippy)."
    category = "development"
    permission_level = "SAFE"
    parameters_schema = {"type": "object", "properties": {"cwd": {"type": "string"}}}
    def is_available(self): return _check("cargo")


# ── Python ────────────────────────────────────────────────────────────────────

class PytestRunTool(Tool):
    name = "development.pytest_run"
    description = "Run Python tests with pytest."
    category = "development"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "cwd": {"type": "string"},
            "path": {"type": "string", "description": "Test path or file"},
            "verbose": {"type": "boolean", "default": True},
        },
    }
    def is_available(self): return _check("pytest") or _check("python3")


class PipInstallTool(Tool):
    name = "development.pip_install"
    description = "Install Python packages with pip."
    category = "development"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "packages": {"type": "array", "items": {"type": "string"}},
            "cwd": {"type": "string"},
        },
        "required": ["packages"],
    }
    def is_available(self): return _check("pip3") or _check("pip")


class PythonRunTool(Tool):
    name = "development.python_run"
    description = "Run a Python script."
    category = "development"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "script": {"type": "string", "description": "Script path or -m module"},
            "args": {"type": "array", "items": {"type": "string"}, "default": []},
            "cwd": {"type": "string"},
        },
        "required": ["script"],
    }
    def is_available(self): return _check("python3")


# ── Node / npm ────────────────────────────────────────────────────────────────

class NpmInstallTool(Tool):
    name = "development.npm_install"
    description = "Install Node.js dependencies with npm install."
    category = "development"
    permission_level = "MODERATE"
    parameters_schema = {"type": "object", "properties": {"cwd": {"type": "string"}}}
    def is_available(self): return _check("npm")


class NpmRunTool(Tool):
    name = "development.npm_run"
    description = "Run an npm script (e.g. build, dev, start)."
    category = "development"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "script": {"type": "string", "description": "Script name from package.json"},
            "cwd": {"type": "string"},
        },
        "required": ["script"],
    }
    def is_available(self): return _check("npm")


class NpmTestTool(Tool):
    name = "development.npm_test"
    description = "Run npm test."
    category = "development"
    permission_level = "SAFE"
    parameters_schema = {"type": "object", "properties": {"cwd": {"type": "string"}}}
    def is_available(self): return _check("npm")
