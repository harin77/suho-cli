"""Git tools — status, diff, log, branch, add, commit, pull, push, checkout."""

from __future__ import annotations

import shutil
from typing import Optional

from suho_agent.tools.base import Tool


def _git_available() -> tuple[bool, Optional[str]]:
    return (True, None) if shutil.which("git") else (False, "git not found in PATH")


class GitStatusTool(Tool):
    name = "git.status"
    description = "Show git repository status (changed, staged, untracked files)."
    category = "git"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "cwd": {"type": "string", "description": "Repository path"},
        },
    }
    def is_available(self): return _git_available()


class GitDiffTool(Tool):
    name = "git.diff"
    description = "Show git diff (unstaged changes or between refs)."
    category = "git"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Optional ref to diff against"},
            "cwd": {"type": "string"},
            "file": {"type": "string", "description": "Specific file to diff"},
        },
    }
    def is_available(self): return _git_available()


class GitLogTool(Tool):
    name = "git.log"
    description = "Show recent git commit history."
    category = "git"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 10},
            "cwd": {"type": "string"},
        },
    }
    def is_available(self): return _git_available()


class GitBranchTool(Tool):
    name = "git.branch"
    description = "List git branches."
    category = "git"
    permission_level = "SAFE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "cwd": {"type": "string"},
            "all": {"type": "boolean", "description": "Show remote branches too", "default": False},
        },
    }
    def is_available(self): return _git_available()


class GitCheckoutTool(Tool):
    name = "git.checkout"
    description = "Checkout a git branch or file."
    category = "git"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "ref": {"type": "string", "description": "Branch, tag, or commit"},
            "create": {"type": "boolean", "description": "Create new branch", "default": False},
            "cwd": {"type": "string"},
        },
        "required": ["ref"],
    }
    def is_available(self): return _git_available()


class GitAddTool(Tool):
    name = "git.add"
    description = "Stage files for git commit."
    category = "git"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files to stage (empty = all)",
            },
            "cwd": {"type": "string"},
        },
    }
    def is_available(self): return _git_available()


class GitCommitTool(Tool):
    name = "git.commit"
    description = "Create a git commit with a message."
    category = "git"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Commit message"},
            "cwd": {"type": "string"},
        },
        "required": ["message"],
    }
    def is_available(self): return _git_available()


class GitPullTool(Tool):
    name = "git.pull"
    description = "Pull latest changes from remote."
    category = "git"
    permission_level = "MODERATE"
    parameters_schema = {
        "type": "object",
        "properties": {
            "cwd": {"type": "string"},
            "remote": {"type": "string", "default": "origin"},
        },
    }
    def is_available(self): return _git_available()


class GitPushTool(Tool):
    name = "git.push"
    description = "Push commits to remote repository. Requires approval."
    category = "git"
    permission_level = "DANGEROUS"
    parameters_schema = {
        "type": "object",
        "properties": {
            "cwd": {"type": "string"},
            "remote": {"type": "string", "default": "origin"},
            "branch": {"type": "string"},
        },
    }
    def is_available(self): return _git_available()
