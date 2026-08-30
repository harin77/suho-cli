//! Simple (non-TUI) terminal output mode — color, spinners, structured display.
//! Used when --tui flag is NOT set. This is the default mode.

use anyhow::Result;
use std::io::{self, Write};

use crate::ipc::bridge::AgentBridge;
use crate::ipc::protocol::{AgentMessage, CliMessage, PolicyLevel, TaskStatus};
use crate::security::gate::SecurityGate;
use crate::security::prompt::prompt_permission;
use crate::config::Config;
use crate::executor::process::ProcessExecutor;
use crate::security::sandbox::SandboxConfig;

// ANSI color helpers
const RESET: &str = "\x1b[0m";
const BOLD: &str = "\x1b[1m";
const DIM: &str = "\x1b[2m";
const GREEN: &str = "\x1b[32m";
const YELLOW: &str = "\x1b[33m";
const RED: &str = "\x1b[31m";
const CYAN: &str = "\x1b[36m";
const BLUE: &str = "\x1b[34m";
const MAGENTA: &str = "\x1b[35m";

fn print_header() {
    println!(
        "\n{}{}╔══════════════════════════════════════════╗{}",
        BOLD, BLUE, RESET
    );
    println!(
        "{}{}║           SUHO Agent  v{}{}{}{}",
        BOLD,
        BLUE,
        env!("CARGO_PKG_VERSION"),
        " ".repeat(24 - env!("CARGO_PKG_VERSION").len()),
        "║",
        RESET
    );
    println!(
        "{}{}╚══════════════════════════════════════════╝{}",
        BOLD, BLUE, RESET
    );
    println!();
}

fn status_icon(status: &TaskStatus) -> &'static str {
    match status {
        TaskStatus::Pending => "○",
        TaskStatus::Planning => "🧠",
        TaskStatus::Executing => "⚡",
        TaskStatus::WaitingForApproval => "⚠️ ",
        TaskStatus::Verifying => "🔍",
        TaskStatus::Failed => "✗",
        TaskStatus::Completed => "✓",
        TaskStatus::Cancelled => "⊘",
    }
}

/// Run interactive mode — continuous conversation loop
pub async fn run_simple_interactive(
    mut bridge: AgentBridge,
    cwd: std::path::PathBuf,
    initial_message: Option<String>,
) -> Result<()> {
    print_header();
    println!("{}Interactive mode — type your request. Ctrl+C to exit.{}", DIM, RESET);
    println!("{}Working directory: {}{}\n", DIM, cwd.display(), RESET);

    let config = bridge_config_placeholder();
    let gate = SecurityGate::new(&config);
    let executor = ProcessExecutor::new(config.security.max_file_read_bytes);

    // Set up Ctrl+C handler
    let (cancel_tx, mut cancel_rx) = tokio::sync::mpsc::channel::<()>(1);
    {
        let tx = cancel_tx.clone();
        ctrlc::set_handler(move || {
            let _ = tx.blocking_send(());
        }).ok();
    }

    if let Some(msg) = initial_message {
        let task_id = uuid::Uuid::new_v4().to_string();
        handle_task(&mut bridge, &gate, &executor, &config, &cwd, msg, task_id).await?;
    }

    let stdin = tokio::io::stdin();
    let mut reader = tokio::io::BufReader::new(stdin);

    loop {
        print!("{}>{} ", BOLD, RESET);
        io::stdout().flush()?;

        let mut line = String::new();
        tokio::select! {
            result = tokio::io::AsyncBufReadExt::read_line(
                &mut reader,
                &mut line,
            ) => {
                match result {
                    Ok(0) => break, // EOF
                    Ok(_) => {
                        let input = line.trim().to_string();
                        if input.is_empty() { continue; }
                        if input == "exit" || input == "quit" { break; }

                        let task_id = uuid::Uuid::new_v4().to_string();
                        handle_task(&mut bridge, &gate, &executor, &config, &cwd, input, task_id).await?;
                    }
                    Err(e) => {
                        eprintln!("Input error: {}", e);
                        break;
                    }
                }
            }
            _ = cancel_rx.recv() => {
                println!("\n{}Cancelled.{}", YELLOW, RESET);
                break;
            }
        }
    }

    bridge.shutdown().await?;
    Ok(())
}

