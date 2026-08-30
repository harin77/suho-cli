use anyhow::Result;
use clap::{Parser, Subcommand};
use std::path::PathBuf;

use crate::config::Config;
use crate::ipc::bridge::AgentBridge;
use crate::tui::app::App;

/// SUHO Agent — CLI-native autonomous AI agent
#[derive(Parser, Debug)]
#[command(
    name = "suho",
    version,
    author,
    about = "SUHO Agent — your terminal-first autonomous AI assistant",
    long_about = None,
    propagate_version = true,
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Option<Commands>,

    /// Working directory override
    #[arg(short = 'C', long, global = true, value_name = "DIR")]
    pub cwd: Option<PathBuf>,

    /// Config file override
    #[arg(long, global = true, value_name = "FILE")]
    pub config: Option<PathBuf>,

    /// Enable full TUI mode
    #[arg(long, global = true)]
    pub tui: bool,

    /// Disable color output
    #[arg(long, global = true)]
    pub no_color: bool,

    /// Verbose output (stackable: -v, -vv, -vvv)
    #[arg(short, long, global = true, action = clap::ArgAction::Count)]
    pub verbose: u8,
}

#[derive(Subcommand, Debug)]
pub enum Commands {
    /// Start interactive chat session with the agent (default)
    Chat {
        /// Initial message to send
        message: Option<String>,
    },

    /// Execute a task autonomously
    Run {
        /// Task description
        task: String,

        /// Show planned actions without executing (dry run)
        #[arg(long)]
        dry_run: bool,

        /// Autonomous mode — minimal interruption (still subject to safety policies)
        #[arg(long)]
        auto: bool,

        /// Maximum agent iterations
        #[arg(long, default_value = "30")]
        max_iterations: u32,

        /// Execution timeout in seconds
        #[arg(long, default_value = "300")]
        timeout: u64,
    },

    /// Generate a plan for a task without executing it
    Plan {
        /// Task description
        task: String,
    },

    /// Ask a single question (no tool use, pure LLM response)
    Ask {
        /// Question to ask
        question: String,
    },

    /// List available tools and their status
    Tools {
        /// Show detailed tool information
        #[arg(long)]
        detailed: bool,

        /// Filter by category
        #[arg(long)]
        category: Option<String>,
    },

    /// Manage agent memory
    Memory {
        #[command(subcommand)]
        action: MemoryCommands,
    },

    /// View and edit configuration
    Config {
        #[command(subcommand)]
        action: Option<ConfigCommands>,
    },

    /// Run system diagnostics
    Doctor,

    /// Show version information
    Version,

    /// Show agent status
    Status,

    /// Show task history
    History {
        /// Number of entries to show
        #[arg(short, long, default_value = "20")]
        limit: usize,
    },

    /// Manage permissions
    Permissions {
        #[command(subcommand)]
        action: Option<PermissionCommands>,
    },

    /// Manage plugins
    Plugins {
        #[command(subcommand)]
        action: Option<PluginCommands>,
    },

    /// List available LLM models
    Models,

    /// Manage sessions
    Session {
        #[command(subcommand)]
        action: Option<SessionCommands>,
    },

    /// Resume a previous session or task
    Resume {
        /// Session or task ID to resume
        id: Option<String>,
    },
}

#[derive(Subcommand, Debug)]
pub enum MemoryCommands {
    /// List stored memories
    List {
        #[arg(short, long, default_value = "20")]
        limit: usize,
    },
    /// Search memories
    Search { query: String },
    /// Delete a memory entry
    Delete { id: String },
    /// Clear all memories
    Clear {
        #[arg(long)]
        confirm: bool,
    },
}

#[derive(Subcommand, Debug)]
pub enum ConfigCommands {
    /// Show current configuration
    Show,
    /// Set a configuration value
    Set { key: String, value: String },
    /// Get a configuration value
    Get { key: String },
    /// Reset to defaults
    Reset {
        #[arg(long)]
        confirm: bool,
    },
    /// Open config file in editor
    Edit,
}

#[derive(Subcommand, Debug)]
pub enum PermissionCommands {
    /// List current session permissions
    List,
    /// Clear all session permissions
    Clear,
    /// Show permission policy
    Policy,
}

#[derive(Subcommand, Debug)]
pub enum PluginCommands {
    /// List installed plugins
    List,
    /// Install a plugin
    Install { name: String },
    /// Remove a plugin
    Remove { name: String },
    /// Show plugin information
    Info { name: String },
}

#[derive(Subcommand, Debug)]
pub enum SessionCommands {
    /// List recent sessions
    List,
    /// Show session details
    Show { id: Option<String> },
    /// Delete a session
    Delete { id: String },
}

