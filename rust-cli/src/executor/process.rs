//! Process executor — runs subprocesses on behalf of the agent.
//! This is the ONLY place actual subprocess execution happens in Rust.

use anyhow::Result;
use std::path::PathBuf;
use std::process::Stdio;
use std::time::{Duration, Instant};
use tokio::process::Command;

use crate::executor::output::OutputCapture;
use crate::ipc::protocol::CliMessage;
use crate::security::gate::{ExecutionConstraints, GateDecision};
use crate::security::sandbox::SandboxConfig;

/// The result of executing a tool request
#[derive(Debug)]
pub struct ExecutionResult {
    pub success: bool,
    pub exit_code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
    pub duration_ms: u64,
    pub secrets_redacted: u32,
    pub truncated: bool,
}

/// Executes a tool request after it has been approved by SecurityGate
pub struct ProcessExecutor {
    max_output_bytes: usize,
}

impl ProcessExecutor {
    pub fn new(max_output_bytes: usize) -> Self {
        Self { max_output_bytes }
    }

    /// Execute a terminal command
    pub async fn execute_command(
        &self,
        command: &str,
        cwd: Option<&str>,
        env: Option<&serde_json::Value>,
        timeout_ms: u64,
        sandbox: &SandboxConfig,
    ) -> Result<ExecutionResult> {
        let start = Instant::now();

        // Build the command with sandbox wrapping
        let (program, args) = if cfg!(target_os = "windows") {
            // Development mode on Windows
            ("cmd".to_string(), vec!["/C".to_string(), command.to_string()])
        } else {
            sandbox.wrap_command("sh", &["-c".to_string(), command.to_string()])
        };

        let mut cmd = Command::new(&program);
        cmd.args(&args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);

        // Working directory
        if let Some(cwd_str) = cwd {
            cmd.current_dir(cwd_str);
        }

        // Environment
        if let Some(env_map) = env {
            if let Some(obj) = env_map.as_object() {
                for (k, v) in obj {
                    if let Some(val) = v.as_str() {
                        cmd.env(k, val);
                    }
                }
            }
        }

        // Spawn with timeout
        let timeout = Duration::from_millis(timeout_ms);
        let child = cmd.spawn()?;

        let output = tokio::time::timeout(timeout, child.wait_with_output()).await;

        let duration_ms = start.elapsed().as_millis() as u64;

        match output {
            Ok(Ok(out)) => {
                let capture = OutputCapture::new(self.max_output_bytes);
                let (stdout, stderr, truncated, secrets_redacted) =
                    capture.process(&out.stdout, &out.stderr);

                Ok(ExecutionResult {
                    success: out.status.success(),
                    exit_code: out.status.code(),
                    stdout,
                    stderr,
                    duration_ms,
                    secrets_redacted,
                    truncated,
                })
            }
            Ok(Err(e)) => Err(anyhow::anyhow!("Process error: {}", e)),
            Err(_) => {
                Ok(ExecutionResult {
                    success: false,
                    exit_code: None,
                    stdout: String::new(),
                    stderr: format!("Command timed out after {}ms", timeout_ms),
                    duration_ms,
                    secrets_redacted: 0,
                    truncated: false,
                })
            }
        }
    }

    /// Execute a filesystem read operation
    pub async fn read_file(&self, path: &str, max_bytes: usize) -> Result<ExecutionResult> {
        let start = Instant::now();
        let path = PathBuf::from(path);

        if !path.exists() {
            return Ok(ExecutionResult {
                success: false,
                exit_code: Some(1),
                stdout: String::new(),
                stderr: format!("File not found: {}", path.display()),
                duration_ms: start.elapsed().as_millis() as u64,
                secrets_redacted: 0,
                truncated: false,
            });
        }

        let metadata = tokio::fs::metadata(&path).await?;
        if metadata.len() > max_bytes as u64 {
            return Ok(ExecutionResult {
                success: false,
                exit_code: Some(1),
                stdout: String::new(),
                stderr: format!(
                    "File too large: {} bytes (max {})",
                    metadata.len(),
                    max_bytes
                ),
                duration_ms: start.elapsed().as_millis() as u64,
                secrets_redacted: 0,
                truncated: false,
            });
        }

        match tokio::fs::read_to_string(&path).await {
            Ok(content) => {
                let capture = OutputCapture::new(max_bytes);
                let (stdout, _, truncated, secrets_redacted) =
                    capture.process(content.as_bytes(), b"");

                Ok(ExecutionResult {
                    success: true,
                    exit_code: Some(0),
                    stdout,
                    stderr: String::new(),
                    duration_ms: start.elapsed().as_millis() as u64,
                    secrets_redacted,
                    truncated,
                })
            }
            Err(e) => Ok(ExecutionResult {
                success: false,
                exit_code: Some(1),
                stdout: String::new(),
                stderr: format!("Read error: {}", e),
                duration_ms: start.elapsed().as_millis() as u64,
                secrets_redacted: 0,
                truncated: false,
            }),
        }
    }

    /// Execute a filesystem write operation
    pub async fn write_file(&self, path: &str, content: &str, max_bytes: usize) -> Result<ExecutionResult> {
        let start = Instant::now();

        if content.len() > max_bytes {
            return Ok(ExecutionResult {
                success: false,
                exit_code: Some(1),
                stdout: String::new(),
                stderr: format!("Content too large: {} bytes (max {})", content.len(), max_bytes),
                duration_ms: start.elapsed().as_millis() as u64,
                secrets_redacted: 0,
                truncated: false,
            });
        }

        let path = PathBuf::from(path);
        if let Some(parent) = path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }

        match tokio::fs::write(&path, content).await {
            Ok(_) => Ok(ExecutionResult {
                success: true,
                exit_code: Some(0),
                stdout: format!("Written {} bytes to {}", content.len(), path.display()),
                stderr: String::new(),
                duration_ms: start.elapsed().as_millis() as u64,
                secrets_redacted: 0,
                truncated: false,
            }),
            Err(e) => Ok(ExecutionResult {
                success: false,
                exit_code: Some(1),
                stdout: String::new(),
                stderr: format!("Write error: {}", e),
                duration_ms: start.elapsed().as_millis() as u64,
                secrets_redacted: 0,
                truncated: false,
            }),
        }
    }

    /// Convert execution result into a CliMessage::ToolResult
    pub fn to_tool_result(&self, result: &ExecutionResult, request_id: &str) -> CliMessage {
        CliMessage::ToolResult {
            id: request_id.to_string(),
            success: result.success,
            exit_code: result.exit_code,
            stdout: result.stdout.clone(),
            stderr: result.stderr.clone(),
            duration_ms: result.duration_ms,
            secrets_redacted: result.secrets_redacted,
        }
    }
}
