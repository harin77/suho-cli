"""Observation — structured result of tool execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


class Observation(BaseModel):
    """Structured result of a single tool execution."""

    tool: str
    args: dict[str, Any]
    success: bool
    exit_code: Optional[int] = None

    # Raw output (potentially truncated by Rust)
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0

    # Metadata
    secrets_redacted: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Derived fields (filled by ObservationAnalyzer)
    summary: Optional[str] = None
    key_findings: list[str] = Field(default_factory=list)
    errors_found: list[str] = Field(default_factory=list)
    files_mentioned: list[str] = Field(default_factory=list)
    requires_followup: bool = False

    def to_llm_context(self, max_chars: int = 2000) -> str:
        """Convert to a compact string for LLM context."""
        parts = [f"Tool: {self.tool}"]

        if self.success:
            parts.append("Status: ✓ Success")
        else:
            parts.append(f"Status: ✗ Failed (exit {self.exit_code})")

        if self.summary:
            parts.append(f"Summary: {self.summary}")

        if self.key_findings:
            parts.append("Key findings:")
            for f in self.key_findings[:5]:
                parts.append(f"  • {f}")

        if self.errors_found:
            parts.append("Errors:")
            for e in self.errors_found[:5]:
                parts.append(f"  ✗ {e}")

        # Include raw output up to limit
        remaining = max_chars - sum(len(p) for p in parts)
        if remaining > 100:
            raw = self.stdout or self.stderr
            if raw:
                truncated = raw[:remaining]
                if len(raw) > remaining:
                    truncated += f"\n... [{len(raw) - remaining} chars omitted]"
                parts.append(f"Output:\n{truncated}")

        return "\n".join(parts)


class ObservationAnalyzer:
    """
    Converts raw tool results into structured Observations.
    Extracts errors, warnings, file paths, and key information.
    """

    def analyze(self, tool: str, args: dict, result: Any) -> Observation:
        """Create an Observation from a raw tool result."""
        obs = Observation(
            tool=tool,
            args=args,
            success=getattr(result, "success", True),
            exit_code=getattr(result, "exit_code", None),
            stdout=getattr(result, "stdout", ""),
            stderr=getattr(result, "stderr", ""),
            duration_ms=getattr(result, "duration_ms", 0),
            secrets_redacted=getattr(result, "secrets_redacted", 0),
        )

        # Extract structured information
        combined_output = f"{obs.stdout}\n{obs.stderr}"
        obs.errors_found = self._extract_errors(combined_output)
        obs.files_mentioned = self._extract_file_paths(combined_output)
        obs.key_findings = self._extract_key_findings(tool, combined_output, obs.success)
        obs.summary = self._generate_summary(tool, obs)
        obs.requires_followup = len(obs.errors_found) > 0 and not obs.success

        return obs

    def _extract_errors(self, output: str) -> list[str]:
        errors = []
        error_indicators = ["error:", "Error:", "ERROR:", "failed:", "Failed:", "exception:"]
        for line in output.splitlines():
            for indicator in error_indicators:
                if indicator in line:
                    clean = line.strip()
                    if clean and len(clean) < 300:
                        errors.append(clean)
                    break
        return errors[:10]  # max 10

    def _extract_file_paths(self, output: str) -> list[str]:
        import re
        # Match common file path patterns
        pattern = r'(?:^|\s)([/~][^\s:,]+\.[a-zA-Z]{1,10})'
        paths = re.findall(pattern, output, re.MULTILINE)
        return list(dict.fromkeys(paths))[:10]  # dedupe, max 10

    def _extract_key_findings(self, tool: str, output: str, success: bool) -> list[str]:
        findings = []

        if "flutter" in tool.lower():
            for line in output.splitlines():
                if any(kw in line for kw in ["error •", "warning •", "info •", "✓", "✗"]):
                    findings.append(line.strip())

        elif "cargo" in tool.lower() or "rust" in tool.lower():
            for line in output.splitlines():
                if line.startswith("error") or line.startswith("warning"):
                    findings.append(line.strip())

        elif "pytest" in tool.lower() or "test" in tool.lower():
            for line in output.splitlines():
                if any(kw in line for kw in ["PASSED", "FAILED", "ERROR", "passed", "failed"]):
                    findings.append(line.strip())

        return findings[:10]

    def _generate_summary(self, tool: str, obs: Observation) -> str:
        if obs.success:
            if obs.stdout:
                lines = obs.stdout.splitlines()
                return f"Completed successfully. {lines[0][:100]}" if lines else "Completed successfully."
            return "Completed successfully (no output)."
        else:
            if obs.errors_found:
                return f"Failed: {obs.errors_found[0][:150]}"
            if obs.stderr:
                return f"Failed: {obs.stderr.splitlines()[0][:150]}"
            return f"Failed with exit code {obs.exit_code}."
