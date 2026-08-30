//! AgentBridge — spawns the Python agent subprocess and manages bidirectional JSON IPC.

use anyhow::{Context, Result};
use std::path::PathBuf;
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::mpsc;

use crate::config::Config;
use crate::ipc::protocol::{AgentMessage, CliMessage};

/// Bidirectional bridge to the Python agent process
pub struct AgentBridge {
    config: Config,
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    /// Channel for messages coming FROM Python agent
    rx: Option<mpsc::Receiver<AgentMessage>>,
    /// Background task handle reading stdout
    _reader_task: Option<tokio::task::JoinHandle<()>>,
}

impl AgentBridge {
    pub async fn new(config: Config) -> Result<Self> {
        Ok(Self {
            config,
            child: None,
            stdin: None,
            rx: None,
            _reader_task: None,
        })
    }

    /// Spawn the Python agent subprocess
    pub async fn start(&mut self) -> Result<()> {
        let (cmd, args) = self.resolve_python_command()?;

        tracing::debug!("Spawning agent: {} {:?}", cmd, args);

        let mut child = Command::new(&cmd)
            .args(&args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped()) // Pipe Python stderr to prevent terminal bleeding
            .kill_on_drop(true)
            .spawn()
            .with_context(|| format!("Failed to spawn Python agent: {} {:?}", cmd, args))?;

        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| anyhow::anyhow!("Failed to get agent stdin"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| anyhow::anyhow!("Failed to get agent stdout"))?;
        let stderr = child.stderr.take();

        // Background reader for Python stderr -> tracing debug
        if let Some(stderr_stream) = stderr {
            tokio::spawn(async move {
                use tokio::io::AsyncBufReadExt;
                let mut reader = tokio::io::BufReader::new(stderr_stream).lines();
                while let Ok(Some(line)) = reader.next_line().await {
                    tracing::debug!(target: "python_agent", "{}", line);
                }
            });
        }

        // Channel: background reader → bridge consumer
        let (tx, rx) = mpsc::channel::<AgentMessage>(256);

        // Spawn background task reading newline-delimited JSON from stdout
        let reader_task = tokio::spawn(async move {
            let reader = BufReader::new(stdout);
            let mut lines = reader.lines();
            loop {
                match lines.next_line().await {
                    Ok(Some(line)) => {
                        let line = line.trim().to_string();
                        if line.is_empty() {
                            continue;
                        }
                        match serde_json::from_str::<AgentMessage>(&line) {
                            Ok(msg) => {
                                if tx.send(msg).await.is_err() {
                                    break; // receiver dropped
                                }
                            }
                            Err(e) => {
                                tracing::warn!("Failed to parse agent message: {} | line: {}", e, line);
                            }
                        }
                    }
                    Ok(None) => {
                        tracing::info!("Agent stdout closed — process exited");
                        break;
                    }
                    Err(e) => {
                        tracing::error!("Error reading agent stdout: {}", e);
                        break;
                    }
                }
            }
        });

        self.child = Some(child);
        self.stdin = Some(stdin);
        self.rx = Some(rx);
        self._reader_task = Some(reader_task);

        Ok(())
    }

    /// Send a message TO the Python agent
    pub async fn send(&mut self, msg: &CliMessage) -> Result<()> {
        let stdin = self
            .stdin
            .as_mut()
            .ok_or_else(|| anyhow::anyhow!("Agent not started"))?;

        let mut json = serde_json::to_string(msg)?;
        json.push('\n');

        stdin
            .write_all(json.as_bytes())
            .await
            .context("Failed to write to agent stdin")?;
        stdin.flush().await.context("Failed to flush agent stdin")?;

        Ok(())
    }

    /// Receive next message FROM the Python agent (blocking)
    pub async fn recv(&mut self) -> Option<AgentMessage> {
        self.rx.as_mut()?.recv().await
    }

