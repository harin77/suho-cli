//! IPC Protocol — newline-delimited JSON messages between Rust CLI and Python agent.
//!
//! Design principles:
//! - Python side REQUESTS operations via AgentMessage
//! - Rust side DECIDES via GateDecision and sends CliMessage responses
//! - All messages are newline-terminated JSON objects
//! - Message IDs link requests to responses

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

// ─── Direction: CLI → Python ──────────────────────────────────────────────────

/// Messages sent FROM Rust CLI TO Python agent
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum CliMessage {
    /// Initial task request
    TaskRequest {
        id: String,
        request: String,
        cwd: String,
        mode: RunMode,
        max_iterations: u32,
        timeout_secs: u64,
    },

    /// Result of a tool execution (Rust ran it, returning result to Python)
    ToolResult {
        /// Matches the id in AgentMessage::ToolRequest
        id: String,
        success: bool,
        exit_code: Option<i32>,
        stdout: String,
        stderr: String,
        duration_ms: u64,
        /// Redacted secrets report (if any secrets were found and redacted)
        secrets_redacted: u32,
    },

    /// Tool execution denied by security gate
    ToolDenied {
        id: String,
        reason: String,
        level: PolicyLevel,
    },

    /// User permission decision (after interactive prompt)
    PermissionDecision {
        /// Matches the id in AgentMessage::PermissionRequest
        id: String,
        decision: PermissionDecision,
    },

    /// Cancel the active task
    Cancel { task_id: String },

    /// Session/config info (sent after connection)
    SessionInfo {
        task_id: String,
        config: serde_json::Value,
    },

    /// Query messages from CLI to Agent
    ListTools { verbose: bool, category: Option<String> },
    MemoryList { limit: usize },
    MemorySearch { query: String },
    MemoryDelete { id: String },
    MemoryClear,
    Status,
    History { limit: usize },
    ListModels,
    SessionList { limit: usize },
    Resume { id: Option<String>, cwd: String },

    /// List tools request response
    ToolsResponse { tools: Vec<ToolInfo> },

    /// Models list response
    ModelsResponse { models: Vec<ModelInfo> },

    /// History response
    HistoryResponse { entries: Vec<HistoryEntry> },

    /// Status response
    StatusResponse { status: AgentStatus },

    /// Generic oneshot response
    Response { data: serde_json::Value },

    /// Error from Rust side
    RustError { message: String },
}

// ─── Direction: Python → CLI ──────────────────────────────────────────────────

/// Messages sent FROM Python agent TO Rust CLI
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum AgentMessage {
    /// Agent requests a tool to be executed
    /// Rust SecurityGate makes the final allow/deny decision
    ToolRequest {
        id: String,
        task_id: String,
        tool: String,
        args: serde_json::Value,
        /// Policy Engine's assessment (advisory — Rust may override)
        policy_level: PolicyLevel,
        policy_reasons: Vec<String>,
        /// Human-readable description of what this will do
        description: String,
    },

    /// Agent requests user permission (for operations that need explicit approval)
    PermissionRequest {
        id: String,
        task_id: String,
        tool: String,
        description: String,
        command_preview: Option<String>,
        level: PolicyLevel,
        /// What will happen if allowed
        consequences: Vec<String>,
    },

    /// Agent status update (for UI display)
    StatusUpdate {
        task_id: String,
        status: TaskStatus,
        message: String,
        step: Option<String>,
        progress: Option<f32>,
    },

    /// Streaming LLM output chunk
    StreamChunk { task_id: String, content: String },

    /// Tool execution started (before result)
    ToolStarted {
        task_id: String,
        tool: String,
        description: String,
    },

    /// Task completed successfully
    TaskComplete {
        task_id: String,
        summary: String,
        files_changed: Vec<FileChange>,
        tool_calls: u32,
        iterations: u32,
        token_usage: TokenUsage,
        duration_ms: u64,
    },

    /// Task failed
    TaskFailed {
        task_id: String,
        error: String,
        recoverable: bool,
        suggestion: Option<String>,
    },

    /// Plan generated (for plan-only mode)
    PlanGenerated {
        task_id: String,
        steps: Vec<PlanStep>,
    },

    /// LLM thinking (shown in verbose mode)
    Thinking { task_id: String, content: String },

    /// General info message
    Info { task_id: String, message: String },

    /// Error from Python side
    AgentError {
        task_id: String,
        error: String,
        recoverable: bool,
    },

    /// Response to CliMessage::ListTools etc.
    QueryResponse {
        id: String,
        data: serde_json::Value,
    },
}

// ─── Shared types ─────────────────────────────────────────────────────────────

/// Execution mode for a task
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum RunMode {
    /// Interactive — agent checks in for MODERATE+ operations
    Interactive,
    /// Autonomous — minimal interruption (DANGEROUS/CRITICAL still prompt)
    Autonomous,
    /// Dry run — show planned actions only
    DryRun,
    /// Plan only — generate plan, do not execute
    PlanOnly,
    /// Ask only — pure LLM response, no tool use
    AskOnly,
}

/// Security classification level
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PolicyLevel {
    Safe,
    Moderate,
    Dangerous,
    Critical,
}

/// User's permission decision
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum PermissionDecision {
    AllowOnce,
    AllowSession,
    AllowTool,
    Deny,
    AlwaysDeny,
}

/// Task lifecycle status
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum TaskStatus {
    Pending,
    Planning,
    Executing,
    WaitingForApproval,
    Verifying,
    Failed,
    Completed,
    Cancelled,
}

/// A file that was changed during a task
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileChange {
    pub path: String,
    pub operation: FileOperation,
    pub diff: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FileOperation {
    Created,
    Modified,
    Deleted,
    Moved { from: String },
}

/// Token usage for a task
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TokenUsage {
    #[serde(default)]
    pub input_tokens: u64,
    #[serde(default)]
    pub output_tokens: u64,
    #[serde(default)]
    pub total_tokens: u64,
    #[serde(default)]
    pub estimated_cost_usd: Option<f64>,
}

/// A step in a generated plan
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlanStep {
    pub index: u32,
    pub description: String,
    pub tool: Option<String>,
    pub rationale: Option<String>,
    pub risk_level: PolicyLevel,
}

/// Tool metadata for listing
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolInfo {
    pub name: String,
    pub description: String,
    pub category: String,
    pub permission_level: PolicyLevel,
    pub available: bool,
    pub unavailable_reason: Option<String>,
}

/// Model metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelInfo {
    pub name: String,
    pub provider: String,
    pub available: bool,
    pub context_length: Option<usize>,
}

/// History entry
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    pub task_id: String,
    pub request: String,
    pub status: TaskStatus,
    pub created_at: DateTime<Utc>,
    pub duration_ms: Option<u64>,
    pub tool_calls: Option<u32>,
}

/// Agent status for status command
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentStatus {
    pub active_task: Option<String>,
    pub model: String,
    pub provider: String,
    pub memory_enabled: bool,
    pub total_tasks_run: u64,
    pub uptime_secs: u64,
}
