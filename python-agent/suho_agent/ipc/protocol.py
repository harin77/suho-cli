"""IPC Protocol — Python-side message models matching the Rust protocol exactly."""

from __future__ import annotations

from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, Field


# ─── Agent → CLI (Python sends these) ────────────────────────────────────────

class ToolRequestMessage(BaseModel):
    type: Literal["tool_request"] = "tool_request"
    id: str
    task_id: str
    tool: str
    args: dict[str, Any]
    policy_level: str  # SAFE / MODERATE / DANGEROUS / CRITICAL
    policy_reasons: list[str]
    description: str


class PermissionRequestMessage(BaseModel):
    type: Literal["permission_request"] = "permission_request"
    id: str
    task_id: str
    tool: str
    description: str
    command_preview: Optional[str] = None
    level: str
    consequences: list[str] = Field(default_factory=list)


class StatusUpdateMessage(BaseModel):
    type: Literal["status_update"] = "status_update"
    task_id: str
    status: str  # PENDING / PLANNING / EXECUTING / etc.
    message: str
    step: Optional[str] = None
    progress: Optional[float] = None


class StreamChunkMessage(BaseModel):
    type: Literal["stream_chunk"] = "stream_chunk"
    task_id: str
    content: str


class ToolStartedMessage(BaseModel):
    type: Literal["tool_started"] = "tool_started"
    task_id: str
    tool: str
    description: str


class TaskCompleteMessage(BaseModel):
    type: Literal["task_complete"] = "task_complete"
    task_id: str
    summary: str
    files_changed: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: int = 0
    iterations: int = 0
    token_usage: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0


class TaskFailedMessage(BaseModel):
    type: Literal["task_failed"] = "task_failed"
    task_id: str
    error: str
    recoverable: bool = True
    suggestion: Optional[str] = None


class PlanGeneratedMessage(BaseModel):
    type: Literal["plan_generated"] = "plan_generated"
    task_id: str
    steps: list[dict[str, Any]]


class ThinkingMessage(BaseModel):
    type: Literal["thinking"] = "thinking"
    task_id: str
    content: str


class InfoMessage(BaseModel):
    type: Literal["info"] = "info"
    task_id: str
    message: str


class AgentErrorMessage(BaseModel):
    type: Literal["agent_error"] = "agent_error"
    task_id: str
    error: str
    recoverable: bool = True


class QueryResponseMessage(BaseModel):
    type: Literal["query_response"] = "query_response"
    id: str
    data: Any


# Union of all agent → CLI messages
AgentMessage = Union[
    ToolRequestMessage,
    PermissionRequestMessage,
    StatusUpdateMessage,
    StreamChunkMessage,
    ToolStartedMessage,
    TaskCompleteMessage,
    TaskFailedMessage,
    PlanGeneratedMessage,
    ThinkingMessage,
    InfoMessage,
    AgentErrorMessage,
    QueryResponseMessage,
]


# ─── CLI → Agent (Rust sends these, Python receives) ─────────────────────────

class TaskRequestMessage(BaseModel):
    type: Literal["task_request"] = "task_request"
    id: str
    request: str
    cwd: str
    mode: str  # interactive / autonomous / dry_run / plan_only / ask_only
    max_iterations: int = 30
    timeout_secs: int = 300


class ToolResultMessage(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    id: str
    success: bool
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    secrets_redacted: int = 0


class ToolDeniedMessage(BaseModel):
    type: Literal["tool_denied"] = "tool_denied"
    id: str
    reason: str
    level: str


class PermissionDecisionMessage(BaseModel):
    type: Literal["permission_decision"] = "permission_decision"
    id: str
    decision: str  # allow_once / allow_session / allow_tool / deny / always_deny


class CancelMessage(BaseModel):
    type: Literal["cancel"] = "cancel"
    task_id: str


class SessionInfoMessage(BaseModel):
    type: Literal["session_info"] = "session_info"
    task_id: str
    config: dict[str, Any]


class ListToolsMessage(BaseModel):
    type: Literal["list_tools"] = "list_tools"
    verbose: bool = False
    category: Optional[str] = None


class ListModelsMessage(BaseModel):
    type: Literal["list_models"] = "list_models"


class HistoryMessage(BaseModel):
    type: Literal["history"] = "history"
    limit: int = 20


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"


class MemoryListMessage(BaseModel):
    type: Literal["memory_list"] = "memory_list"
    limit: int = 20


class MemorySearchMessage(BaseModel):
    type: Literal["memory_search"] = "memory_search"
    query: str


class MemoryDeleteMessage(BaseModel):
    type: Literal["memory_delete"] = "memory_delete"
    id: str


class MemoryClearMessage(BaseModel):
    type: Literal["memory_clear"] = "memory_clear"


class SessionListMessage(BaseModel):
    type: Literal["session_list"] = "session_list"
    limit: int = 20


class ResumeMessage(BaseModel):
    type: Literal["resume"] = "resume"
    id: Optional[str] = None
    cwd: str


# Union of all CLI → agent messages
CliMessage = Union[
    TaskRequestMessage,
    ToolResultMessage,
    ToolDeniedMessage,
    PermissionDecisionMessage,
    CancelMessage,
    SessionInfoMessage,
    ListToolsMessage,
    ListModelsMessage,
    HistoryMessage,
    StatusMessage,
    MemoryListMessage,
    MemorySearchMessage,
    MemoryDeleteMessage,
    MemoryClearMessage,
    SessionListMessage,
    ResumeMessage,
]

# TypeAdapters for Pydantic v2 Union parsing
from pydantic import TypeAdapter

cli_message_adapter: TypeAdapter[CliMessage] = TypeAdapter(CliMessage)
agent_message_adapter: TypeAdapter[AgentMessage] = TypeAdapter(AgentMessage)
