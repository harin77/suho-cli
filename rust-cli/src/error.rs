use thiserror::Error;

#[derive(Debug, Error)]
pub enum SuhoError {
    #[error("Configuration error: {0}")]
    Config(String),

    #[error("IPC error: {0}")]
    Ipc(String),

    #[error("Agent process error: {0}")]
    AgentProcess(String),

    #[error("Permission denied: {0}")]
    PermissionDenied(String),

    #[error("Security gate rejected: {0}")]
    SecurityGate(String),

    #[error("Executor error: {0}")]
    Executor(String),

    #[error("Timeout: {0}")]
    Timeout(String),

    #[error("User cancelled")]
    Cancelled,

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

pub type Result<T> = std::result::Result<T, SuhoError>;