/// Main CLI entry point
pub async fn run() -> anyhow::Result<()> {
    let cli = Cli::parse();

    // Resolve working directory
    let cwd = cli
        .cwd
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));

    // Load configuration
    let config = Config::load(cli.config.as_deref()).await?;

    match cli.command {
        // Default: interactive chat
        None | Some(Commands::Chat { message: None }) => {
            run_interactive(cwd, config, cli.tui, None).await
        }

        Some(Commands::Chat { message: Some(msg) }) => {
            run_interactive(cwd, config, cli.tui, Some(msg)).await
        }

        Some(Commands::Run {
            task,
            dry_run,
            auto,
            max_iterations,
            timeout,
        }) => run_task(cwd, config, task, dry_run, auto, max_iterations, timeout).await,

        Some(Commands::Plan { task }) => run_plan(cwd, config, task).await,

        Some(Commands::Ask { question }) => run_ask(cwd, config, question).await,

        Some(Commands::Tools { detailed, category }) => run_tools(config, detailed, category).await,

        Some(Commands::Memory { action }) => run_memory(config, action).await,

        Some(Commands::Config { action }) => run_config(config, action).await,

        Some(Commands::Doctor) => run_doctor(config).await,

        Some(Commands::Version) => {
            println!("suho {}", env!("CARGO_PKG_VERSION"));
            println!("SUHO Agent — CLI-native autonomous AI assistant");
            Ok(())
        }

        Some(Commands::Status) => run_status(config).await,

        Some(Commands::History { limit }) => run_history(config, limit).await,

        Some(Commands::Permissions { action }) => run_permissions(config, action).await,

        Some(Commands::Plugins { action }) => run_plugins(config, action).await,

        Some(Commands::Models) => run_models(config).await,

        Some(Commands::Session { action }) => run_session(config, action).await,

        Some(Commands::Resume { id }) => run_resume(cwd, config, id).await,
    }
}

// ─── Command handlers ────────────────────────────────────────────────────────

async fn run_interactive(
    cwd: PathBuf,
    config: Config,
    use_tui: bool,
    initial_message: Option<String>,
) -> Result<()> {
    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;

    if use_tui {
        let mut app = App::new(bridge);
        app.run(cwd, initial_message).await
    } else {
        // Fallback: simple line-based interactive mode
        crate::tui::simple::run_simple_interactive(bridge, cwd, initial_message).await
    }
}

async fn run_task(
    cwd: PathBuf,
    config: Config,
    task: String,
    dry_run: bool,
    auto: bool,
    max_iterations: u32,
    timeout: u64,
) -> Result<()> {
    use crate::ipc::protocol::{CliMessage, RunMode};

    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;

    let mode = if dry_run {
        RunMode::DryRun
    } else if auto {
        RunMode::Autonomous
    } else {
        RunMode::Interactive
    };

    let msg = CliMessage::TaskRequest {
        id: uuid::Uuid::new_v4().to_string(),
        request: task,
        cwd: cwd.to_string_lossy().to_string(),
        mode,
        max_iterations,
        timeout_secs: timeout,
    };

    crate::tui::simple::run_task_mode(bridge, msg).await
}

async fn run_plan(cwd: PathBuf, config: Config, task: String) -> Result<()> {
    use crate::ipc::protocol::{CliMessage, RunMode};

    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;

    let msg = CliMessage::TaskRequest {
        id: uuid::Uuid::new_v4().to_string(),
        request: task,
        cwd: cwd.to_string_lossy().to_string(),
        mode: RunMode::PlanOnly,
        max_iterations: 5,
        timeout_secs: 60,
    };

    crate::tui::simple::run_task_mode(bridge, msg).await
}

async fn run_ask(cwd: PathBuf, config: Config, question: String) -> Result<()> {
    use crate::ipc::protocol::{CliMessage, RunMode};

    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;

    let msg = CliMessage::TaskRequest {
        id: uuid::Uuid::new_v4().to_string(),
        request: question,
        cwd: cwd.to_string_lossy().to_string(),
        mode: RunMode::AskOnly,
        max_iterations: 1,
        timeout_secs: 30,
    };

    crate::tui::simple::run_task_mode(bridge, msg).await
}

async fn run_tools(config: Config, verbose: bool, category: Option<String>) -> Result<()> {
    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;

    let msg = crate::ipc::protocol::CliMessage::ListTools { verbose, category };
    crate::tui::simple::run_oneshot(bridge, msg).await
}

async fn run_memory(config: Config, action: MemoryCommands) -> Result<()> {
    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;

    let msg = match action {
        MemoryCommands::List { limit } => crate::ipc::protocol::CliMessage::MemoryList { limit },
        MemoryCommands::Search { query } => {
            crate::ipc::protocol::CliMessage::MemorySearch { query }
        }
        MemoryCommands::Delete { id } => crate::ipc::protocol::CliMessage::MemoryDelete { id },
        MemoryCommands::Clear { confirm } => {
            if !confirm {
                eprintln!("Use --confirm to clear all memories.");
                return Ok(());
            }
            crate::ipc::protocol::CliMessage::MemoryClear
        }
    };

    crate::tui::simple::run_oneshot(bridge, msg).await
}