    /// Receive with timeout
    pub async fn recv_timeout(&mut self, duration: std::time::Duration) -> Result<Option<AgentMessage>> {
        let rx = self
            .rx
            .as_mut()
            .ok_or_else(|| anyhow::anyhow!("Agent not started"))?;

        match tokio::time::timeout(duration, rx.recv()).await {
            Ok(msg) => Ok(msg),
            Err(_) => Err(anyhow::anyhow!("Timeout waiting for agent response")),
        }
    }

    /// Gracefully shut down the agent
    pub async fn shutdown(&mut self) -> Result<()> {
        // Close stdin to signal EOF to Python agent
        self.stdin.take();

        if let Some(mut child) = self.child.take() {
            // Give it 3 seconds to clean up
            match tokio::time::timeout(
                std::time::Duration::from_secs(3),
                child.wait(),
            )
            .await
            {
                Ok(Ok(status)) => {
                    tracing::debug!("Agent exited with status: {}", status);
                }
                Ok(Err(e)) => {
                    tracing::warn!("Error waiting for agent: {}", e);
                }
                Err(_) => {
                    tracing::warn!("Agent did not exit cleanly, killing");
                    let _ = child.kill().await;
                }
            }
        }

        Ok(())
    }

    /// Check if the agent process is still running
    pub fn is_running(&mut self) -> bool {
        if let Some(child) = self.child.as_mut() {
            matches!(child.try_wait(), Ok(None))
        } else {
            false
        }
    }

    // ─── Private ──────────────────────────────────────────────────────────────

    fn resolve_python_command(&self) -> Result<(String, Vec<String>)> {
        // If explicit command configured, use it
        if let Some(cmd) = &self.config.agent.python_agent_cmd {
            let parts: Vec<&str> = cmd.split_whitespace().collect();
            if parts.is_empty() {
                return Err(anyhow::anyhow!("Empty python_agent_cmd"));
            }
            return Ok((
                parts[0].to_string(),
                parts[1..].iter().map(|s| s.to_string()).collect(),
            ));
        }

        // Auto-detect: look for python-agent directory relative to binary
        let agent_dir = self.find_agent_dir()?;

        // Use `uv run` if available (preferred — handles virtualenv automatically)
        if which_available("uv") {
            return Ok((
                "uv".to_string(),
                vec![
                    "run".to_string(),
                    "--project".to_string(),
                    agent_dir.to_string_lossy().to_string(),
                    "python".to_string(),
                    "-m".to_string(),
                    "suho_agent.main".to_string(),
                ],
            ));
        }

        // Fallback: direct python / python3
        let python_cmd = if cfg!(target_os = "windows") { "python" } else { "python3" };
        Ok((
            python_cmd.to_string(),
            vec!["-m".to_string(), "suho_agent.main".to_string()],
        ))
    }

    fn find_agent_dir(&self) -> Result<PathBuf> {
        // Config override
        if let Some(dir) = &self.config.agent.python_agent_dir {
            if dir.exists() {
                return Ok(dir.clone());
            }
        }

        // Relative to binary
        if let Ok(exe) = std::env::current_exe() {
            // suho binary is at <root>/target/release/suho
            // python-agent is at <root>/python-agent/
            let candidates = [
                exe.parent().and_then(|p| p.parent()).map(|p| p.join("python-agent")),
                exe.parent().and_then(|p| p.parent()).and_then(|p| p.parent()).map(|p| p.join("python-agent")),
            ];
            for c in candidates.iter().flatten() {
                if c.join("pyproject.toml").exists() {
                    return Ok(c.clone());
                }
            }
        }

        // CWD relative
        let cwd_candidate = std::env::current_dir()?.join("python-agent");
        if cwd_candidate.join("pyproject.toml").exists() {
            return Ok(cwd_candidate);
        }

        Err(anyhow::anyhow!(
            "Cannot find python-agent directory. Set [agent] python_agent_dir in config."
        ))
    }
}

impl Drop for AgentBridge {
    fn drop(&mut self) {
        // kill_on_drop(true) handles process cleanup
        self.stdin.take();
    }
}

fn which_available(cmd: &str) -> bool {
    let check_cmd = if cfg!(target_os = "windows") { "where" } else { "which" };
    std::process::Command::new(check_cmd)
        .arg(cmd)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}
