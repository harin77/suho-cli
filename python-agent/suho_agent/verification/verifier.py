"""Verification system — runs project-appropriate verification after changes."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, Any, Optional

import structlog

if TYPE_CHECKING:
    from suho_agent.agent.state import TaskState
    from suho_agent.ipc.bridge import IPCBridge

log = structlog.get_logger(__name__)


class VerificationResult:
    def __init__(self, tool: str, success: bool, output: str) -> None:
        self.tool = tool
        self.success = success
        self.output = output

    def to_llm_context(self) -> str:
        status = "✓ PASSED" if self.success else "✗ FAILED"
        return f"Verification [{self.tool}]: {status}\n{self.output[:500]}"


class VerificationSystem:
    """
    Runs project-appropriate verification after task changes.
    Detects project type and runs relevant checks.
    """

    def __init__(self, bridge: "IPCBridge", state: "TaskState") -> None:
        self._bridge = bridge
        self._state = state

    async def verify(
        self,
        working_directory: str,
        files_changed: list[str],
    ) -> list[VerificationResult]:
        """Run all relevant verification checks."""
        from suho_agent.detection.project import ProjectDetector, ProjectType

        detector = ProjectDetector()
        project = detector.detect(working_directory)
        results = []

        log.info("Running verification", project_type=project.type.value if project else "unknown")

        if project is None:
            return results

        await self._bridge.send_status(
            task_id=self._state.task_id,
            status="VERIFYING",
            message=f"Verifying {project.type.value} project...",
        )

        match project.type:
            case ProjectType.FLUTTER:
                results += await self._verify_flutter(working_directory)

            case ProjectType.RUST:
                results += await self._verify_rust(working_directory)

            case ProjectType.PYTHON:
                results += await self._verify_python(working_directory)

            case ProjectType.NODE:
                results += await self._verify_node(working_directory)

            case _:
                pass  # Unknown project type — skip verification

        return results

    async def _run_check(self, command: str, cwd: str, tool_name: str) -> VerificationResult:
        """Execute a verification command via IPC and return result."""
        from uuid import uuid4
        from suho_agent.policy.engine import PolicyEngine

        policy = PolicyEngine()
        policy_result = await policy.evaluate(
            tool="terminal.execute",
            args={"command": command},
            cwd=cwd,
        )

        result_msg = await self._bridge.send_tool_request(
            request_id=str(uuid4()),
            task_id=self._state.task_id,
            tool="terminal.execute",
            args={"command": command, "cwd": cwd, "timeout": 120},
            policy_level=policy_result.level,
            policy_reasons=policy_result.reasons,
            description=f"Verification: {command}",
        )

        output = getattr(result_msg, "stdout", "") + getattr(result_msg, "stderr", "")
        success = getattr(result_msg, "success", False)

        return VerificationResult(tool_name, success, output)

    async def _verify_flutter(self, cwd: str) -> list[VerificationResult]:
        results = []
        if shutil.which("flutter"):
            results.append(await self._run_check("flutter analyze", cwd, "flutter analyze"))
            results.append(await self._run_check("flutter test", cwd, "flutter test"))
        return results

    async def _verify_rust(self, cwd: str) -> list[VerificationResult]:
        results = []
        if shutil.which("cargo"):
            results.append(await self._run_check("cargo check", cwd, "cargo check"))
            results.append(await self._run_check("cargo clippy -- -D warnings", cwd, "cargo clippy"))
            results.append(await self._run_check("cargo test", cwd, "cargo test"))
        return results

    async def _verify_python(self, cwd: str) -> list[VerificationResult]:
        results = []
        if shutil.which("pytest"):
            results.append(await self._run_check("pytest --tb=short -q", cwd, "pytest"))
        elif shutil.which("python3"):
            results.append(await self._run_check("python3 -m pytest --tb=short -q", cwd, "pytest"))
        return results

    async def _verify_node(self, cwd: str) -> list[VerificationResult]:
        results = []
        if shutil.which("npm"):
            results.append(await self._run_check("npm test", cwd, "npm test"))
        return results