async fn run_config(config: Config, action: Option<ConfigCommands>) -> Result<()> {
    match action {
        None | Some(ConfigCommands::Show) => {
            println!("{}", toml::to_string_pretty(&config)?);
        }
        Some(ConfigCommands::Edit) => {
            let editor = std::env::var("EDITOR").unwrap_or_else(|_| "nano".to_string());
            let path = Config::config_path()?;
            std::process::Command::new(editor).arg(&path).status()?;
        }
        _ => {
            println!("Config subcommand not yet implemented in this version.");
        }
    }
    Ok(())
}

async fn run_doctor(_config: Config) -> Result<()> {
    println!("🔍 SUHO Doctor — System Diagnostics\n");

    // Check Python agent
    let python_cmd = if cfg!(target_os = "windows") { "python" } else { "python3" };
    let python = std::process::Command::new(python_cmd)
        .arg("--version")
        .output();
    match python {
        Ok(o) if o.status.success() => {
            println!("✓ Python: {}", String::from_utf8_lossy(&o.stdout).trim());
        }
        _ => {
            // Try python fallback on Windows
            let py_fallback = std::process::Command::new("py").arg("--version").output();
            match py_fallback {
                Ok(o) if o.status.success() => {
                    println!("✓ Python: {}", String::from_utf8_lossy(&o.stdout).trim());
                }
                _ => println!("✗ Python: not found"),
            }
        }
    }

    // Check uv
    let uv = std::process::Command::new("uv").arg("--version").output();
    match uv {
        Ok(o) if o.status.success() => {
            println!("✓ uv: {}", String::from_utf8_lossy(&o.stdout).trim());
        }
        _ => println!("✗ uv: not found (install from https://docs.astral.sh/uv/)"),
    }

    // Check Ollama
    let ollama = std::process::Command::new("ollama").arg("list").output();
    match ollama {
        Ok(o) if o.status.success() => println!("✓ Ollama: running"),
        _ => println!("⚠ Ollama: not found or not running"),
    }

    // Check git
    let git = std::process::Command::new("git").arg("--version").output();
    match git {
        Ok(o) if o.status.success() => {
            println!("✓ Git: {}", String::from_utf8_lossy(&o.stdout).trim());
        }
        _ => println!("✗ Git: not found"),
    }

    // Config path
    println!("\n📁 Config: {:?}", Config::config_path()?);
    println!("📦 Version: {}", env!("CARGO_PKG_VERSION"));

    Ok(())
}

async fn run_status(config: Config) -> Result<()> {
    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;
    crate::tui::simple::run_oneshot(bridge, crate::ipc::protocol::CliMessage::Status).await
}

async fn run_history(config: Config, limit: usize) -> Result<()> {
    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;
    crate::tui::simple::run_oneshot(
        bridge,
        crate::ipc::protocol::CliMessage::History { limit },
    )
    .await
}

async fn run_permissions(config: Config, action: Option<PermissionCommands>) -> Result<()> {
    // Permission management is local to Rust security gate
    match action {
        None | Some(PermissionCommands::List) => {
            println!("Session permissions: (none set)");
        }
        Some(PermissionCommands::Clear) => {
            println!("Session permissions cleared.");
        }
        Some(PermissionCommands::Policy) => {
            println!("Permission levels:\n");
            println!("  SAFE     — no prompt required");
            println!("  MODERATE — logged, may prompt based on config");
            println!("  DANGEROUS — always prompts for user confirmation");
            println!("  CRITICAL — always prompts, cannot be pre-authorized");
        }
    }
    Ok(())
}

async fn run_plugins(_config: Config, action: Option<PluginCommands>) -> Result<()> {
    println!("Plugin system: coming in V0.7");
    Ok(())
}

async fn run_models(config: Config) -> Result<()> {
    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;
    crate::tui::simple::run_oneshot(bridge, crate::ipc::protocol::CliMessage::ListModels).await
}

async fn run_session(config: Config, action: Option<SessionCommands>) -> Result<()> {
    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;
    let msg = crate::ipc::protocol::CliMessage::SessionList { limit: 20 };
    crate::tui::simple::run_oneshot(bridge, msg).await
}

async fn run_resume(cwd: PathBuf, config: Config, id: Option<String>) -> Result<()> {
    let mut bridge = AgentBridge::new(config).await?;
    bridge.start().await?;
    let msg = crate::ipc::protocol::CliMessage::Resume {
        id,
        cwd: cwd.to_string_lossy().to_string(),
    };
    crate::tui::simple::run_task_mode(bridge, msg).await
}
