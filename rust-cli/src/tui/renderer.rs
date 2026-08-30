//! CLI Event Renderer — converts AgentMessages into clean, professional terminal UI events.
//!
//! Supports 4 Output Modes:
//! 1. HumanUI (default clean, compact developer CLI)
//! 2. Plain (--plain or piped output)
//! 3. Json (--json)
//! 4. Debug (--debug or verbose)

use serde::{Deserialize, Serialize};
use std::io::{self, Write};
use std::path::Path;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutputMode {
    HumanUI,
    Plain,
    Json,
    Debug,
}

#[derive(Debug, Clone)]
pub struct ShellContext {
    pub os: &'static str,
    pub shell: &'static str,
    pub is_windows: bool,
}

impl ShellContext {
    pub fn detect() -> Self {
        let is_win = cfg!(target_os = "windows");
        let os = if is_win {
            "Windows"
        } else if cfg!(target_os = "macos") {
            "macOS"
        } else {
            "Linux"
        };

        let shell = if is_win {
            if std::env::var("PSModulePath").is_ok() {
                "PowerShell"
            } else {
                "CMD"
            }
        } else if std::env::var("SHELL").unwrap_or_default().contains("zsh") {
            "Zsh"
        } else {
            "Bash"
        };

        Self {
            os,
            shell,
            is_windows: is_win,
        }
    }
}

pub struct CliRenderer {
    pub mode: OutputMode,
    pub no_color: bool,
    pub no_banner: bool,
    pub shell_ctx: ShellContext,
}

impl CliRenderer {
    pub fn new(mode: OutputMode, no_color: bool, no_banner: bool) -> Self {
        let is_piped = !atty_stdout();
        let effective_mode = if mode == OutputMode::HumanUI && is_piped {
            OutputMode::Plain
        } else {
            mode
        };

        Self {
            mode: effective_mode,
            no_color: no_color || std::env::var("NO_COLOR").is_ok() || is_piped,
            no_banner,
            shell_ctx: ShellContext::detect(),
        }
    }

    /// Render classic SUHO ASCII banner header
    pub fn render_header(&self, version: &str, cwd: &Path) {
        if self.no_banner || self.mode == OutputMode::Json {
            return;
        }

        let cyan = if self.no_color { "" } else { "\x1b[36m" };
        let bold = if self.no_color { "" } else { "\x1b[1m" };
        let reset = if self.no_color { "" } else { "\x1b[0m" };
        let dim = if self.no_color { "" } else { "\x1b[2m" };

        println!("{}███████╗██╗   ██╗██╗  ██╗ ██████╗", cyan);
        println!("██╔════╝██║   ██║██║  ██║██╔═══██╗");
        println!("███████╗██║   ██║███████║██║   ██║");
        println!("╚════██║██║   ██║██╔══██║██║   ██║");
        println!("███████║╚██████╔╝██║  ██║╚██████╔╝");
        println!("╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝{}", reset);
        println!();
        println!("                 {}AI CLI AGENT{}", bold, reset);
        println!("                    {}v{}{}", dim, version, reset);
        println!();
        println!("{}Workspace: {}{}", dim, cwd.display(), reset);
        println!("{}Type /help for commands, Ctrl+C to exit.{}\n", dim, reset);
    }