/// Run a single task and wait for completion
pub async fn run_task_mode(mut bridge: AgentBridge, msg: CliMessage) -> Result<()> {
    let config = bridge_config_placeholder();
    let gate = SecurityGate::new(&config);
    let executor = ProcessExecutor::new(config.security.max_file_read_bytes);
    let cwd = std::env::current_dir().unwrap_or_default();

    // Extract request text for display
    let request = match &msg {
        CliMessage::TaskRequest { request, .. } => request.clone(),
        CliMessage::Resume { id, .. } => format!("Resume session {:?}", id),
        _ => String::new(),
    };

    let task_id = match &msg {
        CliMessage::TaskRequest { id, .. } => id.clone(),
        _ => uuid::Uuid::new_v4().to_string(),
    };

    print_header();

    if !request.is_empty() {
        println!("{}Task:{} {}", BOLD, RESET, request);
        println!();
    }

    bridge.send(&msg).await?;
    process_messages(&mut bridge, &gate, &executor, &config, &cwd, &task_id).await?;
    bridge.shutdown().await?;
    Ok(())
}

/// Run a oneshot command (tools list, memory, etc.)
pub async fn run_oneshot(mut bridge: AgentBridge, msg: CliMessage) -> Result<()> {
    bridge.send(&msg).await?;

    // Wait for a single response
    if let Some(agent_msg) = bridge.recv_timeout(std::time::Duration::from_secs(10)).await? {
        display_message(&agent_msg);
    }

    bridge.shutdown().await?;
    Ok(())
}

// ─── Core message handling loop ───────────────────────────────────────────────

async fn handle_task(
    bridge: &mut AgentBridge,
    gate: &SecurityGate,
    executor: &ProcessExecutor,
    config: &Config,
    cwd: &std::path::Path,
    request: String,
    task_id: String,
) -> Result<()> {
    let msg = CliMessage::TaskRequest {
        id: task_id.clone(),
        request,
        cwd: cwd.to_string_lossy().to_string(),
        mode: crate::ipc::protocol::RunMode::Interactive,
        max_iterations: config.agent.max_iterations,
        timeout_secs: config.agent.timeout_secs,
    };

    bridge.send(&msg).await?;
    process_messages(bridge, gate, executor, config, cwd, &task_id).await
}

async fn process_messages(
    bridge: &mut AgentBridge,
    gate: &SecurityGate,
    executor: &ProcessExecutor,
    config: &Config,
    cwd: &std::path::Path,
    task_id: &str,
) -> Result<()> {
    let timeout = std::time::Duration::from_secs(config.agent.timeout_secs);

    loop {
        match bridge.recv_timeout(timeout).await {
            Ok(Some(msg)) => {
                let done = handle_agent_message(bridge, gate, executor, config, cwd, msg).await?;
                if done {
                    break;
                }
            }
            Ok(None) => {
                println!("\n{}Agent disconnected.{}", YELLOW, RESET);
                break;
            }
            Err(_) => {
                println!("\n{}{}Timeout waiting for agent response.{}", RED, BOLD, RESET);
                break;
            }
        }
    }

    Ok(())
}

