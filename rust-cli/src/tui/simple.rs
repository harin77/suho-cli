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
        TaskStatus::Planning => "○",
        TaskStatus::Executing => "→",
        TaskStatus::WaitingForApproval => "!",
        TaskStatus::Verifying => "?",
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
    let config = Config::load(None).await.unwrap_or_default();
    let renderer = crate::tui::renderer::CliRenderer::new(
        if config.ui.json { crate::tui::renderer::OutputMode::Json }
        else if config.ui.plain { crate::tui::renderer::OutputMode::Plain }
        else if config.ui.debug { crate::tui::renderer::OutputMode::Debug }
        else { crate::tui::renderer::OutputMode::HumanUI },
        config.ui.no_color,
        config.ui.no_banner,
    );
    renderer.render_header("0.2.0", &cwd);

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

                        // Slash command handling
                        if input.starts_with('/') {
                            let handled = handle_slash_command(&mut bridge, &input).await?;
                            if handled {
                                continue;
                            }
                        }

                        let mut task_prompt = input.clone();
                        for prefix in &["suho run ", "suho ask ", "suho plan ", "suho "] {
                            if task_prompt.to_lowercase().starts_with(prefix) {
                                task_prompt = task_prompt[prefix.len()..].trim().to_string();
                            }
                        }
                        if task_prompt.starts_with('"') && task_prompt.ends_with('"') && task_prompt.len() >= 2 {
                            task_prompt = task_prompt[1..task_prompt.len()-1].to_string();
                        }

                        if task_prompt == "exit" || task_prompt == "quit" { break; }

                        let task_id = uuid::Uuid::new_v4().to_string();
                        handle_task(&mut bridge, &gate, &executor, &config, &cwd, task_prompt, task_id).await?;
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
    let title = if request.len() > 45 {
        format!("{}...", &request[..45])
    } else {
        request.clone()
    };
    let now = chrono::Local::now().format("%Y-%m-%d %H:%M").to_string();
    Config::save_conversation(crate::config::SavedConversation {
        id: task_id.clone(),
        title,
        cwd: cwd.to_string_lossy().to_string(),
        model: config.model.model.clone(),
        timestamp: now,
        initial_request: request.clone(),
    });

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
    _task_id: &str,
) -> Result<()> {
    let timeout = std::time::Duration::from_secs(config.agent.timeout_secs.max(600));
    let mut retries = 0;

    loop {
        match bridge.recv_timeout(timeout).await {
            Ok(Some(msg)) => {
                retries = 0;
                let done = handle_agent_message(bridge, gate, executor, config, cwd, msg).await?;
                if done {
                    break;
                }
            }
            Ok(None) => {
                if retries < 3 {
                    retries += 1;
                    println!("\n{}~ Connection lost. Reconnecting (attempt {}/3)...{}", YELLOW, retries, RESET);
                    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                    continue;
                }
                println!("\n{}Agent disconnected.{}", YELLOW, RESET);
                break;
            }
            Err(_) => {
                if retries < 3 {
                    retries += 1;
                    println!("\n{}~ Response timeout. Reconnecting (attempt {}/3)...{}", YELLOW, retries, RESET);
                    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                    continue;
                }
                println!("\n{}{}Task failed: Connection timeout after retries.{}", RED, BOLD, RESET);
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
            if config.ui.debug || !message.starts_with("Iteration ") {
                let icon = status_icon(&status);
                println!("{} {}{}{}  {}", icon, DIM, step.as_deref().unwrap_or(""), RESET, message);
            }
            Ok(false)
        }

        AgentMessage::StreamChunk { content, .. } => {
            print!("{}", content);
            io::stdout().flush()?;
            Ok(false)
        }

        AgentMessage::Thinking { content, .. } => {
            // Suppress raw internal chain-of-thought in standard mode
            if config.ui.debug {
                println!("\n{}Thinking Mode:{}", BOLD, CYAN);
                for line in content.lines() {
                    println!("  {}{}{}", DIM, line, RESET);
                }
                let _ = io::stdout().flush();
            }
            Ok(false)
        }

        AgentMessage::ToolStarted { tool, description, .. } => {
            if config.ui.debug {
                println!("\n{}  → {}{}  {}", CYAN, tool, RESET, description);
            }
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
            let renderer = crate::tui::renderer::CliRenderer::new(
                if config.ui.json { crate::tui::renderer::OutputMode::Json }
                else if config.ui.plain { crate::tui::renderer::OutputMode::Plain }
                else if config.ui.debug { crate::tui::renderer::OutputMode::Debug }
                else { crate::tui::renderer::OutputMode::HumanUI },
                config.ui.no_color,
                config.ui.no_banner,
            );

            renderer.render_tool_start(&tool, &description, &args);

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
                        renderer.render_tool_success(&tool, result.duration_ms, "");
                    } else {
                        renderer.render_tool_failure(&tool, result.exit_code, &result.stderr);
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

                            if result.success {
                                renderer.render_tool_success(&tool, result.duration_ms, "");
                            } else {
                                renderer.render_tool_failure(&tool, result.exit_code, &result.stderr);
                            }
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

        AgentMessage::TaskComplete { summary, files_changed, tool_calls: _, token_usage: _, duration_ms, .. } => {
            let renderer = crate::tui::renderer::CliRenderer::new(
                if config.ui.json { crate::tui::renderer::OutputMode::Json }
                else if config.ui.plain { crate::tui::renderer::OutputMode::Plain }
                else if config.ui.debug { crate::tui::renderer::OutputMode::Debug }
                else { crate::tui::renderer::OutputMode::HumanUI },
                config.ui.no_color,
                config.ui.no_banner,
            );

            renderer.render_completion(&summary, duration_ms, &files_changed);
            Ok(true)
        }

        AgentMessage::TaskFailed { error, suggestion, .. } => {
            println!("\n{}{}✗ Task failed{}", BOLD, RED, RESET);
            println!("{}", error);
            if let Some(s) = suggestion {
                println!("\n{}Suggested action:{} {}", BOLD, RESET, s);
            }
            Ok(true)
        }

        AgentMessage::PlanGenerated { steps, .. } => {
            let renderer = crate::tui::renderer::CliRenderer::new(
                if config.ui.json { crate::tui::renderer::OutputMode::Json }
                else if config.ui.plain { crate::tui::renderer::OutputMode::Plain }
                else if config.ui.debug { crate::tui::renderer::OutputMode::Debug }
                else { crate::tui::renderer::OutputMode::HumanUI },
                config.ui.no_color,
                config.ui.no_banner,
            );

            renderer.render_plan(&steps);

            print!("{}Proceed with plan? [Y/n]: {}", BOLD, RESET);
            io::stdout().flush()?;
            let mut input = String::new();
            if io::stdin().read_line(&mut input).is_ok() {
                let trimmed = input.trim().to_lowercase();
                if trimmed == "n" || trimmed == "no" {
                    println!("  {}Plan cancelled by user.{}", RED, RESET);
                    return Ok(true);
                }
            }
            Ok(false)
        }

        AgentMessage::Info { message, .. } => {
            println!("  {}i  {}{}", DIM, message, RESET);
            Ok(false)
        }

        AgentMessage::AgentError { error, recoverable, .. } => {
            println!("  {}!  Agent error: {}{}", YELLOW, error, RESET);
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
        "terminal.execute" | "terminal.execute_command" | "terminal.run" | "shell.execute" => {
            let command = args.get("command").and_then(|v| v.as_str()).unwrap_or("");
            let cwd_override = args.get("cwd").and_then(|v| v.as_str());
            let effective_cwd = cwd_override.unwrap_or(cwd.to_str().unwrap_or("."));
            executor.execute_command(command, Some(effective_cwd), args.get("env"), constraints.timeout_ms, &sandbox_cfg).await
        }

        "filesystem.read_file" | "filesystem.read" => {
            let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
            executor.read_file(path, config.security.max_file_read_bytes).await
        }

        "filesystem.create_directory" | "filesystem.mkdir" | "filesystem.create_dir" => {
            let raw_path = args.get("path").and_then(|v| v.as_str()).or_else(|| args.get("directory").and_then(|v| v.as_str())).unwrap_or("");
            let command = if cfg!(target_os = "windows") {
                format!("mkdir \"{}\"", raw_path)
            } else {
                format!("mkdir -p \"{}\"", raw_path)
            };
            executor.execute_command(&command, Some(cwd.to_str().unwrap_or(".")), None, constraints.timeout_ms, &sandbox_cfg).await
        }

        "filesystem.write_file" | "filesystem.create_file" | "filesystem.edit_file" | "filesystem.write" | "filesystem.create" => {
            let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
            let content = args.get("content").and_then(|v| v.as_str()).unwrap_or("");
            executor.write_file(path, content, config.security.max_file_write_bytes).await
        }

        "filesystem.delete_file" | "filesystem.remove_file" => {
            let path = args.get("path").and_then(|v| v.as_str()).unwrap_or("");
            let command = if cfg!(target_os = "windows") {
                format!("del /f /q \"{}\"", path)
            } else {
                format!("rm -f \"{}\"", path)
            };
            executor.execute_command(&command, Some(cwd.to_str().unwrap_or(".")), None, constraints.timeout_ms, &sandbox_cfg).await
        }

        "filesystem.list_directory" | "filesystem.list_dir" => {
            let raw_path = args.get("path").and_then(|v| v.as_str()).unwrap_or(".");
            let path = raw_path.trim_end_matches(&['/', '\\'][..]);
            let path_clean = if path.is_empty() { "." } else { path };

            let target_path = if std::path::Path::new(path_clean).is_absolute() {
                std::path::PathBuf::from(path_clean)
            } else {
                cwd.join(path_clean)
            };

            if !target_path.exists() {
                return Ok(crate::executor::process::ExecutionResult {
                    success: false,
                    exit_code: Some(1),
                    stdout: String::new(),
                    stderr: format!("Directory does not exist: {}", target_path.display()),
                    duration_ms: 0,
                    secrets_redacted: 0,
                    truncated: false,
                });
            }

            let (target_cwd, target_cmd) = if cfg!(target_os = "windows") {
                if target_path.is_absolute() {
                    (Some(target_path.to_str().unwrap_or(".")), "dir /b .".to_string())
                } else if path_clean == "." {
                    (Some(cwd.to_str().unwrap_or(".")), "dir /b .".to_string())
                } else {
                    (Some(cwd.to_str().unwrap_or(".")), format!("dir /b \"{}\"", path_clean))
                }
            } else {
                if target_path.is_absolute() {
                    (Some(target_path.to_str().unwrap_or(".")), "ls -la .".to_string())
                } else {
                    (Some(cwd.to_str().unwrap_or(".")), format!("ls -la \"{}\"", path_clean))
                }
            };
            executor.execute_command(&target_cmd, target_cwd, None, constraints.timeout_ms, &sandbox_cfg).await
        }

        "filesystem.find_files" => {
            let raw_path = args.get("path").and_then(|v| v.as_str()).unwrap_or(".");
            let path = raw_path.trim_end_matches(&['/', '\\'][..]);
            let path_clean = if path.is_empty() { "." } else { path };
            let pattern = args.get("pattern").and_then(|v| v.as_str()).unwrap_or("*");
            let command = if cfg!(target_os = "windows") {
                format!("dir /b /s \"{}\\{}\"", path_clean, pattern)
            } else {
                format!("find \"{}\" -name \"{}\"", path_clean, pattern)
            };
            executor.execute_command(&command, Some(cwd.to_str().unwrap_or(".")), None, constraints.timeout_ms, &sandbox_cfg).await
        }

        "filesystem.search_files" => {
            let raw_path = args.get("path").and_then(|v| v.as_str()).unwrap_or(".");
            let path = raw_path.trim_end_matches(&['/', '\\'][..]);
            let path_clean = if path.is_empty() { "." } else { path };
            let pattern = args.get("pattern").and_then(|v| v.as_str()).unwrap_or("");
            let file_pattern = args.get("file_pattern").and_then(|v| v.as_str()).unwrap_or("*");
            let command = if cfg!(target_os = "windows") {
                format!("findstr /s /i /n \"{}\" \"{}\\{}\"", pattern, path_clean, file_pattern)
            } else {
                format!("grep -rn \"{}\" \"{}\"", pattern, path_clean)
            };
            executor.execute_command(&command, Some(cwd.to_str().unwrap_or(".")), None, constraints.timeout_ms, &sandbox_cfg).await
        }

        "system.system_info" | "system.info" | "sys.info" => {
            let command = if cfg!(target_os = "windows") { "systeminfo" } else { "uname -a" };
            executor.execute_command(command, Some(cwd.to_str().unwrap_or(".")), None, constraints.timeout_ms, &sandbox_cfg).await
        }

        tool if tool.starts_with("git.") => {
            let sub = tool.trim_start_matches("git.");
            let sub_arg = args.get("args").and_then(|v| v.as_str()).unwrap_or("");
            let command = format!("git {} {}", sub, sub_arg);
            executor.execute_command(command.trim(), Some(cwd.to_str().unwrap_or(".")), None, constraints.timeout_ms, &sandbox_cfg).await
        }

        "filesystem.move_file" => {
            let src = args.get("source").and_then(|v| v.as_str()).unwrap_or("");
            let dst = args.get("destination").and_then(|v| v.as_str()).unwrap_or("");
            let command = if cfg!(target_os = "windows") {
                format!("move /y \"{}\" \"{}\"", src, dst)
            } else {
                format!("mv -f \"{}\" \"{}\"", src, dst)
            };
            executor.execute_command(&command, Some(cwd.to_str().unwrap_or(".")), None, constraints.timeout_ms, &sandbox_cfg).await
        }

        "filesystem.copy_file" => {
            let src = args.get("source").and_then(|v| v.as_str()).unwrap_or("");
            let dst = args.get("destination").and_then(|v| v.as_str()).unwrap_or("");
            let command = if cfg!(target_os = "windows") {
                format!("copy /y \"{}\" \"{}\"", src, dst)
            } else {
                format!("cp -f \"{}\" \"{}\"", src, dst)
            };
            executor.execute_command(&command, Some(cwd.to_str().unwrap_or(".")), None, constraints.timeout_ms, &sandbox_cfg).await
        }

        _ => {
            // Unknown tool — treat as terminal command
            let command = args.get("command").and_then(|v| v.as_str()).unwrap_or(tool);
            executor.execute_command(command, Some(cwd.to_str().unwrap_or(".")), None, constraints.timeout_ms, &sandbox_cfg).await
        }
    }
}

/// Handle interactive slash commands starting with '/'
pub async fn handle_slash_command(bridge: &mut AgentBridge, cmd: &str) -> Result<bool> {
    let parts: Vec<&str> = cmd.split_whitespace().collect();
    let command = parts[0].to_lowercase();

    match command.as_str() {
        "/help" | "/h" => {
            print_slash_help();
            Ok(true)
        }

        "/models" | "/providers" | "/provider" => {
            handle_models_menu(bridge).await?;
            Ok(true)
        }

        "/selectmodel" | "/model" | "/m" => {
            handle_select_model(bridge).await?;
            Ok(true)
        }

        "/clear" | "/cls" => {
            print!("\x1B[2J\x1B[1;1H");
            io::stdout().flush()?;
            Ok(true)
        }

        "/tools" | "/t" => {
            bridge.send(&CliMessage::ListTools { verbose: false, category: None }).await?;
            if let Some(AgentMessage::QueryResponse { data, .. }) = bridge.recv_timeout(std::time::Duration::from_secs(10)).await? {
                println!("{}", serde_json::to_string_pretty(&data)?);
            }
            Ok(true)
        }

        "/history" => {
            bridge.send(&CliMessage::History { limit: 10 }).await?;
            if let Some(AgentMessage::QueryResponse { data, .. }) = bridge.recv_timeout(std::time::Duration::from_secs(10)).await? {
                println!("{}", serde_json::to_string_pretty(&data)?);
            }
            Ok(true)
        }

        "/chatlist" | "/chats" | "/cl" => {
            let list = Config::load_conversations();
            if list.is_empty() {
                println!("\n{}No saved conversations found.{}", YELLOW, RESET);
            } else {
                println!("\n{}{}╔════ Saved Conversations ═════════════════════════════════════╗{}", BOLD, CYAN, RESET);
                for (idx, item) in list.iter().enumerate() {
                    println!("  {}[{}] {}{}", BOLD, idx + 1, item.title, RESET);
                    println!("      {}Workspace: {}{}", DIM, item.cwd, RESET);
                    println!("      {}Date: {} | Model: {} | ID: {}{}\n", DIM, item.timestamp, item.model, item.id, RESET);
                }
                println!("{}Type /selectchat <number> to jump back to any conversation.{}\n", DIM, RESET);
            }
            Ok(true)
        }

        "/selectchat" | "/resume" => {
            let parts: Vec<&str> = cmd.split_whitespace().collect();
            let list = Config::load_conversations();
            if list.is_empty() {
                println!("\n{}No saved conversations found.{}", YELLOW, RESET);
                return Ok(true);
            }

            if parts.len() < 2 {
                println!("\n{}Usage: /selectchat <number|id>{}", YELLOW, RESET);
                println!("Example: /selectchat 1\n");
                return Ok(true);
            }

            let target = parts[1];
            let selected = if let Ok(num) = target.parse::<usize>() {
                if num >= 1 && num <= list.len() {
                    Some(&list[num - 1])
                } else {
                    None
                }
            } else {
                list.iter().find(|item| item.id.starts_with(target))
            };

            if let Some(conv) = selected {
                println!("\n{}✓ Loaded Conversation: \"{}\"{}", GREEN, conv.title, RESET);
                println!("  {}Workspace: {}{}", DIM, conv.cwd, RESET);
                println!("  {}Model: {} | ID: {}{}", DIM, conv.model, conv.id, RESET);
                println!("{}Resumed conversation session! Type your next prompt below.{}\n", BOLD, RESET);
            } else {
                println!("\n{}Invalid conversation index or ID. Type /chatlist to see available conversations.{}", RED, RESET);
            }
            Ok(true)
        }

        "/status" | "/s" => {
            bridge.send(&CliMessage::Status).await?;
            if let Some(AgentMessage::QueryResponse { data, .. }) = bridge.recv_timeout(std::time::Duration::from_secs(10)).await? {
                println!("{}", serde_json::to_string_pretty(&data)?);
            }
            Ok(true)
        }

        "/exit" | "/quit" | "/q" => {
            println!("Goodbye!");
            std::process::exit(0);
        }

        _ => {
            println!("{}Unknown slash command '{}'. Type /help for assistance.{}", YELLOW, cmd, RESET);
            Ok(true)
        }
    }
}

fn print_slash_help() {
    println!("\n{}{}╔════ SUHO Agent — Interactive Slash Commands ═══════════╗{}", BOLD, CYAN, RESET);
    println!("  {}/chatlist{}    — Show all saved conversations with project title", BOLD, RESET);
    println!("  {}/selectchat{}  — Switch back to previous conversation by index/ID", BOLD, RESET);
    println!("  {}/models{}      — Select LLM Provider & enter API key", BOLD, RESET);
    println!("  {}/selectmodel{} — Pick active LLM model for current provider", BOLD, RESET);
    println!("  {}/tools{}       — List all 30+ built-in tools and availability", BOLD, RESET);
    println!("  {}/status{}      — Show agent runtime status & active model", BOLD, RESET);
    println!("  {}/clear{}       — Clear the terminal screen", BOLD, RESET);
    println!("  {}/help{}        — Show this help menu", BOLD, RESET);
    println!("  {}/exit{}        — Exit interactive mode\n", BOLD, RESET);

    println!("{}{}Supported Providers:{}", BOLD, BLUE, RESET);
    println!("  • Ollama (local: http://localhost:11434)");
    println!("  • OpenAI (GPT-4o, GPT-4o-mini)");
    println!("  • Anthropic (Claude-3.5-Sonnet, Claude-3.5-Haiku)");
    println!("  • Groq (Llama-3.3-70b)");
    println!("  • DeepSeek (deepseek-chat, deepseek-coder)");
    println!("  • OpenRouter (universal API router)");
    println!("  • Together AI (Meta-Llama-3.1)");
    println!("  • Google Gemini (Gemini-2.5-Flash)");
    println!("  • LM Studio (local: http://localhost:1234/v1)");

    println!("\n{}{}CLI Subcommands (outside interactive mode):{}", BOLD, BLUE, RESET);
    println!("  suho run \"task\"             — Execute task autonomously");
    println!("  suho run --dry-run \"task\"   — View planned actions without executing");
    println!("  suho plan \"task\"            — Generate execution plan only");
    println!("  suho ask \"question\"         — Direct LLM answer without tools");
    println!("  suho doctor                 — Run system diagnostics");
    println!("  suho memory list            — View long-term stored memories");
    println!("  suho resume                 — Resume last session\n");
}

async fn handle_models_menu(bridge: &mut AgentBridge) -> Result<()> {
    println!("\n{}{}╔══ LLM Provider Configuration ═════════════════════════╗{}", BOLD, BLUE, RESET);
    println!("  [1] Ollama (Local default)");
    println!("  [2] OpenAI");
    println!("  [3] Anthropic (Claude)");
    println!("  [4] Groq (Ultra-fast inference)");
    println!("  [5] DeepSeek");
    println!("  [6] OpenRouter");
    println!("  [7] Together AI");
    println!("  [8] Google Gemini");
    println!("  [9] LM Studio (Local server)");
    print!("{}{}Select provider [1-9]: {}", BOLD, RESET, RESET);
    io::stdout().flush()?;

    let mut choice = String::new();
    io::stdin().read_line(&mut choice)?;
    let choice = choice.trim();

    let (provider, default_base, default_model, needs_key) = match choice {
        "2" => ("openai", Some("https://api.openai.com/v1"), "gpt-4o-mini", true),
        "3" => ("anthropic", None, "claude-3-5-sonnet-20241022", true),
        "4" => ("groq", Some("https://api.groq.com/openai/v1"), "llama-3.3-70b-versatile", true),
        "5" => ("deepseek", Some("https://api.deepseek.com/v1"), "deepseek-chat", true),
        "6" => ("openrouter", Some("https://openrouter.ai/api/v1"), "auto", true),
        "7" => ("together", Some("https://api.together.xyz/v1"), "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", true),
        "8" => ("gemini", Some("https://generativelanguage.googleapis.com/v1beta/openai/"), "gemini-2.0-flash", true),
        "9" => ("lmstudio", Some("http://localhost:1234/v1"), "local-model", false),
        _ => ("ollama", Some("http://localhost:11434"), "llama3.2", false),
    };

    let mut api_key: Option<String> = None;
    if needs_key {
        print!("{}Enter API key for {} (or press Enter to skip): {}", BOLD, provider, RESET);
        io::stdout().flush()?;
        let mut key_in = String::new();
        io::stdin().read_line(&mut key_in)?;
        let key_in = key_in.trim();
        if !key_in.is_empty() {
            api_key = Some(key_in.to_string());
        }
    }

    // Save to ~/.config/suho/config.toml
    let mut config = Config::load(None).await.unwrap_or_default();
    config.model.provider = provider.to_string();
    config.model.model = default_model.to_string();
    if let Some(base) = default_base {
        config.model.api_base = Some(base.to_string());
    }
    if let Some(key) = api_key {
        config.model.api_key = Some(key);
    }
    config.save(None).await?;

    println!("\n{}{}✓ Provider updated & saved to ~/.config/suho/config.toml{}", BOLD, GREEN, RESET);
    println!("  Provider: {}{}{}", CYAN, provider, RESET);
    println!("  Default Model: {}{}{}", CYAN, default_model, RESET);
    println!("\n{}Type {}/selectmodel{} to pick a specific model for this provider!{}\n", DIM, BOLD, RESET, RESET);

    Ok(())
}

async fn handle_select_model(bridge: &mut AgentBridge) -> Result<()> {
    let mut config = Config::load(None).await.unwrap_or_default();
    let provider = config.model.provider.clone();

    println!("\n{}{}╔══ Select Model for Provider [{}] ═════════════════════╗{}", BOLD, BLUE, provider, RESET);

    // Fetch models from provider via Python agent
    let mut available_list: Vec<String> = Vec::new();
    println!("{}Fetching models from provider...{}", DIM, RESET);
    if let Ok(_) = bridge.send(&CliMessage::ListModels).await {
        match bridge.recv_timeout(std::time::Duration::from_secs(12)).await {
            Ok(Some(AgentMessage::QueryResponse { data, .. })) => {
                if let Some(models) = data.get("models").and_then(|m| m.as_array()) {
                    for m in models {
                        if let Some(name) = m.get("name").and_then(|n| n.as_str()) {
                            if !available_list.contains(&name.to_string()) {
                                available_list.push(name.to_string());
                            }
                        }
                    }
                }
            }
            _ => {
                println!("{}Could not fetch live API model list, showing standard provider models.{}", DIM, RESET);
            }
        }
    }

    // Add standard preset models per provider if not already present
    let presets: Vec<&str> = match provider.as_str() {
        "gemini" => vec!["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"],
        "openai" => vec!["gpt-4o-mini", "gpt-4o", "o1-mini", "o1"],
        "anthropic" => vec!["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
        "groq" => vec!["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
        "deepseek" => vec!["deepseek-chat", "deepseek-reasoner"],
        "openrouter" => vec!["auto", "anthropic/claude-3.5-sonnet", "google/gemini-2.5-flash", "deepseek/deepseek-r1"],
        "together" => vec!["meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "Qwen/Qwen2.5-Coder-32B-Instruct"],
        "lmstudio" => vec!["local-model"],
        _ => vec!["llama3.2", "qwen2.5-coder", "deepseek-r1"],
    };

    for p in presets {
        if !available_list.contains(&p.to_string()) {
            available_list.push(p.to_string());
        }
    }

    // Display numbered list
    for (idx, name) in available_list.iter().enumerate() {
        let active = if name == &config.model.model { format!(" {}[ACTIVE]{}", GREEN, RESET) } else { String::new() };
        println!("  [{}] {}{}{}", idx + 1, CYAN, name, active);
    }

    print!("\n{}{}Select model [1-{}] or enter custom model name: {}", BOLD, RESET, available_list.len(), RESET);
    io::stdout().flush()?;

    let mut model_in = String::new();
    io::stdin().read_line(&mut model_in)?;
    let model_in = model_in.trim();

    let selected_model = if let Ok(num) = model_in.parse::<usize>() {
        if num >= 1 && num <= available_list.len() {
            available_list[num - 1].clone()
        } else {
            model_in.to_string()
        }
    } else if !model_in.is_empty() {
        model_in.to_string()
    } else {
        config.model.model.clone()
    };

    config.model.model = selected_model.clone();
    config.save(None).await?;

    println!("\n{}{}✓ Active model updated & saved to ~/.config/suho/config.toml{}", BOLD, GREEN, RESET);
    println!("  Provider: {}{}{}", CYAN, provider, RESET);
    println!("  Active Model: {}{}{}\n", CYAN, selected_model, RESET);

    Ok(())
}

/// Placeholder — in production the bridge carries the config
fn bridge_config_placeholder() -> Config {
    Config::default()
}
