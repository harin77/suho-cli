//! Permission prompt — interactive user confirmation in terminal.

use std::io::{self, Write};
use crate::ipc::protocol::{PermissionDecision, PolicyLevel};
use crate::security::gate::PromptContext;

/// Prompt the user for permission in simple (non-TUI) mode.
/// Returns the user's decision.
pub fn prompt_permission(ctx: &PromptContext) -> PermissionDecision {
    let level_str = match ctx.level {
        PolicyLevel::Safe => "\x1b[32mSAFE\x1b[0m",
        PolicyLevel::Moderate => "\x1b[33mMODERATE\x1b[0m",
        PolicyLevel::Dangerous => "\x1b[31mDANGEROUS\x1b[0m",
        PolicyLevel::Critical => "\x1b[1;31mCRITICAL\x1b[0m",
    };

    println!("\n\x1b[1m╔══ Permission Required ══════════════════════════════╗\x1b[0m");
    println!("  Level: {}", level_str);
    println!("  Action: {}", ctx.description);

    if let Some(preview) = &ctx.command_preview {
        println!("  Command: \x1b[36m{}\x1b[0m", preview);
    }

    if !ctx.consequences.is_empty() {
        println!("  Consequences:");
        for c in &ctx.consequences {
            println!("    • {}", c);
        }
    }

    println!("\x1b[1m╠══ Choose ════════════════════════════════════════════╣\x1b[0m");
    println!("  [1] Allow once");
    println!("  [2] Allow for this session");
    println!("  [3] Deny");
    println!("  [4] Always deny (this session)");
    print!("\x1b[1m╚══ Your choice [1-4]: \x1b[0m");

    io::stdout().flush().unwrap();

    let mut input = String::new();
    match io::stdin().read_line(&mut input) {
        Ok(_) => match input.trim() {
            "1" => PermissionDecision::AllowOnce,
            "2" => PermissionDecision::AllowSession,
            "4" => PermissionDecision::AlwaysDeny,
            _ => PermissionDecision::Deny,
        },
        Err(_) => PermissionDecision::Deny,
    }
}

/// TUI-based permission prompt (used when ratatui TUI is active)
/// Returns None if TUI is not available (falls back to simple prompt)
pub fn prompt_permission_tui(ctx: &PromptContext) -> Option<PermissionDecision> {
    // TODO: implement ratatui overlay in V0.21
    None
}