/// Handle a single agent message. Returns true if task is complete.
async fn handle_agent_message(
    bridge: &mut AgentBridge,
    gate: &SecurityGate,
    executor: &ProcessExecutor,
    config: &Config,
    cwd: &std::path::Path,
    msg: AgentMessage,
) -> Result<bool> {
    match msg {
        AgentMessage::StatusUpdate { status, message, step, .. } => {
            let icon = status_icon(&status);
            println!("{} {}{}{}  {}", icon, DIM, step.as_deref().unwrap_or(""), RESET, message);
            Ok(false)
        }

        AgentMessage::StreamChunk { content, .. } => {
            print!("{}", content);
            io::stdout().flush()?;
            Ok(false)
        }

        AgentMessage::Thinking { content, .. } => {
            println!("{}  🧠 {}{}", DIM, content, RESET);
            Ok(false)
        }

        AgentMessage::ToolStarted { tool, description, .. } => {
            println!("\n{}  ⚡ {}{}  {}", CYAN, tool, RESET, description);
            Ok(false)
        }

        AgentMessage::ToolRequest {
            id,
            tool,
            args,
            policy_level,
            description,
            ..
        } => {
            // ── SecurityGate: final allow/deny decision ──────────────────
            let command_preview = args.get("command").and_then(|v| v.as_str()).map(|s| s.to_string());

            let gate_decision = gate
                .evaluate(
                    &tool,
                    &args,
                    &policy_level,
                    &description,
                    command_preview.as_deref(),
                )
                .await;

            match gate_decision {
                crate::security::gate::GateDecision::Allow(constraints) => {
                    // Execute
                    let result = execute_tool(executor, &tool, &args, &constraints, cwd, config).await?;
                    let response = executor.to_tool_result(&result, &id);
                    bridge.send(&response).await?;

                    // Show brief result
                    if result.success {
                        println!("  {}✓{} {} ({}ms)", GREEN, RESET, tool, result.duration_ms);
                    } else {
                        println!("  {}✗{} {} failed (exit {})",
                            RED, RESET, tool,
                            result.exit_code.unwrap_or(-1));
                        if !result.stderr.is_empty() {
                            let preview: String = result.stderr.lines().take(3).collect::<Vec<_>>().join("\n");
                            println!("{}    {}{}", DIM, preview, RESET);
                        }
                    }
                }

                crate::security::gate::GateDecision::RequirePrompt(ctx) => {
                    let decision = prompt_permission(&ctx);
                    gate.record_decision(&tool, &decision).await;

                    match decision {
                        crate::ipc::protocol::PermissionDecision::Deny
                        | crate::ipc::protocol::PermissionDecision::AlwaysDeny => {
                            bridge.send(&CliMessage::ToolDenied {
                                id,
                                reason: "User denied".to_string(),
                                level: policy_level,
                            }).await?;
                        }
                        _ => {
                            let constraints = crate::security::gate::ExecutionConstraints {
                                sandbox: config.security.sandbox,
                                timeout_ms: 30_000,
                                max_output_bytes: config.security.max_file_read_bytes,
                                allowed_paths: config.security.allowed_paths.clone(),
                                network_allowed: true,
                            };
                            let result = execute_tool(executor, &tool, &args, &constraints, cwd, config).await?;
                            let response = executor.to_tool_result(&result, &id);
                            bridge.send(&response).await?;
                        }
                    }
                }

                crate::security::gate::GateDecision::Deny(reason) => {
                    println!("  {}✗ BLOCKED:{} {}", RED, RESET, reason.reason);
                    bridge.send(&CliMessage::ToolDenied {
                        id,
                        reason: reason.reason,
                        level: policy_level,
                    }).await?;
                }
            }

            Ok(false)
        }

        AgentMessage::PermissionRequest { id, tool, description, command_preview, level, consequences, .. } => {
            let ctx = crate::security::gate::PromptContext {
                description,
                command_preview,
                level,
                consequences,
            };
            let decision = prompt_permission(&ctx);
            gate.record_decision(&tool, &decision).await;
            bridge.send(&CliMessage::PermissionDecision { id, decision }).await?;
            Ok(false)
        }

        AgentMessage::TaskComplete { summary, files_changed, tool_calls, token_usage, duration_ms, .. } => {
            println!("\n{}{}✓ Task Complete{}", BOLD, GREEN, RESET);
            println!("{}", summary);

            if !files_changed.is_empty() {
                println!("\n{}Changed files:{}", BOLD, RESET);
                for f in &files_changed {
                    println!("  • {}", f.path);
                }
            }

            println!(
                "\n{}Tool calls:{} {}  {}Tokens:{} {}  {}Time:{} {}ms{}",
                DIM, RESET, tool_calls,
                DIM, RESET, token_usage.total_tokens,
                DIM, RESET, duration_ms,
                RESET
            );

            Ok(true)
        }

        AgentMessage::TaskFailed { error, suggestion, .. } => {
            println!("\n{}{}✗ Task Failed{}", BOLD, RED, RESET);
            println!("{}", error);
            if let Some(s) = suggestion {
                println!("\n{}Suggestion:{} {}", BOLD, RESET, s);
            }
            Ok(true)
        }

        AgentMessage::PlanGenerated { steps, .. } => {
            println!("\n{}{}Plan:{}", BOLD, CYAN, RESET);
            for step in &steps {
                let risk = match step.risk_level {
                    PolicyLevel::Safe => format!("{}safe{}", GREEN, RESET),
                    PolicyLevel::Moderate => format!("{}moderate{}", YELLOW, RESET),
                    PolicyLevel::Dangerous => format!("{}dangerous{}", RED, RESET),
                    PolicyLevel::Critical => format!("{}CRITICAL{}", RED, RESET),
                };
                println!("  {}{}. {} [{}]{}",
                    DIM, step.index, step.description, risk, RESET);
            }
            Ok(true)
        }

        AgentMessage::Info { message, .. } => {
            println!("  {}ℹ  {}{}", DIM, message, RESET);
            Ok(false)
        }

        AgentMessage::AgentError { error, recoverable, .. } => {
            println!("  {}⚠  Agent error: {}{}", YELLOW, error, RESET);
            if !recoverable {
                return Ok(true);
            }
            Ok(false)
        }

        AgentMessage::QueryResponse { data, .. } => {
            println!("{}", serde_json::to_string_pretty(&data)?);
            Ok(true)
        }
    }
}

