"""Policy Engine — 5-layer tool request validation.

Layers:
  1. SchemaValidator   — args match tool's JSON schema (Pydantic)
  2. PathValidator     — no path traversal
  3. CommandParser     — shell token analysis
  4. PatternClassifier — SAFE/MODERATE/DANGEROUS/CRITICAL classification
  5. SessionPolicy     — session-level allow/deny rules

This engine is ADVISORY. Final authority is Rust SecurityGate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from suho_agent.policy.classifier import PatternClassifier
from suho_agent.policy.command_parser import CommandParser
from suho_agent.policy.path_validator import PathValidator
from suho_agent.policy.schema_validator import SchemaValidator
from suho_agent.policy.session_policy import SessionPolicy

log = structlog.get_logger(__name__)


@dataclass
class PolicyResult:
    level: str  # SAFE / MODERATE / DANGEROUS / CRITICAL
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    requires_prompt: bool = False
    blocking_reason: str | None = None


class PolicyEngine:
    """
    Orchestrates all 5 validation layers.

    Design rule:
      PolicyEngine outputs a RECOMMENDATION.
      Rust SecurityGate makes the FINAL decision.
    """

    def __init__(self) -> None:
        self._schema_validator = SchemaValidator()
        self._path_validator = PathValidator()
        self._command_parser = CommandParser()
        self._classifier = PatternClassifier()
        self._session_policy = SessionPolicy()

    async def evaluate(
        self,
        tool: str,
        args: dict[str, Any],
        cwd: str = ".",
    ) -> PolicyResult:
        """Run all 5 layers and return advisory PolicyResult."""
        reasons: list[str] = []

        # ── Layer 1: Schema Validation ─────────────────────────────────────
        schema_ok, schema_error = self._schema_validator.validate(tool, args)
        if not schema_ok:
            return PolicyResult(
                level="SAFE",
                allowed=False,
                reasons=[f"Schema validation failed: {schema_error}"],
                blocking_reason=schema_error,
            )

        # ── Layer 2: Path Validation ───────────────────────────────────────
        path_ok, path_errors = self._path_validator.validate(args, cwd)
        if not path_ok:
            return PolicyResult(
                level="DANGEROUS",
                allowed=False,
                reasons=path_errors,
                requires_prompt=True,
                blocking_reason=path_errors[0] if path_errors else "Path validation failed",
            )
        if path_errors:
            reasons.extend(path_errors)

        # ── Layer 3: Command Parser ────────────────────────────────────────
        cmd_level, cmd_reasons = self._command_parser.analyze(args)
        reasons.extend(cmd_reasons)

        # ── Layer 4: Pattern Classifier ────────────────────────────────────
        class_level, class_reasons = self._classifier.classify(tool, args)
        reasons.extend(class_reasons)

        # Take the highest level from layers 3 and 4
        effective_level = self._max_level(cmd_level, class_level)

        # ── Layer 5: Session Policy ────────────────────────────────────────
        session_ok, session_reason = self._session_policy.check(tool, effective_level)
        if not session_ok:
            return PolicyResult(
                level=effective_level,
                allowed=False,
                reasons=[session_reason or "Session policy denied"],
                blocking_reason=session_reason,
            )

        requires_prompt = effective_level in ("DANGEROUS", "CRITICAL")

        log.debug(
            "Policy evaluation complete",
            tool=tool,
            level=effective_level,
            reasons=reasons[:3],
        )

        return PolicyResult(
            level=effective_level,
            allowed=True,
            reasons=reasons,
            requires_prompt=requires_prompt,
        )

    @staticmethod
    def _max_level(a: str, b: str) -> str:
        order = {"SAFE": 0, "MODERATE": 1, "DANGEROUS": 2, "CRITICAL": 3}
        return a if order.get(a, 0) >= order.get(b, 0) else b
