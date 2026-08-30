"""Filesystem tools — read, write, edit, create, delete, list, search, find, move, copy."""

from __future__ import annotations

import shutil
from typing import Any, Optional

from suho_agent.tools.base import Tool


class ReadFileTool(Tool):
    name = "filesystem.read_file"
    description = "Read the contents of a file."
    category = "filesystem"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read"},
        },
        "required": ["path"],
    }


class WriteFileTool(Tool):
    name = "filesystem.write_file"
    description = "Write content to a file (overwrites existing content)."
    category = "filesystem"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to write"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    }


class EditFileTool(Tool):
    name = "filesystem.edit_file"
    description = "Apply a unified diff patch to a file. Safer than full rewrite."
    category = "filesystem"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to edit"},
            "diff": {"type": "string", "description": "Unified diff to apply"},
        },
        "required": ["path", "diff"],
    }


class CreateFileTool(Tool):
    name = "filesystem.create_file"
    description = "Create a new file with content. Fails if file already exists."
    category = "filesystem"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path for the new file"},
            "content": {"type": "string", "description": "Initial content"},
        },
        "required": ["path", "content"],
    }


class DeleteFileTool(Tool):
    name = "filesystem.delete_file"
    description = "Delete a file. Use with caution."
    category = "filesystem"
    permission_level = "DANGEROUS"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to delete"},
            "recursive": {"type": "boolean", "description": "Delete recursively (for directories)", "default": False},
        },
        "required": ["path"],
    }


class ListDirectoryTool(Tool):
    name = "filesystem.list_directory"
    description = "List files and directories in a path."
    category = "filesystem"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to list", "default": "."},
            "show_hidden": {"type": "boolean", "description": "Include hidden files", "default": False},
            "recursive": {"type": "boolean", "description": "List recursively", "default": False},
        },
        "required": [],
    }


class SearchFilesTool(Tool):
    name = "filesystem.search_files"
    description = "Search for text patterns inside files (like grep)."
    category = "filesystem"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory to search in"},
            "pattern": {"type": "string", "description": "Text or regex pattern to search for"},
            "file_pattern": {"type": "string", "description": "File name glob (e.g. '*.dart')", "default": "*"},
            "case_sensitive": {"type": "boolean", "default": True},
        },
        "required": ["path", "pattern"],
    }


class FindFilesTool(Tool):
    name = "filesystem.find_files"
    description = "Find files by name pattern."
    category = "filesystem"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory to search in"},
            "pattern": {"type": "string", "description": "File name glob pattern"},
        },
        "required": ["path", "pattern"],
    }


class MoveFileTool(Tool):
    name = "filesystem.move_file"
    description = "Move or rename a file."
    category = "filesystem"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "destination"],
    }


class CopyFileTool(Tool):
    name = "filesystem.copy_file"
    description = "Copy a file."
    category = "filesystem"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "destination"],
    }