fn display_message(msg: &AgentMessage) {
    match msg {
        AgentMessage::QueryResponse { data, .. } => {
            println!("{}", serde_json::to_string_pretty(data).unwrap_or_default());
        }
        AgentMessage::Info { message, .. } => println!("{}", message),
        _ => {}
    }
}

/// Dispatch tool execution to the process executor
async fn execute_tool(
    executor: &ProcessExecutor,
    tool: &str,
    args: &serde_json::Value,
    constraints: &crate::security::gate::ExecutionConstraints,
    cwd: &std::path::Path,
    config: &Config,
) -> Result<crate::executor::process::ExecutionResult> {
    let sandbox_cfg = SandboxConfig {
        backend: if constraints.sandbox {
            crate::security::sandbox::SandboxBackend::Firejail
        } else {
            crate::security::sandbox::SandboxBackend::None
        },
        network_allowed: constraints.network_allowed,
        allowed_paths: constraints.allowed_paths.clone(),
        timeout_ms: constraints.timeout_ms,
        max_output_bytes: constraints.max_output_bytes,
    };

    match tool {
        "terminal.execute" | "terminal.execute_command" => {
            let command = args.get("command").and_then(|v| v.as_str()).unwrap_or("");
            let cwd_override = args.get("cwd").and_then(|v| v.as_str());
            let effective_cwd = cwd_override.unwrap_or(cwd.to_str().unwrap_or("."));
            executor.execute_command(command, Some(effective_cwd), args.get("env"), constraints.timeout_ms, &sandbox_cfg).await
        }

        "filesystem.read_file" => {
            let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
            executor.read_file(path, config.security.max_file_read_bytes).await
        }

        "filesystem.write_file" => {
            let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
            let content = args.get("content").and_then(|v| v.as_str()).unwrap_or("");
            executor.write_file(path, content, config.security.max_file_write_bytes).await
        }

        _ => {
            // Unknown tool — treat as terminal command
            let command = args.get("command").and_then(|v| v.as_str()).unwrap_or(tool);
            executor.execute_command(command, Some(cwd.to_str().unwrap_or(".")), None, constraints.timeout_ms, &sandbox_cfg).await
        }
    }
}

/// Placeholder — in production the bridge carries the config
fn bridge_config_placeholder() -> Config {
    Config::default()
}
