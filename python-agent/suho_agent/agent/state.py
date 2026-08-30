"""TaskState — the complete state of a running agent task."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    VERIFYING = "VERIFYING"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FileChange(BaseModel):
    path: str
    operation: str  # created / modified / deleted / moved
    diff: Optional[str] = None


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any]
    result_success: bool
    result_summary: str
    duration_ms: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PlanStep(BaseModel):
    index: int
    description: str
    tool: Optional[str] = None
    rationale: Optional[str] = None
    risk_level: str = "SAFE"
    completed: bool = False
    skipped: bool = False
    failed: bool = False


class Plan(BaseModel):
    steps: list[PlanStep] = Field(default_factory=list)
    current_step_index: int = 0

    @property
    def current_step(self) -> Optional[PlanStep]:
        if self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    @property
    def is_complete(self) -> bool:
        return all(s.completed or s.skipped for s in self.steps)


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TaskState(BaseModel):
    """Complete state of a running agent task."""

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    user_request: str
    working_directory: str
    mode: str = "interactive"
    status: TaskStatus = TaskStatus.PENDING

    # Planning
    plan: Optional[Plan] = None
    current_step: Optional[str] = None

    # Execution tracking
    completed_steps: list[str] = Field(default_factory=list)
    failed_steps: list[str] = Field(default_factory=list)

    # Tool calls
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_count: int = 0

    # Results
    observations: list[str] = Field(default_factory=list)
    files_changed: list[FileChange] = Field(default_factory=list)
    commands_executed: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    # Limits
    iteration_count: int = 0
    max_iterations: int = 30
    max_tool_calls: int = 100
    retry_count: int = 0
    max_retries: int = 3

    # Token tracking
    token_usage: TokenUsage = Field(default_factory=TokenUsage)

    # Timing
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None

    # Context
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)

    # Cancellation
    cancelled: bool = False

    @property
    def duration_ms(self) -> int:
        end = self.end_time or datetime.now(timezone.utc)
        return int((end - self.start_time).total_seconds() * 1000)

    @property
    def is_at_limit(self) -> bool:
        return (
            self.iteration_count >= self.max_iterations
            or self.tool_call_count >= self.max_tool_calls
        )

    def add_observation(self, observation: str) -> None:
        self.observations.append(observation)
        # Keep last 50 observations to prevent unbounded growth
        if len(self.observations) > 50:
            self.observations = self.observations[-50:]

    def add_tool_call(self, call: ToolCall) -> None:
        self.tool_calls.append(call)
        self.tool_call_count += 1

    def add_error(self, error: str) -> None:
        self.errors.append(error)

    def record_file_change(self, path: str, operation: str, diff: Optional[str] = None) -> None:
        # Avoid duplicate entries
        existing = next((f for f in self.files_changed if f.path == path), None)
        if existing:
            existing.operation = operation
            if diff:
                existing.diff = diff
        else:
            self.files_changed.append(FileChange(path=path, operation=operation, diff=diff))

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "request": self.user_request,
            "status": self.status.value,
            "iterations": self.iteration_count,
            "tool_calls": self.tool_call_count,
            "files_changed": len(self.files_changed),
            "errors": len(self.errors),
            "duration_ms": self.duration_ms,
            "tokens": self.token_usage.total_tokens,
        }