    /// Map internal tool name to human-friendly display name
    pub fn friendly_tool_name<'a>(&self, tool: &'a str) -> &'a str {
        match tool {
            "filesystem.list_directory" | "filesystem.list_dir" => "List directory",
            "filesystem.create_directory" | "filesystem.mkdir" | "filesystem.create_dir" => "Create directory",
            "filesystem.read_file" | "filesystem.read" => "Read file",
            "filesystem.write_file" | "filesystem.create_file" | "filesystem.write" | "filesystem.create" => "Write file",
            "filesystem.edit_file" => "Edit file",
            "filesystem.delete_file" | "filesystem.remove_file" => "Delete file",
            "filesystem.find_files" => "Find files",
            "filesystem.search_files" => "Search files",
            "terminal.execute" | "terminal.execute_command" | "shell.execute" => "Run command",
            "git.status" => "Check Git status",
            "git.log" => "View Git history",
            "git.diff" => "View Git diff",
            "git.commit" => "Commit changes",
            "git.push" => "Push to remote",
            "system.system_info" | "system.info" => "Check system info",
            _ => tool,
        }
    }

    /// Render compact plan
    pub fn render_plan(&self, steps: &[crate::ipc::protocol::PlanStep]) {
        if self.mode == OutputMode::Json {
            return;
        }

        let green = if self.no_color { "" } else { "\x1b[32m" };
        let dim = if self.no_color { "" } else { "\x1b[2m" };
        let reset = if self.no_color { "" } else { "\x1b[0m" };

        println!("Planning...");
        println!("{}✓ Plan ready{}\n", green, reset);

        for step in steps {
            println!("  {}{}. {}{}", dim, step.index, step.description, reset);
        }
        println!();
    }

    /// Render tool execution start
    pub fn render_tool_start(&self, tool: &str, _description: &str, args: &serde_json::Value) {
        if self.mode == OutputMode::Json {
            return;
        }

        let cyan = if self.no_color { "" } else { "\x1b[36m" };
        let reset = if self.no_color { "" } else { "\x1b[0m" };

        let display_name = self.friendly_tool_name(tool);
        let detail = if tool.starts_with("terminal.") {
            args.get("command").and_then(|v| v.as_str()).map(|s| format!(" ($ {})", s)).unwrap_or_default()
        } else if tool.starts_with("filesystem.") {
            args.get("path").and_then(|v| v.as_str()).map(|s| format!(" ({})", s)).unwrap_or_default()
        } else {
            String::new()
        };

        if self.mode == OutputMode::Debug {
            println!("{}→ [{}] {}{}{}", cyan, tool, display_name, detail, reset);
        } else {
            println!("{}→ {}{}{}", cyan, display_name, detail, reset);
        }
    }

    /// Render tool success result
    pub fn render_tool_success(&self, tool: &str, duration_ms: u64, summary: &str) {
        if self.mode == OutputMode::Json {
            return;
        }

        let green = if self.no_color { "" } else { "\x1b[32m" };
        let reset = if self.no_color { "" } else { "\x1b[0m" };

        let display_name = self.friendly_tool_name(tool);
        if summary.is_empty() {
            println!("{}✓{} {} {}ms", green, reset, display_name, duration_ms);
        } else {
            println!("{}✓{} {} {}", green, reset, summary, reset);
        }
    }

    /// Render tool failure result
    pub fn render_tool_failure(&self, tool: &str, exit_code: Option<i32>, stderr: &str) {
        if self.mode == OutputMode::Json {
            return;
        }

        let red = if self.no_color { "" } else { "\x1b[31m" };
        let dim = if self.no_color { "" } else { "\x1b[2m" };
        let reset = if self.no_color { "" } else { "\x1b[0m" };

        let display_name = self.friendly_tool_name(tool);
        println!("{}✗ {} failed (exit {}){}", red, display_name, exit_code.unwrap_or(-1), reset);
        if !stderr.is_empty() {
            let first_line = stderr.lines().next().unwrap_or("").trim();
            if !first_line.is_empty() {
                println!("  {}{}{}", dim, first_line, reset);
            }
        }
    }

    /// Render task completion summary
    pub fn render_completion(&self, summary: &str, duration_ms: u64, files_changed: &[crate::ipc::protocol::FileChange]) {
        if self.mode == OutputMode::Json {
            let json_out = serde_json::json!({
                "status": "completed",
                "duration_ms": duration_ms,
                "files_changed": files_changed,
                "summary": summary
            });
            println!("{}", json_out.to_string());
            return;
        }

        let green = if self.no_color { "" } else { "\x1b[32m" };
        let bold = if self.no_color { "" } else { "\x1b[1m" };
        let dim = if self.no_color { "" } else { "\x1b[2m" };
        let reset = if self.no_color { "" } else { "\x1b[0m" };
        let red = if self.no_color { "" } else { "\x1b[31m" };

        println!("\n{}✓ Task completed in {:.1}s{}\n", green, (duration_ms as f64) / 1000.0, reset);

        if !files_changed.is_empty() {
            println!("{}Files changed:{}\n", bold, reset);
            for fc in files_changed {
                let symbol = match fc.operation {
                    crate::ipc::protocol::FileOperation::Created => format!("{}+{}", green, reset),
                    crate::ipc::protocol::FileOperation::Modified => format!("{}~{}", green, reset),
                    crate::ipc::protocol::FileOperation::Deleted => format!("{}-{}", red, reset),
                    _ => format!("{}•{}", dim, reset),
                };
                println!("  {} {}", symbol, fc.path);
            }
            println!();
        }
    }
}

fn atty_stdout() -> bool {
    crossterm::ansi_support::supports_ansi()
}
